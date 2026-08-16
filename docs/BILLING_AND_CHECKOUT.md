# Billing / Checkout Canonical Specification

Status: `SPEC_FROZEN / IMPLEMENTATION_PARTIAL`
Date: 2026-08-16

This document freezes the commercial and inference-cost model for WebAI Bridge.

## 1. Core separation

The product has two independent money flows:

```text
ACCESS PRICE != INFERENCE COST
```

- **Access price**: what the buyer pays for the AI Package / right to use it.
- **Inference cost**: what a provider charges to execute the model.

A paid AI may use BYOK. A free AI may still consume creator/platform inference budget. A subscription does not imply unlimited inference.

## 2. Access modes

Supported product intent:

- `FREE`
- `ALLOWANCE_THEN_PAID`
- `BUY_ONCE`
- `SUBSCRIPTION`
- `PER_USE`
- `PAID` (generic paid intent while a more specific mode is not selected)

Every non-free access mode records a positive access price. Currency and access price are package metadata independent from inference billing.

## 3. Buy-once product

The preferred buy-once shape is:

```text
BUY_ONCE
→ buyer obtains package usage rights
→ buyer selects a supported provider/model
→ buyer supplies their own API key (BYOK)
→ provider inference cost belongs to the buyer
```

This lets a creator sell the AI design, Instructions, Knowledge, UI, updates or usage rights without inheriting unbounded inference cost.

Provider/model freedom is a package policy:

- `FIXED`
- `RECOMMENDED_BUT_CHANGEABLE`
- `SUPPORTED_MODELS_FREE_CHOICE`

Only actually supported provider adapters may be advertised.

## 4. Inference payer modes

The payer must be resolved before provider execution.

```text
NO PAYER RESOLUTION
→ NO BUDGET AUTHORIZATION
→ NO MODEL EXECUTION
```

Target payer modes:

- `BYOK` — end user supplies their provider credential.
- `USER_CREDIT` — user spends WebAI credit.
- `CREATOR_PAYS` — creator-owned bounded budget/credential pays.
- `PLATFORM_CREDIT` — operator-funded bounded budget.
- `SPONSORED` — explicit sponsor budget.
- `HYBRID` — ordered fallback across authorized payer modes.

V0 executable runtime currently supports BYOK and bounded PLATFORM_CREDIT. Other modes are frozen contract targets, not current runtime claims.

## 5. Creator API credentials

Creator credentials must never be embedded in an AI Package or browser-delivered config.

Future persistent credential path:

```text
creator authentication
→ encrypted/managed secret store
→ credential_ref in policy
→ server-side provider execution
```

Until that exists, no feature may pretend that creator API-key persistence is safe or supported.

## 6. Creator-funded budget allocation

A creator may define a total inference budget and how it is distributed across users.

Allocation policies:

### `EQUAL`
All eligible users draw from an equal allocation.

### `INDIVIDUAL`
Named/identified users receive explicit individual allocations.

### `INDIVIDUAL_THEN_SHARED`
Each selected user receives an individual guaranteed allocation first. The unallocated remainder becomes a shared pool.

Example:

```text
TOTAL CREATOR BUDGET: 10,000 JPY
A guaranteed:           2,000 JPY
B guaranteed:           1,000 JPY
C guaranteed:             500 JPY
SHARED REMAINDER:       6,500 JPY
```

A user may also be bounded by both:

- maximum percentage of total budget; and
- absolute maximum amount.

Effective user cap uses the stricter bound:

```text
USER_CAP = min(total_budget × max_percent, absolute_cap)
```

This prevents one user from consuming the creator's whole budget while allowing unused budget to remain useful.

## 7. Payer fallback

Hybrid packages may define an ordered payer fallback, for example:

```text
1. CREATOR_PAYS
2. USER_CREDIT
3. BYOK
```

Each transition must be explicit to the user. Exhausting one payer budget must never silently charge another payer.

## 8. Paid hosted inference and margin

When WebAI/creator credentials fund inference for a paying user, execution must reserve enough budget before the provider call.

Target flow:

```text
estimate bounded maximum provider cost
→ reserve payer budget
→ reserve/authorize user charge
→ execute provider
→ observe actual usage
→ settle actual provider cost
→ apply configured commercial markup/fee
→ release unused reservation
```

