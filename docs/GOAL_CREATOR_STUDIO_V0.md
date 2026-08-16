# /goal — Creator Studio thin v0

Date: 2026-08-16
Method: Ultimate Loop / Development Sequence Loop
Status: `FROZEN_SUBJECT / BOUNDED_CHALLENGER`

## Protected outcome

A creator/operator can define a second WebAI Bridge AI Package from a smartphone without hand-writing package JSON, while preserving access-price / checkout / payer / budget / model / distribution-authority safety boundaries and without introducing a new admin SaaS or unauthenticated runtime-write surface.

## Frozen workload

The challenger must handle the same bounded package contract for:

1. BYOK-only free hosted AI.
2. Paid-access AI whose access price is separate from BYOK inference cost.
3. Paid-access AI using a creator-supplied Stripe Payment Link.
4. Paid-access AI requesting assisted Stripe Payment Link setup without falsely claiming it is ready to sell.
5. BYOK + bounded PLATFORM_CREDIT AI.
6. Knowledge binding with explicit platform-funded tool-cost reserve.
7. Free / allowance-then-paid / paid-intent access policy with an explicit JPY price intent.
8. One creator-facing four-level distribution-protection selector.
9. Level 1: portable license-only with no technical copy guarantee.
10. Level 2: planned encrypted portable package + buyer passphrase, clearly contract-only in thin v0.
11. Level 3: planned buyer passphrase + seller/WebAI Bridge signed activation + seat intent, clearly contract-only in thin v0.
12. Level 4: hosted-only strongest current secrecy/entitlement/Safety boundary.
13. Allowed/default model policy bound to the current pricing registry.
14. Smartphone-sized form input.
15. Canonical package-schema validation.
16. Export of package JSON + Instructions file.
17. No runtime config mutation merely because validation succeeded.

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

### Candidate F — promise DRM-style copy prevention for exported ZIPs

Fails reality gate: once package contents and a modifiable runtime are delivered into a buyer-controlled environment, WebAI Bridge cannot honestly guarantee that copying, inspection, modification, or Safety Kernel removal is impossible.

Result: `REJECT CLAIM / MODEL PROTECTION LEVELS HONESTLY`.

### Candidate G — expose many low-level copy-control knobs directly

Fails usability goal: asking creators to separately choose delivery mode, encryption, buyer password, seller activation, seat enforcement and risk posture recreates a technical admin screen.

Result: `REJECT UI / COMPOSE INTO FOUR PRESETS`.

## Raison d'être Destroy result

```text
DROP            -> no; hand-editing remains painful
EXTERNALIZE     -> checkout yes: Stripe Payment Links
COMPOSE         -> yes; existing runtime + schema + pricing registry + external checkout metadata
MANUAL_BOUNDED  -> yes; operator still deploys exported files and paid fulfillment is manual
GLUE            -> yes; thin UI + validation endpoint + protection preset mapping
IRREDUCIBLE_BUILD -> package-builder semantics, checkout metadata, four-level distribution contract and mobile form
```

The Creator Studio does **not** become a separate service in v0.

## Authority boundaries

Hard rules:

- Studio is opt-in via `WEB_AI_STUDIO_ENABLED`; disabled by default.
- Validation does not write runtime package files.
- Validation does not call an AI provider.
- Validation does not accept/store provider API keys.
- Validation does not accept/store Stripe secret keys or card data.
- Validation does not accept/store buyer passphrases or seller signing keys.
- `ACCESS PRICE != INFERENCE COST` remains explicit.
- `PAYMENT LINK != VERIFIED ENTITLEMENT` remains explicit.
- `PORTABLE != SECRET` remains explicit.
- `LICENSE TERMS != TECHNICAL COPY CONTROL` remains explicit.
- `BUYER PASSPHRASE != PERFECT DRM` remains explicit.
- `ACTIVATION != PERFECT DRM` remains explicit.
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
- Protection Levels 1-3 require explicit creator acknowledgement that technical copy prevention is not guaranteed.
- Level 1 must state `NOT_GUARANTEED`.
- Level 2 must state `CONTRACT_ONLY` + `PLANNED_ENCRYPTION` until package encryption/passphrase enrollment exists.
- Level 3 must state `CONTRACT_ONLY` + `PLANNED_ENTITLEMENT` until activation/seat/revocation/exit behavior exists.
- Level 3 seller-side control means signed/server-verifiable activation, not a raw seller password handed to the buyer.
- Level 4 maps to the strongest currently realizable `HOSTED_BOUNDARY`.

