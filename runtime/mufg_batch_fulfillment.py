from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bank_payment_ingress import BankPaymentIngress
from mufg_response_ingress import MUFGBatch
from payment_adapter import PaymentVerificationError


@dataclass(frozen=True)
class MUFGBatchFulfillmentResult:
    fulfilled: tuple[dict[str, Any], ...]
    skipped_unknown_orders: tuple[dict[str, Any], ...]
    rejected_known_orders: tuple[dict[str, Any], ...]
    provider_unmatchable: tuple[dict[str, Any], ...]


def fulfill_mufg_batch(*, batch: MUFGBatch, ingress: BankPaymentIngress) -> MUFGBatchFulfillmentResult:
    """Fulfill only deposits that correspond to server-side orders.

    Unknown provider references are not treated as orders and never grant access.
    Known orders are verified independently; amount/currency/status mismatches are
    rejected and recorded without blocking unrelated valid deposits in the page.
    Provider records lacking a supported order reference remain quarantined from
    the normalization boundary.
    """
    fulfilled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for deposit in batch.deposits:
        order_ref = str(deposit.get("order_ref") or "").strip()
        order = ingress.orders.get(order_ref)
        if order is None:
            skipped.append({
                "order_ref": order_ref,
                "transaction_ref": deposit.get("transaction_ref"),
                "reason": "UNKNOWN_ORDER",
            })
            continue

        try:
            result = ingress.process(deposit)
        except PaymentVerificationError as exc:
            rejected.append({
                "order_ref": order_ref,
                "transaction_ref": deposit.get("transaction_ref"),
                "reason": str(exc),
            })
            continue

        fulfilled.append({
            "order_ref": order_ref,
            "transaction_ref": deposit.get("transaction_ref"),
            "active": result.active,
            "created": result.created,
        })

    return MUFGBatchFulfillmentResult(
        fulfilled=tuple(fulfilled),
        skipped_unknown_orders=tuple(skipped),
        rejected_known_orders=tuple(rejected),
        provider_unmatchable=batch.unmatchable,
    )
