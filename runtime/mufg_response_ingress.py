from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from mufg_payment_adapter import normalize_mufg_payment_arrival
from payment_adapter import PaymentVerificationError


@dataclass(frozen=True)
class MUFGBatch:
    deposits: tuple[dict[str, Any], ...]
    unmatchable: tuple[dict[str, Any], ...]
    next_flag: str
    next_keyword: str | None
    declared_number: int


def _candidate_sources(preferred: str) -> tuple[str, ...]:
    if preferred == "auto":
        return ("paymentApplicantNo", "ediInfo")
    if preferred == "paymentApplicantNo":
        return ("paymentApplicantNo", "ediInfo")
    if preferred == "ediInfo":
        return ("ediInfo", "paymentApplicantNo")
    raise PaymentVerificationError("MUFG order reference source must be auto, ediInfo, or paymentApplicantNo")


def normalize_mufg_payment_arrivals_response(
    *,
    response: Mapping[str, Any],
    account_id: str,
    order_ref_source: str = "auto",
    currency: str = "JPY",
) -> MUFGBatch:
    """Normalize one MUFG Account API v1.4.2 payment-arrivals response page.

    Page-structure corruption fails closed. Individual incoming deposits that are
    otherwise valid but contain neither supported order-reference field are
    quarantined as unmatchable and can never reach fulfillment.
    """
    arrivals = response.get("paymentArrivals")
    if not isinstance(arrivals, list):
        raise PaymentVerificationError("MUFG response paymentArrivals must be an array")

    try:
        declared_number = int(response.get("number"))
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

    sources = _candidate_sources(order_ref_source)
    deposits: list[dict[str, Any]] = []
    unmatchable: list[dict[str, Any]] = []

    for index, record in enumerate(arrivals):
        if not isinstance(record, Mapping):
            raise PaymentVerificationError("MUFG payment arrival record must be an object")

        normalized = None
        last_reference_error: PaymentVerificationError | None = None
        for source in sources:
            try:
                normalized = normalize_mufg_payment_arrival(
                    raw=record,
                    account_id=account_id,
                    order_ref_source=source,
                    currency=currency,
                )
                break
            except PaymentVerificationError as exc:
                message = str(exc)
                if "missing ediInfo" in message or "missing paymentApplicantNo" in message or "order reference is empty" in message:
                    last_reference_error = exc
                    continue
                raise

        if normalized is None:
            unmatchable.append({
                "index": index,
                "transactionDate": record.get("transactionDate"),
                "transactionId": record.get("transactionId"),
                "amount": record.get("amount"),
                "reason": str(last_reference_error or "missing supported order reference"),
            })
            continue
        deposits.append(normalized)

    return MUFGBatch(
        deposits=tuple(deposits),
        unmatchable=tuple(unmatchable),
        next_flag=next_flag,
        next_keyword=next_keyword,
        declared_number=declared_number,
    )
