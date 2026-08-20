import pytest

from mufg_response_ingress import normalize_mufg_payment_arrivals_response
from payment_adapter import PaymentVerificationError


ACCOUNT_ID = "77717777777"


def arrival(**changes):
    value = {
        "transactionDate": "2024-03-01",
        "designatedDate": "2024-03-01",
        "transactionId": "1",
        "transactionType": "ヨキンキ",
        "applicantName": "フツウニユウキンフリコミニン０１",
        "paymentFinancialInstitutionNameKana": "フツウキンユウキカン",
        "branchNameKana": "ハルミ",
        "paymentApplicantNo": "160300",
        "debitCreditTypeCode": "1",
        "amount": 100000,
    }
    value.update(changes)
    return value


def response(**changes):
    value = {
        "nextFlag": "0",
        "number": 2,
        "transactionDateFrom": "2024-03-01",
        "transactionDateTo": "2024-03-31",
        "transactionIdFirst": "1",
        "transactionIdLast": "2",
        "operationDate": "2026-08-21",
        "operationTime": "00:57:08",
        "paymentArrivals": [arrival(), arrival(transactionId="2", paymentApplicantNo="160301", amount=200000)],
    }
    value.update(changes)
    return value


def test_real_shape_page_normalizes_all_records_without_fulfillment():
    batch = normalize_mufg_payment_arrivals_response(response=response(), account_id=ACCOUNT_ID)
    assert batch.declared_number == 2
    assert batch.next_flag == "0"
    assert batch.next_keyword is None
    assert [d["order_ref"] for d in batch.deposits] == ["160300", "160301"]
    assert [d["amount_minor"] for d in batch.deposits] == [100000, 200000]


def test_declared_count_mismatch_fails_closed():
    with pytest.raises(PaymentVerificationError, match="does not match"):
        normalize_mufg_payment_arrivals_response(response=response(number=65), account_id=ACCOUNT_ID)


def test_pagination_requires_keyword():
    with pytest.raises(PaymentVerificationError, match="requires nextKeyword"):
        normalize_mufg_payment_arrivals_response(response=response(nextFlag="1"), account_id=ACCOUNT_ID)


def test_pagination_keyword_is_preserved():
    batch = normalize_mufg_payment_arrivals_response(
        response=response(nextFlag="1", nextKeyword="00000000120261020000111"),
        account_id=ACCOUNT_ID,
    )
    assert batch.next_flag == "1"
    assert batch.next_keyword == "00000000120261020000111"


def test_one_bad_record_rejects_entire_page():
    bad = response(paymentArrivals=[arrival(), arrival(transactionId="2", debitCreditTypeCode="2")])
    with pytest.raises(PaymentVerificationError, match="not an incoming"):
        normalize_mufg_payment_arrivals_response(response=bad, account_id=ACCOUNT_ID)
