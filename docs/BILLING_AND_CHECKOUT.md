# Billing / Checkout Canonical Specification

Status: `SPEC_FROZEN / IMPLEMENTATION_PARTIAL / READINESS_FAIL_CLOSED`
Date: 2026-08-16

## 1. Core separation

```text
ACCESS PRICE != INFERENCE COST
```

- **Access price**: what a buyer pays for the AI Package/right to use it.
- **Inference cost**: what a model/tool provider charges to execute it.

A paid AI may use BYOK. A free AI may consume a creator/platform budget. Subscription never implies unlimited tokens.

## 2. Access modes and charge basis

The access mode and the basis of the price are machine-readable.

```text
FREE                -> FREE
BUY_ONCE            -> ONE_TIME
SUBSCRIPTION        -> MONTHLY
PER_USE             -> PER_RUN
PAID                -> UNSPECIFIED_PAID
ALLOWANCE_THEN_PAID -> UNSPECIFIED_AFTER_ALLOWANCE
```

The two generic paid modes remain useful draft intent, but:

```text
PRICE AMOUNT WITHOUT CHARGE BASIS != COMPLETE COMMERCIAL CONTRACT
```

Therefore `PAID` and `ALLOWANCE_THEN_PAID` are not commercial-ready until their billing basis is made specific.

## 3. Inference payer

Before provider execution:

```text
PAYER RESOLUTION
→ BUDGET AUTHORIZATION
→ MODEL RESOLUTION
→ PROVIDER EXECUTION
```

Target payer modes:
- `BYOK`
- `USER_CREDIT`
- `CREATOR_PAYS`
- `PLATFORM_CREDIT`
- `SPONSORED`
- `HYBRID`

Current hosted runtime implements only BYOK and bounded PLATFORM_CREDIT.

## 4. Hosted BYOK

Current BYOK is `SERVER_PROXY_EPHEMERAL`.

The user key is not intentionally persisted by the runtime, but it travels through the WebAI Bridge server so the hosted runtime can call the provider while keeping creator Instructions/Knowledge server-side.

```text
NOT PERSISTED != NEVER SEEN BY SERVER
```

Package/browser copy must not imply otherwise.

## 5. Platform-funded inference

PLATFORM_CREDIT requires:
- server credential;
- budget identity;
- hard limit;
- pre-call cost reservation;
- positive extra tool-cost reserve for platform-funded Knowledge.

### Accounting truth after reservation

Reservation is an authorization estimate, not accounting truth.

If observed provider cost is greater than the reservation after execution:

```text
OBSERVED ACTUAL COST > RESERVED COST
→ RECORD OBSERVED ACTUAL COST
→ MARK RESERVATION OVERRUN
→ BLOCK LATER SPEND WHEN BUDGET IS EXHAUSTED/OVER LIMIT
```

The system must never cap the ledger entry at the reservation merely to make the hard limit appear respected.

Reservation IDs, idempotent retry settlement and crash lease recovery are still required before production wallet/multi-worker semantics are claimed.

## 6. Creator-funded allocation target

Frozen allocation policies:
- `EQUAL`
- `INDIVIDUAL`
- `INDIVIDUAL_THEN_SHARED`

For individual caps:

```text
USER_CAP = min(total_budget × max_percent, absolute_cap)
```

Unused individually allocated budget may enter the shared pool only when the selected policy explicitly allows it.

Current runtime does not yet have authenticated user identity or per-user allocation enforcement, so these are v1 runtime contracts.

## 7. Payer fallback

Example:

```text
CREATOR_PAYS
→ USER_CREDIT
→ BYOK
```

Every transition must be explicit. Exhausting one payer may not silently charge another payer.

## 8. Stripe Payment Links

Early checkout is externalized to creator-owned Stripe Payment Links.

WebAI Bridge does not handle card data in v0.

Hard distinctions:

```text
PAYMENT LINK != VERIFIED ENTITLEMENT
CHECKOUT URL != VERIFIED PRODUCT/PRICE BINDING
```

### SELF_SETUP

Creator supplies an HTTPS checkout URL and explicitly attests that the Stripe checkout matches:
- product/access mode;
- access amount;
- currency;
- billing basis/cadence.

This records `CREATOR_ATTESTED`; it is not automated Stripe verification.

### ASSISTED_SETUP

Setup support may help with:
- product name/description;
- amount/cadence;
- Payment Link;
- post-payment flow;
- handoff checklist.

A missing link is `ASSISTED_PENDING` and blocks commercial readiness.

### Future verified checkout

Target:

```text
Stripe event/webhook
→ verify payment state and package binding
→ issue/update entitlement
→ authorize protected access
```

Until this exists, opening/redirecting from checkout is not proof of purchase.

## 9. Paid hosted runtime

DA found a critical gap: a shareable AI URL plus a Payment Link does not enforce the access price.

Current response is fail-closed:

```text
PAID HOSTED + NO VERIFIED ENTITLEMENT
→ NO CHAT EXECUTION
```

So the current runtime deliberately blocks all paid hosted packages. The package may still be configuration-valid/exportable as a draft.

## 10. Commercial readiness

Creator Studio distinguishes:

```text
CONFIG_VALID != READY_TO_RUN != READY_TO_SELL
```

Potential commercial blockers include:
- hosted entitlement missing;
- portable runtime missing;
- portable protection implementation missing;
- checkout setup pending;
- generic/unspecified charge basis;
- portable Knowledge binding missing;
- portable server-funded payer path missing.

A Package JSON download is not a sale authorization.

## 11. Buy-once

Target buy-once model remains:

```text
BUY_ONCE
→ buyer purchases AI Package rights
→ buyer may use BYOK when the selected distribution/runtime supports it
→ inference provider cost belongs to the buyer unless another payer policy is explicit
```

But delivery is separate from purchase:
- Level 4 paid hosted is currently blocked on entitlement;
- Levels 1-3 are currently blocked on missing portable runtime.

`BUY_ONCE` therefore freezes the commercial contract without falsely claiming delivery is complete.

## 12. Creator credentials

Creator provider credentials must never be Package JSON/browser-delivered data.

Future persistent path:

```text
creator authentication
→ managed/encrypted secret store
→ credential_ref
→ server-authorized provider execution
```

No creator secret persistence is implemented in thin v0.

## 13. Hard invariants

```text
ACCESS PRICE != INFERENCE COST
PAID ACCESS != PLATFORM PAYS INFERENCE
FREE ACCESS != FREE INFERENCE
BYOK != FREE PACKAGE
SUBSCRIPTION != UNLIMITED TOKENS
PAYMENT LINK != VERIFIED ENTITLEMENT
CHECKOUT URL != VERIFIED PRICE BINDING
CREATOR API KEY != PACKAGE DATA
PAYER FALLBACK != SILENT CHARGE
UNKNOWN COST != ZERO COST
CONFIG_VALID != READY_TO_SELL
```

## 14. Implementation order

### thin v0
- access price + charge-basis contract
- BYOK disclosure/transport contract
- bounded PLATFORM_CREDIT
- truthful cost ledger
- external Stripe Link metadata
- SELF_SETUP attestation / ASSISTED_SETUP state
- readiness/blocker model
- paid hosted fail-closed

### v1
- verified Stripe entitlement
- USER_CREDIT wallet
- authenticated user identity
- per-user/package caps
- creator allocation pools
- model/cost routing
- reservation identity/idempotent settlement/crash recovery

### later
- managed creator credential refs
- CREATOR_PAYS / SPONSORED / HYBRID
- subscription lifecycle enforcement
- creator payout / revenue split
- Stripe Connect only if marketplace economics require it
