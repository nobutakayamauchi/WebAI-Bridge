from pathlib import Path

import pytest

from bank_checkout import BankCheckoutService
from bank_payment_ingress import BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from payment_adapter import BankTransactionClaimStore


def stack(tmp_path: Path):
    orders = BankOrderStore(tmp_path / "orders.sqlite3")
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    ingress = BankPaymentIngress(orders=orders, entitlements=entitlements, claims=claims)
    service = BankCheckoutService(orders, random_digits=lambda: 16030000)
    return orders, entitlements, ingress, service


def test_checkout_ref_is_not_browser_authority(tmp_path):
    orders, _, _, service = stack(tmp_path)
    checkout = service.create(package_id="knowledge-300k", amount_minor=300000)
    assert checkout.order_ref == "16030000"
    stored = orders.get(checkout.order_ref)
    assert stored is not None
    assert stored.claim_hash
    assert checkout.claim_token not in stored.claim_hash
    with pytest.raises(ValueError, match="claim"):
        service.claim_paid(order_ref=checkout.order_ref, claim_token=checkout.order_ref)


def test_paid_bank_order_can_be_claimed_only_with_original_secret(tmp_path):
    orders, entitlements, ingress, service = stack(tmp_path)
    checkout = service.create(package_id="knowledge-300k", amount_minor=300000)
    result = ingress.process({
        "provider": "MUFG",
        "transaction_ref": "real-ish-txn-001",
        "order_ref": checkout.order_ref,
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "SETTLED",
    })
    paid = service.claim_paid(order_ref=checkout.order_ref, claim_token=checkout.claim_token)
    assert paid.status == "PAID"
    assert paid.payment_ref == result.payment_ref
    assert entitlements.authorize_payment(package_id="knowledge-300k", payment_ref=paid.payment_ref)
    with pytest.raises(ValueError, match="claim"):
        service.claim_paid(order_ref=checkout.order_ref, claim_token="wrong-secret")


def test_price_is_server_authority_during_bank_checkout(tmp_path):
    _, _, ingress, service = stack(tmp_path)
    checkout = service.create(package_id="knowledge-300k", amount_minor=300000)
    with pytest.raises(Exception, match="amount"):
        ingress.process({
            "provider": "MUFG",
            "transaction_ref": "underpay-001",
            "order_ref": checkout.order_ref,
            "amount_minor": 1,
            "currency": "JPY",
            "status": "SETTLED",
        })


def test_order_store_migrates_and_persists_payment_ref(tmp_path):
    orders, _, ingress, service = stack(tmp_path)
    checkout = service.create(package_id="knowledge-300k", amount_minor=300000)
    result = ingress.process({
        "provider": "MUFG",
        "transaction_ref": "persist-001",
        "order_ref": checkout.order_ref,
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "SETTLED",
    })
    reopened = BankOrderStore(orders.path).get(checkout.order_ref)
    assert reopened is not None
    assert reopened.status == "PAID"
    assert reopened.payment_ref == result.payment_ref
