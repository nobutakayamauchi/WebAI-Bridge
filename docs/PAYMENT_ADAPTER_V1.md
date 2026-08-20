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

Bank transfer is planned, not claimed as production-complete in V1.

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

Future providers may include MUFG, GMO Aozora, or other banks exposing suitable corporate/open APIs. Each bank gets an adapter; EntitlementStore does not become bank-specific.

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
8. Bank support may be advertised only as planned until a real bank sandbox/live acceptance chain is proven.
9. Manual bank fallback must require an explicit human verification step; it must not accept buyer-submitted screenshots as payment authority by themselves.
10. Payment provider choice must remain separate from inference payer choice (BYOK/platform credit/etc.).

## Release slices

### Slice A — implemented in this branch

- provider-neutral `VerifiedPaymentEvent`;
- Stripe verified-result canonicalizer;
- fail-closed generic bank transfer matcher;
- unit tests for exact match and rejection cases;
- specification and invariants.

### Slice B — next

- route existing Stripe fulfillment through the canonical event boundary;
- add durable order store and provider-event idempotency for bank transfers;
- add manual-review state machine.

### Slice C — bank acceptance

- implement first concrete bank adapter;
- preferred development candidate: MUFG if the available account/API contract is usable;
- alternative/parallel candidate: GMO Aozora for webhook/virtual-account friendly integration;
- sandbox test;
- real low-value transfer test;
- revoke/duplicate/outage/reconciliation adversarial test.

## Stop boundary

Do not merge or claim bank-transfer production support until a concrete provider has passed authenticated bank evidence -> exact reconciliation -> entitlement -> buyer access -> revoke/deny acceptance on an exact revision.
