from pathlib import Path

import pytest

from bank_payment_ingress import BankOrder, BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from mufg_poll_job import run_mufg_poll
from payment_adapter import BankTransactionClaimStore, PaymentVerificationError


ACCOUNT_ID = "77717777777"


def arrival(*, order_ref: str, amount: int, transaction_id: str):
    return {
        "transactionDate": "2024-03-01",
        "transactionId": transaction_id,
        "paymentApplicantNo": order_ref,
        "debitCreditTypeCode": "1",
        "amount": amount,
    }


def page(*, arrivals, next_flag="0", next_keyword=None):
    value = {
        "nextFlag": next_flag,
        "number": len(arrivals),
        "paymentArrivals": arrivals,
    }
    if next_keyword is not None:
        value["nextKeyword"] = next_keyword
    return value


def ingress(tmp_path: Path):
    orders = BankOrderStore(tmp_path / "orders.sqlite3")
    entitlements = EntitlementStore(tmp_path / "entitlements.sqlite3")
    claims = BankTransactionClaimStore(tmp_path / "claims.sqlite3")
    return BankPaymentIngress(orders=orders, entitlements=entitlements, claims=claims)


def test_two_page_poll_fulfills_only_known_order(tmp_path):
    target = ingress(tmp_path)
    target.orders.create(BankOrder(order_ref="160300", package_id="pkg", buyer_ref="buyer", amount_minor=100000, currency="JPY"))
    pages = {
        None: page(arrivals=[arrival(order_ref="160300", amount=100000, transaction_id="1")], next_flag="1", next_keyword="NEXT-1"),
        "NEXT-1": page(arrivals=[arrival(order_ref="999999", amount=200000, transaction_id="2")]),
    }

    summary = run_mufg_poll(fetch_page=lambda keyword: pages[keyword], account_id=ACCOUNT_ID, ingress=target)

    assert summary.pages == 2
    assert summary.provider_records == 2
    assert summary.normalized == 2
    assert summary.fulfilled == 1
    assert summary.unknown_orders == 1
    assert summary.rejected_known_orders == 0
    assert target.orders.get("160300").status == "PAID"
    assert target.entitlements.authorize_payment(package_id="pkg", payment_ref=next(iter(_payment_refs(target.entitlements, "pkg"))))


def _payment_refs(store: EntitlementStore, package_id: str):
    return [row["payment_ref"] for row in store.list_for_package(package_id)]


def test_repeated_next_keyword_fails_closed(tmp_path):
    target = ingress(tmp_path)
    calls = 0

    def fetch(keyword):
        nonlocal calls
        calls += 1
        return page(arrivals=[], next_flag="1", next_keyword="SAME")

    with pytest.raises(PaymentVerificationError, match="repeated nextKeyword"):
        run_mufg_poll(fetch_page=fetch, account_id=ACCOUNT_ID, ingress=target)
    assert calls == 2


def test_max_pages_fails_closed(tmp_path):
    target = ingress(tmp_path)
    counter = 0

    def fetch(keyword):
        nonlocal counter
        counter += 1
        return page(arrivals=[], next_flag="1", next_keyword=f"K{counter}")

    with pytest.raises(PaymentVerificationError, match="max_pages"):
        run_mufg_poll(fetch_page=fetch, account_id=ACCOUNT_ID, ingress=target, max_pages=2)


def test_known_order_wrong_amount_is_rejected_without_fulfilling(tmp_path):
    target = ingress(tmp_path)
    target.orders.create(BankOrder(order_ref="160300", package_id="pkg", buyer_ref="buyer", amount_minor=100000, currency="JPY"))
    payload = page(arrivals=[arrival(order_ref="160300", amount=99999, transaction_id="1")])

    summary = run_mufg_poll(fetch_page=lambda _: payload, account_id=ACCOUNT_ID, ingress=target)

    assert summary.fulfilled == 0
    assert summary.rejected_known_orders == 1
    assert target.orders.get("160300").status == "AWAITING_PAYMENT"
    assert target.entitlements.list_for_package("pkg") == []


def test_mufg_sequence_no_matches_provider_shape():
    import re
    from mufg_poll_job import MUFGAccountClient
    client = MUFGAccountClient(api_key="dummy", account_id="77717777777")
    first = client._sequence_no()
    second = client._sequence_no()
    assert len(first) == 25
    assert re.fullmatch(r"\d{8}-[A-Z0-9]{16}", first)
    assert first != second
