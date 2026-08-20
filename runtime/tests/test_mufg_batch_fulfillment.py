from pathlib import Path

from bank_payment_ingress import BankOrder, BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from mufg_batch_fulfillment import fulfill_mufg_batch
from mufg_response_ingress import normalize_mufg_payment_arrivals_response
from payment_adapter import BankTransactionClaimStore

ACCOUNT_ID = "77717777777"


def arrival(*, txid: str, order_ref: str, amount: int):
    return {
        "transactionDate": "2024-03-01",
        "designatedDate": "2024-03-01",
        "transactionId": txid,
        "transactionType": "ヨキンキ",
        "applicantName": "テスト",
        "paymentFinancialInstitutionNameKana": "テストギンコウ",
        "branchNameKana": "ホンテン",
        "paymentApplicantNo": order_ref,
        "debitCreditTypeCode": "1",
        "amount": amount,
    }


def page(records):
    return {"nextFlag": "0", "number": len(records), "paymentArrivals": records}


def stack(tmp_path: Path):
    orders = BankOrderStore(tmp_path / "orders.sqlite3")
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    ingress = BankPaymentIngress(orders=orders, entitlements=entitlements, claims=claims)
    return orders, entitlements, ingress


def test_only_server_side_matching_order_is_fulfilled(tmp_path):
    orders, entitlements, ingress = stack(tmp_path)
    orders.create(BankOrder("160300", "trial-product", "buyer@example.test", 100000, "JPY"))
    batch = normalize_mufg_payment_arrivals_response(
        response=page([
            arrival(txid="1", order_ref="160300", amount=100000),
            arrival(txid="2", order_ref="160301", amount=200000),
            arrival(txid="3", order_ref="160302", amount=150000),
        ]),
        account_id=ACCOUNT_ID,
    )
    result = fulfill_mufg_batch(batch=batch, ingress=ingress)
    assert len(result.fulfilled) == 1
    assert result.fulfilled[0]["order_ref"] == "160300"
    assert len(result.skipped_unknown_orders) == 2
    assert len(result.rejected_known_orders) == 0
    assert orders.get("160300").status == "PAID"
    payment_ref = "bank:mufg:" + result.fulfilled[0]["transaction_ref"]
    assert entitlements.authorize_payment(package_id="trial-product", payment_ref=payment_ref)


def test_known_order_with_wrong_amount_is_rejected_without_entitlement(tmp_path):
    orders, entitlements, ingress = stack(tmp_path)
    orders.create(BankOrder("160300", "trial-product", "buyer@example.test", 100000, "JPY"))
    batch = normalize_mufg_payment_arrivals_response(
        response=page([arrival(txid="1", order_ref="160300", amount=99999)]),
        account_id=ACCOUNT_ID,
    )
    result = fulfill_mufg_batch(batch=batch, ingress=ingress)
    assert len(result.fulfilled) == 0
    assert len(result.rejected_known_orders) == 1
    assert orders.get("160300").status == "AWAITING_PAYMENT"


def test_unknown_orders_never_create_entitlements(tmp_path):
    _, _, ingress = stack(tmp_path)
    batch = normalize_mufg_payment_arrivals_response(
        response=page([arrival(txid="1", order_ref="not-an-order", amount=100000)]),
        account_id=ACCOUNT_ID,
    )
    result = fulfill_mufg_batch(batch=batch, ingress=ingress)
    assert len(result.fulfilled) == 0
    assert len(result.skipped_unknown_orders) == 1
