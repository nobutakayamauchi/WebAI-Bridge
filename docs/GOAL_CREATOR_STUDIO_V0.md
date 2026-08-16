# /goal — Creator Studio thin v0

Date: 2026-08-16
Method: Ultimate Loop / Development Sequence Loop
Status: `FROZEN_SUBJECT / BOUNDED_CHALLENGER`

## Protected outcome

A creator/operator can define a second WebAI Bridge AI Package from a smartphone without hand-writing package JSON, while preserving the existing access-price / checkout / payer / budget / model safety boundaries and without introducing a new admin SaaS or unauthenticated runtime-write surface.

## Frozen workload

The challenger must handle the same bounded package contract for:

1. BYOK-only free hosted AI.
2. Paid-access AI whose access price is separate from BYOK inference cost.
3. Paid-access AI using a creator-supplied Stripe Payment Link.
4. Paid-access AI requesting assisted Stripe Payment Link setup without falsely claiming it is ready to sell.
5. BYOK + bounded PLATFORM_CREDIT AI.
6. Knowledge binding with explicit platform-funded tool-cost reserve.
7. Free / allowance-then-paid / paid-intent access policy with an explicit JPY price intent.
8. Hosted-only / portable / both delivery intent.
9. Allowed/default model policy bound to the current pricing registry.
10. Smartphone-sized form input.
11. Canonical package-schema validation.
12. Export of package JSON + Instructions file.
13. No runtime config mutation merely because validation succeeded.

## Current discovery sweep

### Candidate A — keep hand-editing JSON

Pros: zero new code.

Fails: preserves operator friction and makes Creator Studio outcome impossible.

Result: `REJECT`.

### Candidate B — browser-only JSON generator

Pros: smallest UI, no server write surface.

Fails materially: validation logic can drift from canonical `package-schema/package.schema.json` and current pricing registry.

Result: `REJECT AS SOLE AUTHORITY`.

### Candidate C — thin browser UI + existing runtime validation

Composition:

```text
creator-studio/index.html
→ existing FastAPI runtime
→ StudioDraft semantic gate
→ canonical package JSON Schema
→ current pricing registry
→ export only
```

No persistence. No provider call. No payment call. No separate service.

Result: `PROMOTED BOUNDED CHALLENGER`.

### Candidate D — full admin/dashboard/persistence service

Pros: direct publish/edit later.

Fails current Raison d'être: requires auth, secret storage, mutation authority, rollback and commercial-state design before the protected outcome needs them.

Result: `REJECT / DEFER`.

### Candidate E — build our own checkout/card handling now

Fails current Raison d'être: Stripe Payment Links already provide the external hosted checkout responsibility. Owning card/payment handling would add security/compliance burden without improving the frozen v0 outcome.

Result: `REJECT`.

## Raison d'être Destroy result

```text
DROP            -> no; hand-editing remains painful
EXTERNALIZE     -> checkout yes: Stripe Payment Links
COMPOSE         -> yes; existing runtime + schema + pricing registry + external checkout metadata
MANUAL_BOUNDED  -> yes; operator still deploys exported files and paid fulfillment is manual
GLUE            -> yes; thin UI + validation endpoint
IRREDUCIBLE_BUILD -> only package-builder semantics, checkout metadata validation and mobile form
```

The Creator Studio does **not** become a separate service in v0.

## Authority boundaries

Hard rules:

- Studio is opt-in via `WEB_AI_STUDIO_ENABLED`; disabled by default.
- Validation does not write runtime package files.
- Validation does not call an AI provider.
- Validation does not accept/store provider API keys.
- Validation does not accept/store Stripe secret keys or card data.
- `ACCESS PRICE != INFERENCE COST` remains explicit in the package contract.
- FREE access must have a zero access price.
- Any paid-access intent must have a positive access price.
- Paid access is intent only until commercial enforcement exists.
- `SELF_SETUP` paid checkout requires a valid HTTPS checkout URL.
- `ASSISTED_SETUP` may remain link-pending as a draft but must warn that sale setup is incomplete.
- A Payment Link is not treated as verified entitlement.
- V0 paid fulfillment remains `MANUAL_HANDOFF`.
- PLATFORM_CREDIT requires explicit budget identity + positive hard cap.
- Platform-funded Knowledge requires explicit positive tool-cost reserve.
- Default model must be allowed and every allowed model must exist in current pricing evidence.
- Portable delivery emits an explicit exposure warning.

## METEOR cases

Attack at minimum:

1. Studio exposed while disabled.
2. Empty/invalid payer set.
3. Default payer not allowed.
4. PLATFORM_CREDIT without budget env.
5. PLATFORM_CREDIT without positive cap.
6. Platform-funded Knowledge with zero/unknown tool reserve.
7. Unknown model not present in pricing registry.
8. Default model not in allowed set.
9. Allowance mode with zero free runs.
10. FREE access carrying a non-zero access price.
11. Paid access with zero price.
12. Paid access + BYOK being incorrectly coupled or blocked.
13. SELF_SETUP with missing/non-HTTPS checkout URL.
14. ASSISTED_SETUP with link pending but no explicit warning.
15. Payment Link being falsely treated as verified entitlement.
16. Paid mode falsely claiming enforcement.
17. Portable package hiding the fact that Instructions become visible.
18. Successful validation mutating live runtime registry.
19. Oversized Instructions/body.
20. Checked-in example/fixture drifting from canonical schema.
21. Regression of existing BYOK/platform-credit chat tests.

## Commerce finding that reopened the merge gate

After the first merge-ready state, the product billing discussion identified that paid packages need a low-friction external checkout rail and two creator onboarding paths:

```text
SELF_SETUP     -> creator configures Stripe Payment Link themselves -> lower-cost service path
ASSISTED_SETUP -> setup support helps with product/price/link/post-payment flow -> support-priced service path
```

This is now frozen in `docs/BILLING_AND_CHECKOUT.md` and represented in package checkout metadata without adding payment execution authority to Creator Studio.

## Completion gate for this /goal

Stop at merge-ready when all are true:

- thin UI exists and is smartphone-oriented;
- Studio is disabled by default;
- generated package passes canonical schema + semantic/economic gates;
- access price is explicit and independent from inference payer;
- paid checkout metadata distinguishes SELF_SETUP from ASSISTED_SETUP;
- Payment Link is not conflated with verified entitlement;
- two export files are produced without server persistence;
- tests cover the METEOR economic/authority/checkout cases;
- existing runtime regression remains green;
- CI is green;
- PR is mergeable;
- no claim of deployment/mobile/provider/payment validation is made without runtime evidence.

If any material blocker appears before that point, stop and report the blocker instead of weakening the boundary.
