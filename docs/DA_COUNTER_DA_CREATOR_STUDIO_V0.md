# DA / Counter-DA — Creator Studio thin v0

Date: 2026-08-16
Status: `COUNTER_DA_COMPLETE / SURVIVING_FINDINGS_FIXED_OR_EXPLICITLY_DEFERRED`

## Method

```text
DA
→ assume abuse, sharing, retry, copy, stale state, misconfiguration and misleading UX
→ produce a concrete failure

Counter-DA
→ attack the finding itself
→ reject speculative scope creep
→ keep only findings that violate a current invariant or would poison the future contract
```

The merge gate was reopened for findings that survived Counter-DA. Current disposition follows.

## Surviving findings and disposition

### F1 — draft could become runnable

Finding: Creator Studio exports `status=draft`, while runtime previously did not enforce it.

Resolution: `FIXED`.

```text
DRAFT != RUNNABLE
```

Runtime now accepts only explicit runnable states (`dogfood` / `active`).

### F2 — paid hosted URL bypassed access entitlement

Finding: a shared URL could bypass access price; platform-funded use could also consume creator/platform budget.

Resolution: `FIXED FAIL-CLOSED`.

Paid hosted execution is blocked until verified entitlement exists.

```text
PAID HOSTED + NO ENTITLEMENT != RUNNABLE
```

### F3 — config-valid looked like sale/run ready

Resolution: `FIXED`.

Studio now returns machine-readable:
- configuration state;
- runtime readiness;
- commercial readiness;
- blockers.

```text
CONFIG_VALID != READY_TO_RUN != READY_TO_SELL
```

### F4 — BYOK disclosure understated server visibility

Finding: "not stored" did not explain that hosted BYOK traverses the WebAI Bridge server.

Resolution: `FIXED DISCLOSURE + CONTRACT`.

Package metadata uses `SERVER_PROXY_EPHEMERAL`; Studio and runtime UI explain the server-proxy path.

```text
NOT PERSISTED != NEVER SEEN BY SERVER
```

### F5 — actual cost over reservation could be hidden

Finding: settlement previously used `min(actual, reserved)`.

Resolution: `FIXED ACCOUNTING TRUTH`.

Observed actual cost is recorded even when it exceeds reservation and the budget hard limit after the provider charge has already happened. Later reservations then fail closed.

### F6 — history count bounded, history size unbounded

Resolution: `FIXED` with `max_history_chars` plus message-count and current-message limits.

### F7 — instructions path boundary weak

Resolution: `FIXED`.

Runtime validates canonical package schema and requires exactly:

```text
apps/{slug}.instructions.md
```

resolved inside the runtime app-instructions directory.

### F8 — Safety Kernel was described but absent

Resolution: `FIXED WITH HONEST CLASSIFICATION`.

`runtime/safety_kernel.md` is server-controlled and prepended before creator Instructions.

Classification:

`PROMPT_POLICY_PLUS_PROVIDER_BASELINE`

No perfect moderation or portable enforcement is claimed.

### F9 — runtime diagnostics were public-by-default

Resolution: `FIXED`.

`/runtime` is disabled unless `WEB_AI_DIAGNOSTICS_ENABLED=1`.

### F10 — portable levels existed before portable runtime

Finding: Studio exports JSON + Instructions, not a runnable portable ZIP. Portable configs could also refer to server-only Knowledge/budget resources.

Resolution: `FIXED READINESS/CLAIMS`.

All Levels 1-3 now carry `runtime_implementation=NOT_IMPLEMENTED` and readiness blockers. Portable runtime, portable Knowledge binding and portable server-funded payer paths are not claimed.

```text
PORTABLE INTENT != PORTABLE RUNTIME
SERVER SECRET/ENV BINDING != PORTABLE RESOURCE
```

### F11 — generic paid modes had ambiguous price basis

Resolution: `FIXED CONTRACT`.

`charge_basis` is now explicit:
- FREE -> FREE
- BUY_ONCE -> ONE_TIME
- SUBSCRIPTION -> MONTHLY
- PER_USE -> PER_RUN
- PAID -> UNSPECIFIED_PAID
- ALLOWANCE_THEN_PAID -> UNSPECIFIED_AFTER_ALLOWANCE

Generic paid modes receive a commercial blocker until made specific.

```text
PRICE AMOUNT WITHOUT CHARGE BASIS != COMPLETE COMMERCIAL CONTRACT
```

## Counter-DA findings deliberately deferred

These are real but did **not** justify turning thin v0 into a production control plane.

### D1 — reservation identity / idempotency / crash lease recovery

Status: `PRODUCTION BLOCKER / DEFERRED`.

Current synchronous path is acceptable for dogfood; retry/multi-worker wallet semantics must add reservation identity and recovery.

### D2 — reverse-proxy-aware distributed rate limiting

Status: `DEPLOYMENT/PRODUCTION BLOCKER / DEFERRED`.

Current in-memory IP limiter is only a dogfood guard.

### D3 — automated Stripe product/price/cadence verification

Status: `MANUAL V0 GATE / AUTOMATE LATER`.

Self setup requires creator attestation that checkout matches package configuration. Assisted setup remains pending/manual review. Automated Stripe verification belongs with later checkout/entitlement integration.

### D4 — creator/user budget allocation runtime

Status: `V1 RUNTIME BLOCKER`.

`EQUAL`, `INDIVIDUAL`, `INDIVIDUAL_THEN_SHARED` and per-user cap contracts remain frozen, but need authenticated user identity and wallet runtime.

### D5 — Level 2/3 cryptography/activation

Status: `CONTRACT_ONLY / PORTABLE RUNTIME BLOCKED`.

No encryption, passphrase enrollment, activation signing, seat enforcement, revocation or exit-key behavior is represented as implemented.

## Regression evidence required

The following DA surfaces are regression-tested:
- draft fail-closed;
- paid hosted fail-closed;
- portable hosted-runtime rejection;
- readiness separation;
- BYOK transport disclosure metadata;
- Safety policy ordering;
- runtime schema/path validation;
- history total-size limit;
- actual-cost reservation overrun accounting;
- Stripe self-setup attestation;
- checkout-pending blocker;
- explicit charge basis;
- Levels 1-3 portable runtime blockers;
- portable server Knowledge/funded-payer blockers.

Latest verified CI before this documentation closeout: **45 pytest cases passed** with one non-blocking dependency deprecation warning.

## Final merge-gate rule

Return to `MERGE_READY` only if the latest branch head remains CI-green, mergeable, and not behind `main` after this documentation closeout.

No merge is authorized by this document.
