from __future__ import annotations

from pathlib import Path
import sys

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from payment_adapter import (
    CLAIMED,
    REPLAY_SAME,
    BankTransactionClaimStore,
    PaymentVerificationError,
    canonicalize_stripe_payment,
    verify_bank_transfer,
)


def test_stripe_verified_result_becomes_provider_neutral_event():
    event = canonicalize_stripe_payment(
        verified={
            "checkout_session_id": "cs_test_1",
            "payment_ref": "pi_1",
            "package_id": "product-a",
            "buyer_ref": "buyer-1",
            "amount_total": 300000,
            "currency": "jpy",
            "payment_link_id": "plink_1",
        }
    )
    assert event.provider == "STRIPE"
    assert event.payment_ref == "pi_1"
    assert event.package_id == "product-a"
    assert event.amount_minor == 300000
    assert event.currency == "JPY"
    assert event.as_entitlement_input() == {
        "package_id": "product-a",
        "payment_ref": "pi_1",
        "buyer_ref": "buyer-1",
    }


def _order(**overrides):
    value = {
        "order_ref": "order-001",
        "package_id": "product-a",
        "buyer_ref": "buyer-1",
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "AWAITING_PAYMENT",
    }
    value.update(overrides)
    return value


def _deposit(**overrides):
    value = {
        "provider": "MUFG",
        "transaction_ref": "txn-001",
        "order_ref": "order-001",
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "SETTLED",
    }
    value.update(overrides)
    return value


def test_exact_settled_bank_transfer_mints_canonical_payment_authority():
    event = verify_bank_transfer(deposit=_deposit(), order=_order())
    assert event.provider == "MUFG"
    assert event.payment_ref == "bank:mufg:txn-001"
    assert event.package_id == "product-a"
    assert event.as_entitlement_input()["buyer_ref"] == "buyer-1"


@pytest.mark.parametrize(
    "deposit,order",
    [
        (_deposit(status="PENDING"), _order()),
        (_deposit(amount_minor=299999), _order()),
        (_deposit(amount_minor=300001), _order()),
        (_deposit(currency="USD"), _order()),
        (_deposit(order_ref="somebody-else"), _order()),
        (_deposit(), _order(status="PAID")),
    ],
)
def test_bank_transfer_fails_closed_when_evidence_is_not_exact(deposit, order):
    with pytest.raises(PaymentVerificationError):
        verify_bank_transfer(deposit=deposit, order=order)


def test_bank_transfer_requires_provider_transaction_identity():
    with pytest.raises(PaymentVerificationError):
        verify_bank_transfer(deposit=_deposit(transaction_ref=""), order=_order())


def test_exact_bank_provider_replay_is_idempotent(tmp_path):
    store = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    event = verify_bank_transfer(deposit=_deposit(), order=_order())
    assert store.claim(event) == CLAIMED
    assert store.claim(event) == REPLAY_SAME


def test_same_bank_transaction_cannot_be_reused_for_different_product(tmp_path):
    store = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    first = verify_bank_transfer(deposit=_deposit(), order=_order())
    assert store.claim(first) == CLAIMED

    second_order = _order(order_ref="order-002", package_id="product-b", buyer_ref="buyer-2")
    second_deposit = _deposit(order_ref="order-002")
    second = verify_bank_transfer(deposit=second_deposit, order=second_order)
    assert second.event_ref == first.event_ref == "txn-001"
    with pytest.raises(PaymentVerificationError, match="already claimed"):
        store.claim(second)


def test_same_transaction_ref_is_scoped_by_bank_provider(tmp_path):
    store = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    mufg = verify_bank_transfer(deposit=_deposit(provider="MUFG"), order=_order())
    gmo = verify_bank_transfer(deposit=_deposit(provider="GMO_AOZORA"), order=_order())
    assert store.claim(mufg) == CLAIMED
    assert store.claim(gmo) == CLAIMED
