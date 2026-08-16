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
5. Paid checkout intent: Stripe Payment Link self-setup or assisted setup
6. Inference payer: BYOK / bounded PLATFORM_CREDIT
7. Platform-credit hard cap
8. Allowed/default model policy from the current pricing registry
9. Delivery: hosted-only / portable / both
10. Validate against semantic/economic gates + canonical package JSON Schema
11. Download package JSON + Instructions file

The validation endpoint is **read/compute only**. Passing validation does not mutate the live runtime registry or write package files on the server.

`access.price_amount_minor` is the AI/package utilization price intent. It is deliberately separate from inference cost/payer policy.

## Stripe Payment Link boundary

Paid packages use `STRIPE_PAYMENT_LINK` as the default early-stage external checkout rail.

Two creator setup paths are represented:

- `SELF_SETUP`: creator supplies a valid HTTPS Payment Link / Stripe custom checkout URL.
- `ASSISTED_SETUP`: creator requests setup help; a draft can be exported with the link still pending.

The package records checkout metadata only. Creator Studio does not handle card data, create Stripe objects, receive Stripe secret keys, or verify entitlement in thin v0.

A Payment Link is **not** treated as proof that a user owns access. V0 paid fulfillment remains `MANUAL_HANDOFF`; verified webhook entitlement is a later gate.

See `docs/BILLING_AND_CHECKOUT.md`.

## Why no Publish button yet

Direct runtime mutation would create new requirements for authentication, authorization, rollback, secret handling, audit evidence and concurrent editing. Those responsibilities did not survive the v0 Raison d'être test.

For v0 the operator places/deploys the two exported files deliberately. That manual bounded step is cheaper and safer than inventing an admin control plane before the package factory is proven.

## Warnings are part of the contract

- Paid access modes are pricing intent only until commercial enforcement exists.
- Payment Link does not prove entitlement; paid fulfillment is manual in thin v0.
- Portable delivery means exported Instructions (and bundled Knowledge, when later supported) are visible to the recipient.
- Knowledge upload/index creation remains operator-assisted.
- Platform-funded Knowledge is rejected unless an explicit positive tool-cost reserve exists.

## Non-goals

- custom card collection / payment processor implementation
- automated Stripe Payment Link API creation
- Stripe webhook entitlement enforcement
- purchased credit wallet
- subscription enforcement
- creator payout
- persistent BYOK key storage
- analytics dashboard
- multi-admin
- server-side package publish/write

## Success test

Create a second schema-valid AI Package through `/studio` without manually rewriting runtime core code, while preserving the existing access-price / checkout / payer / budget / model boundaries.

See `docs/GOAL_CREATOR_STUDIO_V0.md` for the frozen Ultimate Loop workload and METEOR cases.
