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
5. Inference payer: BYOK / bounded PLATFORM_CREDIT
6. Platform-credit hard cap
7. Allowed/default model policy from the current pricing registry
8. Delivery: hosted-only / portable / both
9. Validate against semantic/economic gates + canonical package JSON Schema
10. Download package JSON + Instructions file

The validation endpoint is **read/compute only**. Passing validation does not mutate the live runtime registry or write package files on the server.

`access.price_amount_minor` is the AI/package utilization price intent. It is deliberately separate from inference cost/payer policy.

## Why no Publish button yet

Direct runtime mutation would create new requirements for authentication, authorization, rollback, secret handling, audit evidence and concurrent editing. Those responsibilities did not survive the v0 Raison d'être test.

For v0 the operator places/deploys the two exported files deliberately. That manual bounded step is cheaper and safer than inventing an admin control plane before the package factory is proven.

## Warnings are part of the contract

- Paid access modes are pricing intent only until commercial enforcement exists.
- Portable delivery means exported Instructions (and bundled Knowledge, when later supported) are visible to the recipient.
- Knowledge upload/index creation remains operator-assisted.
- Platform-funded Knowledge is rejected unless an explicit positive tool-cost reserve exists.

## Non-goals

- Stripe checkout
- purchased credit wallet
- subscription enforcement
- creator payout
- persistent BYOK key storage
- analytics dashboard
- multi-admin
- server-side package publish/write

## Success test

Create a second schema-valid AI Package through `/studio` without manually rewriting runtime core code, while preserving the existing access-price / payer / budget / model boundaries.

See `docs/GOAL_CREATOR_STUDIO_V0.md` for the frozen Ultimate Loop workload and METEOR cases.