## Protection preset mapping

```text
LEVEL 1 — LEVEL_1_LICENSE_ONLY
mode                       PORTABLE_LICENSE
buyer passphrase           no
seller activation          no
seat enforcement           no
implementation             AVAILABLE
copy guarantee             NOT_GUARANTEED

LEVEL 2 — LEVEL_2_BUYER_PASSPHRASE
mode                       PORTABLE_LICENSE
buyer passphrase           yes (planned)
seller activation          no
seat enforcement           no
implementation             CONTRACT_ONLY
copy guarantee             PLANNED_ENCRYPTION

LEVEL 3 — LEVEL_3_DUAL_CONTROL_ACTIVATION
mode                       PORTABLE_LICENSE
buyer passphrase           yes (planned)
seller activation          yes (planned signed activation)
seat enforcement           creator intent
implementation             CONTRACT_ONLY
copy guarantee             PLANNED_ENTITLEMENT

LEVEL 4 — LEVEL_4_HOSTED_ONLY
mode                       HOSTED_ONLY
buyer passphrase           no
seller activation          no
seat enforcement           no
implementation             AVAILABLE
copy guarantee             HOSTED_BOUNDARY
```

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
17. Levels 1-3 created without copy-risk acknowledgement.
18. Level 1 falsely claiming technical copy protection.
19. Level 2 being represented as encrypted/implemented in v0.
20. Level 3 being represented as activation/seat-enforced in v0.
21. Level 3 leaking/storing seller signing secret or buyer passphrase in package metadata.
22. Level 4 accidentally exporting a portable protection state.
23. Portable package hiding that Instructions/Knowledge become copyable/inspectable.
24. Successful validation mutating live runtime registry.
25. Oversized Instructions/body.
26. Checked-in example/fixture drifting from canonical schema.
27. Regression of existing BYOK/platform-credit chat tests.

## Findings that reopened the merge gate

### Finding 1 — paid package had no actual access price

Fixed with `access.currency` + `access.price_amount_minor` while preserving `ACCESS PRICE != INFERENCE COST`.

### Finding 2 — schema evolution could stale examples silently

Fixed by validating checked-in example/runtime fixture against canonical schema in CI.

### Finding 3 — paid checkout lacked a low-friction external rail

Fixed by externalizing to Stripe Payment Links and supporting:

```text
SELF_SETUP     -> creator configures Payment Link themselves
ASSISTED_SETUP -> setup support helps with product/price/link/post-payment flow
```

### Finding 4 — Payment Link could be mistaken for entitlement

Fixed by freezing v0 fulfillment as `MANUAL_HANDOFF` and entitlement verification as `NOT_IMPLEMENTED`.

### Finding 5 — sold portable package can be copied

Fixed by refusing fake DRM claims, requiring portable risk acknowledgement and separating portable protection from hosted secrecy.

### Finding 6 — protection choices were still too technical

The creator had to reason about delivery mode and protection mechanics separately. Fixed by collapsing the public UI into four explicit protection presets while preserving the detailed package contract underneath.

Canonical detail: `docs/DISTRIBUTION_SECURITY.md`.

## Completion gate for this /goal

Stop at merge-ready when all are true:

- thin UI exists and is smartphone-oriented;
- Studio is disabled by default;
- generated package passes canonical schema + semantic/economic/distribution gates;
- access price is explicit and independent from inference payer;
- paid checkout metadata distinguishes SELF_SETUP from ASSISTED_SETUP;
- Payment Link is not conflated with verified entitlement;
- Creator Studio visibly offers exactly the four protection levels;
- Levels 1-3 cannot pass without explicit copy-risk acknowledgement;
- Level 2 and Level 3 are never represented as implemented in thin v0;
- Level 3 seller-side factor is modeled as signed activation, not a shared seller password;
- Level 4 maps cleanly to hosted-only boundary;
- package contract never claims guaranteed technical anti-copy protection for portable delivery;
- two export files are produced without server persistence;
- tests cover METEOR economic/authority/checkout/four-level distribution cases;
- existing runtime regression remains green;
- CI is green;
- PR is mergeable and behind main by zero;
- no claim of deployment/mobile/provider/payment/encryption/activation validation is made without runtime evidence.

If any material blocker appears before that point, stop and report the blocker instead of weakening the boundary.
