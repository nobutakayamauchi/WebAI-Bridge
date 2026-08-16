# /goal — Creator Studio thin v0

Date: 2026-08-16
Method: Ultimate Loop / Raison d'être / METEOR / DA / Counter-DA
Status: `BOUNDED_CHALLENGER / FINAL_GATE_PENDING_LATEST_CI`

## Protected outcome

A creator/operator can define and export a second WebAI Bridge AI Package from a smartphone without hand-writing package JSON, while preserving explicit access-price, inference-payer, budget, model, checkout, safety and distribution-authority boundaries.

The thin v0 must not become a full admin/payment/auth/control-plane SaaS merely to prove package creation.

## Raison d'être result

Rejected or deferred:
- hand-editing JSON as the normal workflow;
- browser-only validation as sole authority;
- a full persistence/admin dashboard now;
- custom card handling;
- fake DRM claims;
- many low-level protection knobs in the creator UI;
- implementing wallet/auth/portable activation just because the contract mentions them.

Promoted composition:

```text
mobile Creator Studio
→ existing FastAPI runtime validation
→ semantic/economic/distribution/readiness gates
→ canonical package schema + pricing evidence
→ explicit export only
```

Checkout remains externalized to creator-owned Stripe Payment Links.

## Creator-facing contract

Creator Studio covers:
- AI name/slug/description;
- Instructions;
- hosted Knowledge binding intent;
- access mode + JPY price + charge basis;
- Stripe self/assisted setup metadata;
- BYOK / bounded PLATFORM_CREDIT;
- allowed/default models;
- four protection levels;
- usage bounds;
- readiness blockers;
- Package JSON + Instructions export.

## Four protection presets

```text
LEVEL 1 — LICENSE ONLY
portable contract intent
no technical anti-copy guarantee
portable runtime NOT IMPLEMENTED

LEVEL 2 — BUYER PASSPHRASE
planned portable encryption
CONTRACT_ONLY
portable runtime NOT IMPLEMENTED

LEVEL 3 — DUAL CONTROL ACTIVATION
planned buyer passphrase + seller/WebAI Bridge signed activation
CONTRACT_ONLY
portable runtime NOT IMPLEMENTED

LEVEL 4 — HOSTED ONLY
current hosted runtime boundary
paid entitlement NOT IMPLEMENTED
```

## Hard invariants after DA / Counter-DA

```text
ACCESS PRICE != INFERENCE COST
PAYMENT LINK != VERIFIED ENTITLEMENT
CHECKOUT URL != VERIFIED PRICE BINDING
DRAFT != RUNNABLE
CONFIG_VALID != READY_TO_RUN != READY_TO_SELL
NOT PERSISTED != NEVER SEEN BY SERVER
PORTABLE != SECRET
PORTABLE INTENT != PORTABLE RUNTIME
LICENSE TERMS != TECHNICAL COPY CONTROL
BUYER PASSPHRASE != PERFECT DRM
ACTIVATION != PERFECT DRM
SERVER SECRET/ENV BINDING != PORTABLE RESOURCE
PRICE AMOUNT WITHOUT CHARGE BASIS != COMPLETE COMMERCIAL CONTRACT
OBSERVED ACTUAL COST MUST NOT BE HIDDEN BY RESERVATION
```

## DA / Counter-DA findings that survived

Full record: `docs/DA_COUNTER_DA_CREATOR_STUDIO_V0.md`.

Resolved/currently bounded findings:
1. draft packages now fail closed in runtime;
2. paid hosted execution now fails closed until entitlement exists;
3. config validity is separate from runtime/commercial readiness;
4. hosted BYOK explicitly discloses server-proxy transport;
5. observed cost above reservation is recorded truthfully;
6. history total size is bounded;
7. runtime validates package schema and canonical instruction path;
8. hosted server-controlled Safety policy now precedes creator Instructions;
9. runtime diagnostics are opt-in;
10. Levels 1-3 explicitly state portable runtime is not implemented;
11. generic paid modes now carry explicit `UNSPECIFIED_*` charge basis blockers;
12. Stripe self-setup requires creator attestation that checkout matches package configuration.

Counter-DA deliberately deferred:
- reservation IDs/idempotent settlement/crash lease recovery;
- distributed/proxy-aware user rate limiting;
- automated Stripe product/price/cadence verification;
- user/creator wallet allocation runtime;
- real Level 2/3 cryptography, signing, activation and exit behavior.

Those are production/v1 gates, not reasons to bloat thin v0.

## Hosted runtime gate

Current runtime intentionally allows only:
- `status = dogfood|active`;
- `delivery.mode = HOSTED_ONLY`;
- hosted runtime implementation available;
- currently free access.

Thus:

```text
draft                -> BLOCK
portable             -> BLOCK
paid hosted/no auth  -> BLOCK
```

The dogfood fixture remains a free hosted runnable package.

## Safety classification

The hosted runtime loads `runtime/safety_kernel.md` and prepends it before creator package Instructions.

Classification:

`PROMPT_POLICY_PLUS_PROVIDER_BASELINE`

No claim of perfect moderation, portable enforcement or DRM is made.

## Current METEOR / regression surface

Tests cover at least:
- Studio disabled by default;
- payer/budget/model/Knowledge failures;
- access-price and charge-basis failures;
- Stripe self/assisted checkout boundaries;
- Payment Link vs entitlement;
- draft/paid/portable runtime fail-closed;
- four protection levels and risk acknowledgement;
- portable runtime/resource blockers;
- BYOK server-proxy disclosure metadata;
- canonical package/path validation;
- Safety-policy ordering;
- input/history/history-size bounds;
- platform budget exhaustion;
- provider failure reservation release;
- observed actual-cost reservation overrun accounting;
- checked-in fixture/schema drift.

Latest verified CI before final documentation closeout: **45 pytest cases passed** with one non-blocking dependency deprecation warning.

## Final stop condition

Per `/goal`, stop **before merge** when the latest branch head satisfies all of:
- CI green;
- PR mergeable;
- branch behind `main` by zero;
- no unresolved release-blocking finding inside the frozen thin-v0 workload;
- no unverified deployment/mobile/live-provider/payment/portable-runtime claim.

If the latest documentation closeout invalidates CI or mergeability, reopen work instead of weakening the gate.