V0 terminology uses **markup** rather than claiming a specific accounting gross-margin definition.

Commercial charge must be sufficient to recover the authorized provider cost plus the configured commercial amount. Missing/unknown provider/tool pricing fails closed for platform-funded execution.

## 9. Checkout rail — Stripe Payment Links

Default early-stage checkout rail:

`STRIPE_PAYMENT_LINK`

Reason:

- hosted checkout;
- no custom card handling in WebAI Bridge;
- usable for one-time products and subscriptions;
- shareable as a URL;
- creator can own their Stripe account directly.

WebAI Bridge does not need to become a payment processor to prove the product.

### V0 checkout authority

V0 uses a creator-owned Stripe Payment Link supplied manually.

No Stripe secret key is required inside an AI Package.

A Payment Link URL alone is **not proof of entitlement**.

Until webhook/entitlement verification exists, paid fulfillment is classified as:

`MANUAL_HANDOFF / EXTERNAL_CHECKOUT`

Do not expose a supposedly protected permanent AI URL merely by redirecting every successful buyer to the same shareable URL and call that secure entitlement.

### V1 checkout authority

Add verified payment fulfillment using Stripe events/webhooks and explicit entitlement state.

Target:

```text
Payment Link
→ verified Stripe payment event
→ entitlement creation/update
→ protected package access
```

Delayed payment methods must not be treated as paid merely because checkout was opened or redirected.

### Later automation

Only after real demand justifies it:

- Payment Links API creation from Creator Studio;
- Stripe Connect / connected-account flows where platform revenue sharing is required;
- automated subscriptions, refunds/entitlements and creator payouts.

These are not v0 requirements.

## 10. Creator setup service

Commercial onboarding has two service paths.

### `SELF_SETUP`
For creators who can configure Stripe themselves (including using their own AI assistance).

They provide their working Payment Link and use the lower-cost setup path.

### `ASSISTED_SETUP`
For creators who do not want to learn Stripe configuration.

WebAI Bridge support can help them configure:

- product name/description;
- one-time vs subscription price;
- Payment Link creation;
- post-payment confirmation/redirect design;
- handoff checklist.

The Stripe account remains the creator's account. The creator retains ownership/control of their payment account and credentials.

Assisted setup is a paid support/service tier; exact service price remains a commercial decision rather than a protocol invariant.

## 11. Safety boundary for portable / buy-once AI

Hosted execution can enforce a platform Safety Kernel. Portable/modifiable packages cannot honestly guarantee that a recipient will never remove client-side/local safeguards.

Therefore:

```text
CREATOR POLICY < PLATFORM SAFETY POLICY   (hosted runtime)
```

For portable packages:

- ship the supported Safety Kernel in the official package;
- prohibit malicious/abusive use in applicable terms/license;
- do not claim technical enforcement after a fully modifiable package leaves the hosted runtime.

## 12. Hard invariants

```text
ACCESS PRICE != INFERENCE COST
PAID ACCESS != PLATFORM PAYS INFERENCE
FREE ACCESS != FREE INFERENCE
BYOK != FREE PACKAGE
SUBSCRIPTION != UNLIMITED TOKENS
PAYMENT LINK != VERIFIED ENTITLEMENT
CREATOR API KEY != PACKAGE DATA
PAYER FALLBACK != SILENT CHARGE
UNKNOWN COST != ZERO COST
```

## 13. Implementation order

### v0
- access price intent
- BYOK
- bounded PLATFORM_CREDIT
- package export
- creator-supplied Stripe Payment Link as external checkout metadata/workflow
- SELF_SETUP / ASSISTED_SETUP commercial onboarding
- manual paid fulfillment; no false entitlement claim

### v1
- USER_CREDIT wallet
- usage meter
- per-user and package caps
- creator budget pools + allocation policies
- verified Stripe webhook entitlement
- automatic model/cost routing

### v2
- persistent creator credential refs with proper secret management
- CREATOR_PAYS / SPONSORED / HYBRID
- subscriptions with automated entitlement lifecycle
- revenue split / creator payout where justified
- Stripe Connect or equivalent only if the marketplace model requires it
