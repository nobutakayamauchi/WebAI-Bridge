# Creator Studio — thin v0

Status: `BOUNDED_CHALLENGER / EXPORT_ONLY`

Creator Studio replaces hand-editing AI Package JSON with one smartphone-friendly form while deliberately **not** becoming a full admin SaaS.

## Run

The existing runtime serves the Studio only when explicitly enabled:

```bash
export WEB_AI_STUDIO_ENABLED=1
cd runtime
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `/studio`.

Default is disabled (`WEB_AI_STUDIO_ENABLED=0` / unset).

## What v0 does

1. AI name / slug / description
2. Instructions
3. Knowledge server-binding reference
4. Access intent: free / allowance / paid / buy-once / subscription / per-use + JPY price intent
5. External Stripe Payment Link metadata: self setup / assisted setup
6. Inference payer: BYOK / bounded PLATFORM_CREDIT
7. Platform-credit hard cap
8. Allowed/default model policy from the current pricing registry
9. Delivery: hosted-only / portable / both
10. Portable copy-control intent: license-only / activation-required
11. Explicit portable copy-risk acknowledgement
12. Validate against semantic/economic/distribution gates + canonical package JSON Schema
13. Download package JSON + Instructions file

The validation endpoint is **read/compute only**. Passing validation does not mutate the live runtime registry or write package files on the server.

`access.price_amount_minor` is the AI/package utilization price intent. It is deliberately separate from inference cost/payer policy.

## Why no Publish button yet

Direct runtime mutation would create new requirements for authentication, authorization, rollback, secret handling, audit evidence and concurrent editing. Those responsibilities did not survive the v0 Raison d'être test.

For v0 the operator places/deploys the exported files deliberately. That manual bounded step is cheaper and safer than inventing an admin control plane before the package factory is proven.

## Checkout boundary

Paid access uses creator-owned Stripe Payment Link metadata rather than custom card handling in WebAI Bridge.

- `SELF_SETUP`: creator supplies a valid HTTPS checkout URL.
- `ASSISTED_SETUP`: the package may remain link-pending as a draft while setup support helps create the product/price/link/post-payment flow.

A Payment Link is **not** treated as verified entitlement in thin v0. Paid fulfillment remains manual handoff until a verified entitlement flow exists.

## Portable distribution boundary

Portable delivery is not the same as secure non-copyable delivery.

```text
HOSTED_ONLY
  -> strongest current secrecy / entitlement / Safety boundary

PORTABLE + LICENSE_ONLY
  -> lowest friction
  -> redistribution may be prohibited by terms
  -> technical copy prevention is NOT GUARANTEED

PORTABLE + ACTIVATION_REQUIRED
  -> future account/license/seat entitlement intent
  -> activation runtime NOT IMPLEMENTED in thin v0
```

Creator Studio therefore refuses portable export unless the creator explicitly acknowledges the copy/inspection/modification risk.

If Instructions, Knowledge, or Safety enforcement must remain under strong control, choose `HOSTED_ONLY`.

See `docs/DISTRIBUTION_SECURITY.md`.

## Warnings are part of the contract

- Paid access modes are pricing intent only until commercial enforcement exists.
- Payment Link does not prove entitlement.
- Portable delivery makes package content available to the recipient and cannot honestly guarantee technical anti-copy protection.
- Activation-required portable protection is contract-only until entitlement runtime exists.
- Knowledge upload/index creation remains operator-assisted.
- Platform-funded Knowledge is rejected unless an explicit positive tool-cost reserve exists.

## Non-goals

- custom card/payment handling
- purchased credit wallet
- subscription enforcement
- creator payout
- persistent BYOK key storage
- analytics dashboard
- multi-admin
- server-side package publish/write
- DRM / guaranteed anti-copy protection
- activation server / device fingerprinting / revocation in thin v0

## Success test

Create a second schema-valid AI Package through `/studio` without manually rewriting runtime core code, while preserving access-price / checkout / payer / budget / model / distribution-authority boundaries.

See:
- `docs/GOAL_CREATOR_STUDIO_V0.md`
- `docs/BILLING_AND_CHECKOUT.md`
- `docs/DISTRIBUTION_SECURITY.md`
