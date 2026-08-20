from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from payment_adapter import PaymentVerificationError


def _required(raw: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in raw:
        raise PaymentVerificationError(f"MUFG payment arrival is missing {label}")
    value = raw[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PaymentVerificationError(f"MUFG payment arrival {label} is empty")
    return value


def _order_ref_from_record(raw: Mapping[str, Any], *, source: str) -> str:
    if source == "auto":
        for candidate in ("ediInfo", "paymentApplicantNo"):
            value = raw.get(candidate)
            if value is not None and str(value).strip():
                return str(value).strip()
        raise PaymentVerificationError("MUFG payment arrival has no usable order reference")
    if source not in {"ediInfo", "paymentApplicantNo"}:
        raise PaymentVerificationError("MUFG order reference source must be auto, ediInfo or paymentApplicantNo")
    value = str(_required(raw, source, source)).strip()
    if not value:
        raise PaymentVerificationError("MUFG order reference is empty")
    return value


def normalize_mufg_payment_arrival(
    *,
    raw: Mapping[str, Any],
    account_id: str,
    order_ref_source: str = "auto",
    currency: str = "JPY",
) -> dict[str, Any]:
    """Normalize one MUFG Account API v1.4.2 PaymentArrival object.

    Source schema: GET /{account_id}/transactions/paymentarrivals.

    MUFG's PaymentArrival schema does not contain generic status, currency, or a
    WebAI order id. Therefore:
    - the payment-arrivals endpoint itself is treated as arrival evidence;
    - debitCreditTypeCode must be '1' (incoming), otherwise fail closed;
    - currency comes from trusted account configuration, never from the record;
    - order_ref comes from explicit EDI information when present, otherwise the
      payment applicant number; neither field may grant product/price authority;
    - provider transaction identity hashes account_id + date + transactionId so
      short transactionId values cannot collide across accounts/dates.
    """

    account_id = str(account_id or "").strip()
    if len(account_id) != 11:
        raise PaymentVerificationError("MUFG account_id must be exactly 11 characters")

    transaction_date = str(_required(raw, "transactionDate", "transactionDate")).strip()
    transaction_id = str(_required(raw, "transactionId", "transactionId")).strip()
    direction = str(_required(raw, "debitCreditTypeCode", "debitCreditTypeCode")).strip()
    if direction != "1":
        raise PaymentVerificationError("MUFG payment arrival is not an incoming deposit")

    try:
        amount_minor = int(_required(raw, "amount", "amount"))
    except (TypeError, ValueError) as exc:
        raise PaymentVerificationError("MUFG payment arrival amount is not an integer") from exc
    if amount_minor <= 0:
        raise PaymentVerificationError("MUFG payment arrival amount must be positive")

    trusted_currency = str(currency or "").strip().upper()
    if not trusted_currency:
        raise PaymentVerificationError("trusted MUFG account currency is required")

    order_ref = _order_ref_from_record(raw, source=order_ref_source)
    identity_material = f"{account_id}|{transaction_date}|{transaction_id}".encode("utf-8")
    transaction_ref = hashlib.sha256(identity_material).hexdigest()

    return {
        "provider": "MUFG",
        "transaction_ref": transaction_ref,
        "order_ref": order_ref,
        "amount_minor": amount_minor,
        "currency": trusted_currency,
        "status": "SETTLED",
    }


def normalize_mufg_payment_arrivals_response(
    *,
    response: Mapping[str, Any],
    account_id: str,
    order_ref_source: str = "auto",
    currency: str = "JPY",
) -> list[dict[str, Any]]:
    """Normalize a complete MUFG payment-arrivals response.

    The response-level `number` field is treated as integrity metadata only. We
    require it to agree with the actual `paymentArrivals` array length when it is
    present so malformed/truncated provider payloads fail closed before any
    entitlement processing.
    """

    arrivals = response.get("paymentArrivals")
    if arrivals is None:
        raise PaymentVerificationError("MUFG response is missing paymentArrivals")
    if not isinstance(arrivals, Sequence) or isinstance(arrivals, (str, bytes, bytearray)):
        raise PaymentVerificationError("MUFG paymentArrivals must be an array")

    declared_number = response.get("number")
    if declared_number is not None:
        try:
            expected = int(declared_number)
        except (TypeError, ValueError) as exc:
            raise PaymentVerificationError("MUFG response number is not an integer") from exc
        if expected != len(arrivals):
            raise PaymentVerificationError("MUFG response number does not match paymentArrivals length")

    return [
        normalize_mufg_payment_arrival(
            raw=arrival,
            account_id=account_id,
            order_ref_source=order_ref_source,
            currency=currency,
        )
        for arrival in arrivals
    ]
