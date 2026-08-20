from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from mufg_payment_adapter import normalize_mufg_payment_arrival
from payment_adapter import PaymentVerificationError


@dataclass(frozen=True)
class MUFGBatch:
    deposits: tuple[dict[str, Any], ...]
    next_flag: str
    next_keyword: str | None
    declared_number: int


def normalize_mufg_payment_arrivals_response(
    *,
    response: Mapping[str, Any],
    account_id: str,
    order_ref_source: str = "paymentApplicantNo",
    currency: str = "JPY",
) -> MUFGBatch:
    """Normalize one MUFG Account API v1.4.2 payment-arrivals response page.

    This boundary is intentionally non-fulfilling: it never grants entitlement.
    It only validates the provider page shape and converts each PaymentArrival
    into the generic bank deposit contract. Matching to a server-side order and
    fulfillment happens later.

    Fail-closed invariants:
    - response.number must equal the actual paymentArrivals array length;
    - nextFlag must be 0 or 1;
    - nextFlag=1 requires a non-empty nextKeyword;
    - every record must normalize successfully; partial acceptance is forbidden.
    """
    arrivals = response.get("paymentArrivals")
    if not isinstance(arrivals, list):
        raise PaymentVerificationError("MUFG response paymentArrivals must be an array")

    raw_number = response.get("number")
    try:
        declared_number = int(raw_number)
    except (TypeError, ValueError) as exc:
        raise PaymentVerificationError("MUFG response number must be an integer") from exc
    if declared_number != len(arrivals):
        raise PaymentVerificationError("MUFG response number does not match paymentArrivals length")

    next_flag = str(response.get("nextFlag") or "").strip()
    if next_flag not in {"0", "1"}:
        raise PaymentVerificationError("MUFG response nextFlag must be 0 or 1")
    next_keyword_raw = response.get("nextKeyword")
    next_keyword = str(next_keyword_raw).strip() if next_keyword_raw is not None else None
    if next_flag == "1" and not next_keyword:
        raise PaymentVerificationError("MUFG response nextFlag=1 requires nextKeyword")

    deposits = tuple(
        normalize_mufg_payment_arrival(
            raw=record,
            account_id=account_id,
            order_ref_source=order_ref_source,
            currency=currency,
        )
        for record in arrivals
    )
    return MUFGBatch(
        deposits=deposits,
        next_flag=next_flag,
        next_keyword=next_keyword,
        declared_number=declared_number,
    )
