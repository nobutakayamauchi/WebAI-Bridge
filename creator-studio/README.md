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
9. One four-level distribution-protection selector
10. Explicit portable copy-risk acknowledgement for Levels 1-3
11. Seat intent for Level 3
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

## Four protection levels

Creator Studio intentionally presents one simple choice instead of exposing multiple technical protection knobs.

```text
LEVEL 1 — LICENSE ONLY
portable package
terms/license only
technical copy protection NOT GUARANTEED

LEVEL 2 — BUYER PASSPHRASE
portable package
planned encryption + buyer passphrase
CONTRACT_ONLY / NOT IMPLEMENTED in thin v0

LEVEL 3 — DUAL CONTROL ACTIVATION
portable package
planned buyer passphrase + seller/WebAI Bridge signed activation
seat intent
CONTRACT_ONLY / NOT IMPLEMENTED in thin v0

LEVEL 4 — HOSTED ONLY
no portable package handoff
strongest current secrecy / entitlement / Safety boundary
```

Level 3 does **not** mean handing a seller password to the buyer. The future seller-side factor is a signed/server-verifiable activation state whose signing secret remains outside the package.

Actual buyer passphrases, seller signing keys, Stripe secrets, and provider secrets must never be written into Package JSON.

Creator Studio refuses Levels 1-3 unless the creator explicitly acknowledges that portable delivery cannot guarantee perfect technical prevention of copying, inspection, modification, or Safety removal.

See `docs/DISTRIBUTION_SECURITY.md`.

## Warnings are part of the contract

- Paid access modes are pricing intent only until commercial enforcement exists.
- Payment Link does not prove entitlement.
- Portable delivery makes package content available to the recipient and cannot honestly guarantee technical anti-copy protection.
- Level 2 encryption/passphrase behavior is contract-only until implemented.
- Level 3 activation/seat/revocation/exit behavior is contract-only until implemented.
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
- encryption/passphrase secret storage in thin v0
- activation server / seller signing infrastructure / revocation in thin v0

## Success test

Create a second schema-valid AI Package through `/studio` without manually rewriting runtime core code, while preserving access-price / checkout / payer / budget / model / four-level distribution-authority boundaries.

See:
- `docs/GOAL_CREATOR_STUDIO_V0.md`
- `docs/BILLING_AND_CHECKOUT.md`
- `docs/DISTRIBUTION_SECURITY.md`
