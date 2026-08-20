import pytest

from mufg_payment_adapter import MUFGPaymentArrivalFieldMap, normalize_mufg_payment_arrival
from payment_adapter import PaymentVerificationError


FIELDS = MUFGPaymentArrivalFieldMap(
    transaction_ref="providerTxnId",
    amount_minor="amountYen",
    currency="currencyCode",
    status="arrivalStatus",
    order_ref="customerReference",
)


def raw(**changes):
    value = {
        "providerTxnId": "MUFG-ARRIVAL-0001",
        "amountYen": "300000",
        "currencyCode": "JPY",
        "arrivalStatus": "BOOKED",
        "customerReference": "order-300k",
        "untrustedProductId": "attacker-product",
        "untrustedBuyer": "attacker@example.test",
    }
    value.update(changes)
    return value


def test_mufg_record_normalizes_only_payment_evidence():
    deposit = normalize_mufg_payment_arrival(raw=raw(), field_map=FIELDS, settled_values={"BOOKED"})
    assert deposit == {
        "provider": "MUFG",
        "transaction_ref": "MUFG-ARRIVAL-0001",
        "order_ref": "order-300k",
        "amount_minor": 300000,
        "currency": "JPY",
        "status": "SETTLED",
    }
    assert "package_id" not in deposit
    assert "buyer_ref" not in deposit


def test_mufg_nonsettled_status_fails_closed():
    with pytest.raises(PaymentVerificationError, match="not settled"):
        normalize_mufg_payment_arrival(raw=raw(arrivalStatus="PENDING"), field_map=FIELDS, settled_values={"BOOKED"})


def test_mufg_missing_mapped_field_fails_closed():
    record = raw()
    del record["providerTxnId"]
    with pytest.raises(PaymentVerificationError, match="missing mapped field"):
        normalize_mufg_payment_arrival(raw=record, field_map=FIELDS, settled_values={"BOOKED"})


def test_mufg_requires_explicit_settled_mapping():
    with pytest.raises(PaymentVerificationError, match="settled status mapping"):
        normalize_mufg_payment_arrival(raw=raw(), field_map=FIELDS, settled_values=set())


def test_mufg_rejects_nonpositive_amount():
    with pytest.raises(PaymentVerificationError, match="positive"):
        normalize_mufg_payment_arrival(raw=raw(amountYen="0"), field_map=FIELDS, settled_values={"BOOKED"})
