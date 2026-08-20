from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


PAID = "PAID"
SETTLED = "SETTLED"


class PaymentVerificationError(ValueError):
    """Raised when a provider event is not strong enough to authorize access."""


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    """Provider-neutral payment authority presented to entitlement fulfillment.

    Adapters may only create this object after the provider-specific evidence has
    been authenticated and matched to one concrete WebAI package/order.

    Invariant: PAYMENT/DEPOSIT OBSERVED != VERIFIED PAYMENT.
    """

    provider: str
    event_ref: str
    payment_ref: str
    package_id: str
    buyer_ref: str
    amount_minor: int
    currency: str
    status: str = PAID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_entitlement_input(self) -> dict[str, str]:
        if self.status != PAID:
            raise PaymentVerificationError("only PAID events may reach entitlement fulfillment")
        return {
            "package_id": self.package_id,
            "payment_ref": self.payment_ref,
            "buyer_ref": self.buyer_ref,
        }


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PaymentVerificationError(f"{field_name} is required")
    return text


def _amount(value: Any) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise PaymentVerificationError("amount_minor must be an integer") from exc
    if amount < 0:
        raise PaymentVerificationError("amount_minor must not be negative")
    return amount


def canonicalize_stripe_payment(*, verified: Mapping[str, Any], event_ref: str = "") -> VerifiedPaymentEvent:
    """Convert an already Stripe-verified checkout result into canonical authority.

    This function deliberately does not verify Stripe signatures or Payment Link
    bindings. The existing Stripe verifier remains authoritative for that step.
    """

    amount = verified.get("amount_total", verified.get("amount_minor", 0))
    currency = str(verified.get("currency") or "JPY").upper()
    return VerifiedPaymentEvent(
        provider="STRIPE",
        event_ref=_required_text(event_ref or verified.get("checkout_session_id") or verified.get("payment_ref"), field_name="event_ref"),
        payment_ref=_required_text(verified.get("payment_ref"), field_name="payment_ref"),
        package_id=_required_text(verified.get("package_id"), field_name="package_id"),
        buyer_ref=str(verified.get("buyer_ref") or ""),
        amount_minor=_amount(amount),
        currency=_required_text(currency, field_name="currency"),
        metadata={"payment_link_id": verified.get("payment_link_id", "")},
    )


def verify_bank_transfer(*, deposit: Mapping[str, Any], order: Mapping[str, Any]) -> VerifiedPaymentEvent:
    """Fail-closed bank transfer matcher for future bank API adapters.

    Provider adapters must authenticate the bank webhook/API response before
    calling this function. This matcher then requires an exact order match.
    Ambiguous, underpaid, overpaid, pending, duplicated-with-different-order, or
    otherwise incomplete deposits must never mint entitlement authority.
    """

    deposit_status = _required_text(deposit.get("status"), field_name="deposit.status").upper()
    if deposit_status != SETTLED:
        raise PaymentVerificationError("bank deposit is not settled")

    order_status = _required_text(order.get("status"), field_name="order.status").upper()
    if order_status not in {"PENDING", "AWAITING_PAYMENT"}:
        raise PaymentVerificationError("order is not awaiting payment")

    deposit_amount = _amount(deposit.get("amount_minor"))
    order_amount = _amount(order.get("amount_minor"))
    if deposit_amount != order_amount:
        raise PaymentVerificationError("bank deposit amount does not exactly match order")

    deposit_currency = _required_text(deposit.get("currency"), field_name="deposit.currency").upper()
    order_currency = _required_text(order.get("currency"), field_name="order.currency").upper()
    if deposit_currency != order_currency:
        raise PaymentVerificationError("bank deposit currency does not match order")

    deposit_order_ref = _required_text(deposit.get("order_ref"), field_name="deposit.order_ref")
    order_ref = _required_text(order.get("order_ref"), field_name="order.order_ref")
    if deposit_order_ref != order_ref:
        raise PaymentVerificationError("bank deposit is not bound to this order")

    provider = _required_text(deposit.get("provider"), field_name="deposit.provider").upper()
    transaction_ref = _required_text(deposit.get("transaction_ref"), field_name="deposit.transaction_ref")
    package_id = _required_text(order.get("package_id"), field_name="order.package_id")

    return VerifiedPaymentEvent(
        provider=provider,
        event_ref=transaction_ref,
        payment_ref=f"bank:{provider.lower()}:{transaction_ref}",
        package_id=package_id,
        buyer_ref=str(order.get("buyer_ref") or ""),
        amount_minor=deposit_amount,
        currency=deposit_currency,
        metadata={"order_ref": order_ref},
    )
