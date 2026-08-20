import hashlib

import pytest

from mufg_payment_adapter import normalize_mufg_payment_arrival, normalize_mufg_payment_arrivals_response
from payment_adapter import PaymentVerificationError


ACCOUNT_ID = "12345678901"


def raw(**changes):
    value = {
        "transactionDate": "2026-08-20",
        "designatedDate": "2026-08-20",
        "transactionId": "234",
        "transactionType": "振込",
        "applicantName": "テストカブシキガイシヤ",
        "paymentFinancialInstitutionNameKana": "テストギンコウ",
        "branchNameKana": "ホンテン",
        "paymentApplicantNo": "1234567890",
        "ediInfo": "order-300k",
        "debitCreditTypeCode": "1",
        "amount": 300000,
    }
    value.update(changes)
    return value


def expected_ref(date="2026-08-20", transaction_id="234"):
    return hashlib.sha256(f"{ACCOUNT_ID}|{date}|{transaction_id}".encode()).hexdigest()


def test_official_mufg_142_payment_arrival_normalizes_to_deposit():
    deposit = normalize_mufg_payment_arrival(raw=raw(), account_id=ACCOUNT_ID)
    assert deposit == {
        "provider": "MUFG",
        "transaction_ref": expected_ref(),
        "order_ref": "order-300k",
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "SETTLED",
    }


def test_auto_order_reference_falls_back_to_payment_applicant_number():
    record = raw()
    del record["ediInfo"]
    deposit = normalize_mufg_payment_arrival(raw=record, account_id=ACCOUNT_ID)
    assert deposit["order_ref"] == "1234567890"


def test_payment_applicant_number_can_be_explicit_order_reference():
    deposit = normalize_mufg_payment_arrival(
        raw=raw(ediInfo="ignored"),
        account_id=ACCOUNT_ID,
        order_ref_source="paymentApplicantNo",
    )
    assert deposit["order_ref"] == "1234567890"


def test_outgoing_record_fails_closed():
    with pytest.raises(PaymentVerificationError, match="not an incoming"):
        normalize_mufg_payment_arrival(raw=raw(debitCreditTypeCode="2"), account_id=ACCOUNT_ID)


def test_missing_transaction_identity_fails_closed():
    record = raw()
    del record["transactionId"]
    with pytest.raises(PaymentVerificationError, match="transactionId"):
        normalize_mufg_payment_arrival(raw=record, account_id=ACCOUNT_ID)


def test_account_id_must_match_official_path_shape():
    with pytest.raises(PaymentVerificationError, match="11 characters"):
        normalize_mufg_payment_arrival(raw=raw(), account_id="123")


def test_zero_amount_fails_closed():
    with pytest.raises(PaymentVerificationError, match="positive"):
        normalize_mufg_payment_arrival(raw=raw(amount=0), account_id=ACCOUNT_ID)


def test_transaction_identity_changes_across_dates():
    first = normalize_mufg_payment_arrival(raw=raw(transactionDate="2026-08-20"), account_id=ACCOUNT_ID)
    second = normalize_mufg_payment_arrival(raw=raw(transactionDate="2026-08-21"), account_id=ACCOUNT_ID)
    assert first["transaction_ref"] != second["transaction_ref"]


def test_record_cannot_supply_currency_or_product_authority():
    deposit = normalize_mufg_payment_arrival(
        raw=raw(currency="USD", package_id="attacker-product"),
        account_id=ACCOUNT_ID,
        currency="JPY",
    )
    assert deposit["currency"] == "JPY"
    assert "package_id" not in deposit


def test_full_trial_response_normalizes_all_arrivals():
    response = {
        "nextFlag": "0",
        "number": 2,
        "accountInfo": {"branchNo": "777", "accountNo": "7777777"},
        "paymentArrivals": [
            raw(transactionDate="2024-03-01", transactionId="1", ediInfo="EDI-ORDER-1", amount=100000),
            {
                "transactionDate": "2024-03-01",
                "designatedDate": "2024-03-01",
                "transactionId": "2",
                "transactionType": "ヨキンキ",
                "applicantName": "フツウニユウキンフリコミニン０２",
                "paymentApplicantNo": "160301",
                "debitCreditTypeCode": "1",
                "amount": 200000,
            },
        ],
    }
    deposits = normalize_mufg_payment_arrivals_response(response=response, account_id="77717777777")
    assert len(deposits) == 2
    assert deposits[0]["order_ref"] == "EDI-ORDER-1"
    assert deposits[1]["order_ref"] == "160301"
    assert deposits[1]["amount_minor"] == 200000


def test_response_count_mismatch_fails_closed():
    response = {"number": 2, "paymentArrivals": [raw()]}
    with pytest.raises(PaymentVerificationError, match="does not match"):
        normalize_mufg_payment_arrivals_response(response=response, account_id=ACCOUNT_ID)


def test_missing_payment_arrivals_fails_closed():
    with pytest.raises(PaymentVerificationError, match="missing paymentArrivals"):
        normalize_mufg_payment_arrivals_response(response={"number": 0}, account_id=ACCOUNT_ID)
