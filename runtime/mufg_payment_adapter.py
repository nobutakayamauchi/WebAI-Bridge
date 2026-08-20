from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from payment_adapter import PaymentVerificationError


@dataclass(frozen=True)
class MUFGPaymentArrivalFieldMap:
    """Map MUFG payment-arrival response fields into WebAI's canonical deposit.

    The public MUFG product page confirms the payment-arrivals endpoint, but the
    response field schema is only available through the authenticated OpenAPI
    definition. Therefore production callers must provide an explicit field map
    from that definition rather than relying on guessed field names.
    """

    transaction_ref: str
    amount_minor: str
    currency: str
    status: str
    order_ref: str


def _get_required(raw: Mapping[str, Any], key: str, *, label: str) -> Any:
    if not key:
        raise PaymentVerificationError(f"MUFG field mapping for {label} is required")
    if key not in raw:
        raise PaymentVerificationError(f"MUFG response is missing mapped field for {label}")
    value = raw[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise PaymentVerificationError(f"MUFG response field for {label} is empty")
    return value


def normalize_mufg_payment_arrival(
    *,
    raw: Mapping[str, Any],
    field_map: MUFGPaymentArrivalFieldMap,
    settled_values: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Normalize one authenticated MUFG payment-arrival record.

    Authentication/OAuth and HTTP transport live outside this function. This
    adapter only maps one provider record into the bank-ingress contract.

    Fail-closed rules:
    - exact field mapping is mandatory;
    - provider status must be explicitly configured as settled;
    - no package, buyer, or expected price may come from the bank response;
    - amount must parse as a positive integer in minor currency units.
    """

    transaction_ref = str(_get_required(raw, field_map.transaction_ref, label="transaction_ref")).strip()
    order_ref = str(_get_required(raw, field_map.order_ref, label="order_ref")).strip()
    currency = str(_get_required(raw, field_map.currency, label="currency")).strip().upper()
    provider_status = str(_get_required(raw, field_map.status, label="status")).strip().upper()

    accepted = {str(value).strip().upper() for value in settled_values if str(value).strip()}
    if not accepted:
        raise PaymentVerificationError("MUFG settled status mapping is required")
    if provider_status not in accepted:
        raise PaymentVerificationError("MUFG payment arrival is not settled")

    raw_amount = _get_required(raw, field_map.amount_minor, label="amount_minor")
    try:
        amount_minor = int(raw_amount)
    except (TypeError, ValueError) as exc:
        raise PaymentVerificationError("MUFG payment arrival amount is not an integer") from exc
    if amount_minor <= 0:
        raise PaymentVerificationError("MUFG payment arrival amount must be positive")

    return {
        "provider": "MUFG",
        "transaction_ref": transaction_ref,
        "order_ref": order_ref,
        "amount_minor": amount_minor,
        "currency": currency,
        "status": "SETTLED",
    }
