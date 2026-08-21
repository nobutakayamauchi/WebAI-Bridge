# Payment Adapter V1

## /goal

Keep the proven Stripe commercial path working while creating one provider-neutral payment boundary so bank transfer adapters can be added without giving bank APIs direct entitlement authority.

## Core rule

```text
PAYMENT/DEPOSIT OBSERVED != VERIFIED PAYMENT
VERIFIED PAYMENT != ENTITLEMENT UNTIL PACKAGE + PAYMENT IDENTITY ARE BOUND
```

A provider-specific integration may authenticate and parse payment evidence. It must then convert that evidence into one `VerifiedPaymentEvent`. Only that canonical event is eligible to enter entitlement fulfillment.

## Canonical event

```text
provider
+ event_ref
+ payment_ref
+ package_id
+ buyer_ref
+ exact amount_minor
+ exact currency
+ PAID status
```

`payment_ref` must be stable and unique enough to preserve the existing idempotent `package_id + payment_ref` entitlement authority.

## Stripe

Stripe remains the current standard provider and the currently proven live commercial chain.

Existing Stripe signature verification, Checkout Session verification, Payment Link binding, browser possession proof, handoff tickets, entitlement cookies, revocation, and BYOK behavior remain authoritative. The adapter boundary must not weaken them.

Stripe adapter flow:

```text
Stripe webhook / Checkout completion
-> existing Stripe authentication + binding validation
-> canonicalize_stripe_payment(...)
-> VerifiedPaymentEvent
-> entitlement fulfillment
```

## Bank transfer

Bank transfer support is implemented behind the provider-neutral boundary and has passed a MUFG trial/sandbox acceptance chain. It is still dogfood, not claimed as production-complete.

Initial bank model:

```text
order created
-> order_ref bound to one package + expected amount + currency
-> bank API / webhook reports deposit
-> provider adapter authenticates bank response
-> strict match of status + order_ref + amount + currency
-> VerifiedPaymentEvent
-> entitlement fulfillment
```

MUFG is the first concrete adapter. Other providers may be added behind the same boundary; EntitlementStore does not become bank-specific.

### Fail closed

The following must not create entitlement:

- pending/unsettled deposit;
- unknown or ambiguous order reference;
- underpayment;
- overpayment;
- wrong currency;
- order already closed/non-payable;
- missing provider transaction identity;
- unauthenticated bank webhook/API response;
- duplicate/replayed provider event that cannot be proven idempotent;
- bank API outage or partial response.

Ambiguous payments go to manual review. They are never auto-granted.

## Invariants from DA / counter-DA

1. Bank deposit notification is not buyer authority.
2. Bank API response is not trusted until provider authentication succeeds.
3. Exact amount match is required for automatic fulfillment in V1.
4. One deposit cannot silently unlock a different package.
5. `package_id + payment_ref` remains the entitlement lifecycle identity.
6. Replay must not resurrect REVOKED or EXPIRED access.
7. Stripe regression is a release blocker.
8. Bank support may be merged as dogfood only after authenticated provider evidence, exact reconciliation, entitlement issuance, buyer-claim binding, replay protection, and deny/revoke tests pass on the exact revision.
9. Production bank-transfer claims additionally require a real low-value transfer acceptance run against the intended production contract/configuration.
10. Manual bank fallback must require an explicit human verification step; it must not accept buyer-submitted screenshots as payment authority by themselves.
11. Payment provider choice must remain separate from inference payer choice (BYOK/platform credit/etc.).

## Release slices

### Slice A — implemented

- provider-neutral `VerifiedPaymentEvent`;
- Stripe verified-result canonicalizer;
- fail-closed generic bank transfer matcher;
- durable bank order and transaction-claim stores;
- browser claim binding so order_ref alone is not a bearer credential;
- idempotent entitlement fulfillment and replay/revocation protections;
- unit and integration tests for exact match, rejection, handoff, replay, and revoke behavior;
- specification and invariants.

### Slice B — MUFG trial acceptance — completed for dogfood

- concrete MUFG payment-arrivals adapter and pagination;
- provider-accepted `X-BTMU-Seq-No` shape;
- authenticated MUFG trial API response;
- exact known-order reconciliation and entitlement issuance;
- amount mismatch and currency mismatch fail-closed checks;
- repeated poll does not duplicate entitlement;
- full runtime regression suite passes on the accepted revision.

### Slice C — production bank acceptance — still required

- configure the intended real bank account/API contract;
- perform a real low-value transfer test;
- repeat buyer access, duplicate/replay, revoke/deny, outage, and reconciliation checks against production-shaped configuration;
- only then mark production readiness or advertise production bank-transfer support.

## Stop boundary

This branch may merge as dogfood after the MUFG trial acceptance and full regression gate pass. Do not mark bank transfer production-ready, enable it as an advertised production capability, or claim live commercial acceptance until Slice C has passed on an exact revision.
