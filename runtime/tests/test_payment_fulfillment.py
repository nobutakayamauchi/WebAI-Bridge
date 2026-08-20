from __future__ import annotations

from pathlib import Path
import sys

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from entitlements import EntitlementStore
from payment_adapter import BankTransactionClaimStore, PaymentVerificationError, verify_bank_transfer
from payment_fulfillment import fulfill_verified_payment


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


def test_bank_payment_fulfills_once_and_exact_replay_is_idempotent(tmp_path):
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "bank-claims.sqlite3")
    event = verify_bank_transfer(deposit=_deposit(), order=_order())

    first = fulfill_verified_payment(event=event, entitlements=entitlements, bank_claims=claims)
    second = fulfill_verified_payment(event=event, entitlements=entitlements, bank_claims=claims)

    assert first.created is True
    assert second.created is False
    assert first.payment_ref == "bank:mufg:txn-001"
    assert entitlements.authorize_payment(package_id="product-a", payment_ref=first.payment_ref)
    rows = entitlements.list_for_package("product-a")
    assert len(rows) == 1


def test_same_bank_transaction_cannot_fulfill_different_product(tmp_path):
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "bank-claims.sqlite3")
    first = verify_bank_transfer(deposit=_deposit(), order=_order())
    fulfill_verified_payment(event=first, entitlements=entitlements, bank_claims=claims)

    second = verify_bank_transfer(
        deposit=_deposit(order_ref="order-002"),
        order=_order(order_ref="order-002", package_id="product-b", buyer_ref="buyer-2"),
    )
    with pytest.raises(PaymentVerificationError):
        fulfill_verified_payment(event=second, entitlements=entitlements, bank_claims=claims)

    assert entitlements.list_for_package("product-b") == []


def test_revoked_bank_payment_cannot_be_resurrected_by_replay(tmp_path):
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "bank-claims.sqlite3")
    event = verify_bank_transfer(deposit=_deposit(), order=_order())
    fulfilled = fulfill_verified_payment(event=event, entitlements=entitlements, bank_claims=claims)

    assert entitlements.revoke_payment(package_id="product-a", payment_ref=fulfilled.payment_ref) == 1
    assert not entitlements.authorize_payment(package_id="product-a", payment_ref=fulfilled.payment_ref)

    with pytest.raises(PaymentVerificationError):
        fulfill_verified_payment(event=event, entitlements=entitlements, bank_claims=claims)

    assert not entitlements.authorize_payment(package_id="product-a", payment_ref=fulfilled.payment_ref)
    rows = entitlements.list_for_package("product-a")
    assert len(rows) == 1
    assert rows[0]["status"] == "revoked"


def test_bank_payment_requires_durable_claim_store_before_entitlement(tmp_path):
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    event = verify_bank_transfer(deposit=_deposit(), order=_order())

    with pytest.raises(PaymentVerificationError):
        fulfill_verified_payment(event=event, entitlements=entitlements, bank_claims=None)

    assert entitlements.list_for_package("product-a") == []
