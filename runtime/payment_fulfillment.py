from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from entitlements import PAYMENT_ACTIVE, PAYMENT_EXPIRED, PAYMENT_MISSING, PAYMENT_REVOKED
from payment_adapter import BankTransactionClaimStore, PaymentVerificationError, VerifiedPaymentEvent


class EntitlementAuthority(Protocol):
    def payment_state(self, *, package_id: str, payment_ref: str | None, now: int | None = None) -> str: ...
    def issue(self, *, package_id: str, buyer_ref: str = "", payment_ref: str = "", expires_at: int | None = None) -> str: ...
    def authorize_payment(self, *, package_id: str, payment_ref: str | None, now: int | None = None) -> bool: ...


@dataclass(frozen=True)
class FulfillmentResult:
    package_id: str
    payment_ref: str
    active: bool
    created: bool


def fulfill_verified_payment(
    *,
    event: VerifiedPaymentEvent,
    entitlements: EntitlementAuthority,
    bank_claims: BankTransactionClaimStore | None = None,
) -> FulfillmentResult:
    """Turn verified provider-neutral payment authority into one active entitlement.

    Bank events must first claim their provider transaction identity durably.
    Exact provider replays are idempotent. A revoked/expired payment is terminal:
    replaying the original payment evidence must never resurrect buyer access.

    Invariants:
      VERIFIED PAYMENT != ENTITLEMENT UNTIL FULFILLMENT SUCCEEDS
      ONE BANK TRANSACTION = ONE PAYMENT AUTHORITY
      REVOKED/EXPIRED PAYMENT != REPLAYABLE ACCESS
    """

    entitlement_input = event.as_entitlement_input()

    if event.payment_ref.startswith("bank:"):
        if bank_claims is None:
            raise PaymentVerificationError("bank payment fulfillment requires durable transaction claims")
        bank_claims.claim(event)

    package_id = entitlement_input["package_id"]
    payment_ref = entitlement_input["payment_ref"]
    buyer_ref = entitlement_input["buyer_ref"]
    state = entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)

    created = False
    if state == PAYMENT_MISSING:
        try:
            entitlements.issue(package_id=package_id, buyer_ref=buyer_ref, payment_ref=payment_ref)
            created = True
        except ValueError as exc:
            state = entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)
            if state != PAYMENT_ACTIVE:
                raise PaymentVerificationError("payment fulfillment could not establish active entitlement") from exc
    elif state in {PAYMENT_REVOKED, PAYMENT_EXPIRED}:
        raise PaymentVerificationError("terminal payment lifecycle cannot be replayed into access")
    elif state != PAYMENT_ACTIVE:
        raise PaymentVerificationError("unknown entitlement lifecycle state")

    if not entitlements.authorize_payment(package_id=package_id, payment_ref=payment_ref):
        raise PaymentVerificationError("payment fulfillment did not establish active entitlement")

    return FulfillmentResult(
        package_id=package_id,
        payment_ref=payment_ref,
        active=True,
        created=created,
    )
