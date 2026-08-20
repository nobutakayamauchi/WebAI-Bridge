from pathlib import Path

import pytest

from bank_payment_ingress import BankOrder, BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from payment_adapter import BankTransactionClaimStore, PaymentVerificationError


def stack(tmp_path: Path):
    orders = BankOrderStore(tmp_path / "orders.sqlite3")
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    ingress = BankPaymentIngress(orders=orders, entitlements=entitlements, claims=claims)
    return orders, entitlements, ingress


def order():
    return BankOrder("order-300k", "knowledge-300k", "buyer@example.test", 300_000, "JPY")


def deposit(**changes):
    value = {
        "provider": "MUFG_MOCK",
        "transaction_ref": "mufg-txn-001",
        "order_ref": "order-300k",
        "amount_minor": 300_000,
        "currency": "JPY",
        "status": "SETTLED",
    }
    value.update(changes)
    return value


def test_mock_bank_api_input_fulfills_server_side_order(tmp_path):
    orders, entitlements, ingress = stack(tmp_path)
    orders.create(order())
    result = ingress.process(deposit())
    assert result.active is True
    assert result.created is True
    assert entitlements.authorize_payment(package_id="knowledge-300k", payment_ref="bank:mufg_mock:mufg-txn-001")
    assert orders.get("order-300k").status == "PAID"


def test_unknown_order_fails_closed(tmp_path):
    _, _, ingress = stack(tmp_path)
    with pytest.raises(PaymentVerificationError, match="unknown order"):
        ingress.process(deposit(order_ref="attacker-order"))


def test_deposit_cannot_override_server_side_price(tmp_path):
    orders, _, ingress = stack(tmp_path)
    orders.create(order())
    with pytest.raises(PaymentVerificationError, match="amount"):
        ingress.process(deposit(amount_minor=1))


def test_paid_order_rejects_second_deposit(tmp_path):
    orders, _, ingress = stack(tmp_path)
    orders.create(order())
    ingress.process(deposit())
    with pytest.raises(PaymentVerificationError, match="not awaiting payment"):
        ingress.process(deposit(transaction_ref="mufg-txn-002"))
