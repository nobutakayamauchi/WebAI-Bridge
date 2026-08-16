# DA / Counter-DA — Creator Studio thin v0

Date: 2026-08-16
Status: `ACTIVE_REVIEW / MERGE_GATE_REOPENED`

This record attacks the current Creator Studio + runtime design, then attacks the attacks. Only findings that survive Counter-DA are allowed to reopen the merge gate.

## Method

```text
DA
→ assume the current design will be abused, misunderstood, retried, copied, shared or misconfigured
→ identify a concrete failure

Counter-DA
→ ask whether the failure is already bounded by the frozen v0 workload
→ reject speculative scope creep
→ retain only failures that violate a current invariant or would make a future-safe contract materially harder
```

## Findings that survived Counter-DA

### F1 — `draft` package can become executable merely by being placed in the runtime config directory

DA:
Creator Studio emits `status = draft`, but the current runtime does not enforce status before serving `/a/{slug}` or `/api/chat`.

Counter-DA:
The v0 operator handoff is intentionally manual, but manual placement is not equivalent to an explicit activation decision. A draft must remain non-runnable by default.

Decision: `FIX NOW`.

Invariant:

```text
DRAFT != RUNNABLE
```

### F2 — paid hosted package has no entitlement enforcement

DA:
A paid hosted package can be reached by anyone who has the URL. With BYOK, a copied URL can bypass the package access price entirely. With platform credit, a copied URL can also consume the funded pool.

Counter-DA:
The docs already say `PAYMENT LINK != VERIFIED ENTITLEMENT`, but runtime behavior must also fail closed. A warning is insufficient if the runtime still executes the package.

Decision: `FIX NOW`.

Invariant:

```text
PAID HOSTED + NO ENTITLEMENT ENFORCEMENT != RUNNABLE COMMERCIAL PRODUCT
```

### F3 — schema-valid / Studio-valid can be mistaken for sale-ready

DA:
Level 2/3 protection is contract-only, assisted checkout may be pending, paid hosted entitlement is not implemented, and platform-funded public use lacks per-user allocation. Yet validation currently returns `valid: true` without a machine-readable readiness distinction.

Counter-DA:
Studio must still be able to export future-intent drafts. Blocking all exports would destroy the thin-v0 purpose. The correct split is configuration validity vs commercial/runtime readiness.

Decision: `FIX NOW`.

Invariant:

```text
CONFIG_VALID != READY_TO_SELL != READY_TO_RUN
```

### F4 — hosted BYOK traverses the WebAI Bridge server

DA:
The UI says the key is not stored and remains page-memory-only, but the browser sends it to `/api/chat`; the server therefore sees and forwards the provider credential.

Counter-DA:
A hosted secret Instructions/Knowledge boundary requires a server-side provider call in the current architecture. Ephemeral proxy transport is acceptable for v0 if it is disclosed and not persisted/logged intentionally.

Decision: `FIX DISCLOSURE + CONTRACT NOW`.

Invariant:

```text
NOT PERSISTED != NEVER SEEN BY SERVER
```

### F5 — actual platform cost can exceed reservation while ledger charges only the reservation

DA:
Current settlement uses `min(actual_cost, reserved_cost)`. If provider-observed cost exceeds the estimate, the ledger under-reports spend even though the external provider charge already happened.

Counter-DA:
Reservation is deliberately conservative, but no estimator is a proof. Accounting truth must survive estimate failure even if a one-request overrun cannot be retroactively prevented.

Decision: `FIX NOW`.

Invariant:

```text
OBSERVED ACTUAL COST > RESERVED COST
→ RECORD ACTUAL COST
→ DO NOT HIDE OVERRUN
```

### F6 — history count is bounded but history size is not

DA:
An attacker can submit the allowed number of history messages with extremely large contents. This can increase memory use and provider input cost far beyond the intended message limit.

Counter-DA:
This is directly inside the current chat endpoint and does not require future auth/payment work.

Decision: `FIX NOW` with an explicit total-history-character limit.

### F7 — `instructions_file` is not constrained to the package instruction directory

DA:
A manually supplied package can reference a relative path outside the intended app instruction directory. Future package ingestion would turn this into a file-read boundary problem.

Counter-DA:
Creator Studio currently emits a safe path, but runtime is the final authority and must reject non-canonical package paths.

Decision: `FIX NOW`.

Invariant:

```text
PACKAGE PATH != ARBITRARY SERVER FILE PATH
```

### F8 — Safety Kernel is described but not independently present in hosted runtime

DA:
Distribution docs cite hosted Safety enforcement as a benefit, but runtime currently sends only creator package instructions plus the provider's own baseline safeguards.

Counter-DA:
Provider safety exists, but it is not a WebAI Bridge Safety Kernel. Either implement a bounded immutable server-side policy layer or stop claiming one.

Decision: `FIX NOW` by adding an immutable hosted server-instruction policy and classifying it honestly as prompt/policy enforcement, not perfect moderation or portable enforcement.

### F9 — runtime diagnostics reveal filesystem/deployment details whenever reachable

DA:
`/runtime` exposes working directory and ledger path. Useful for Deployment Identity, unnecessary for public users.

Counter-DA:
Deployment Identity remains required, but it can be opt-in rather than public-by-default.

Decision: `FIX NOW` by making diagnostics opt-in.

### F10 — portable protection levels exist before a portable runtime/package actually exists

DA:
Creator Studio currently exports Package JSON + Instructions. It does not yet build a runnable ZIP/portable runtime. Portable contracts can also select server-only concepts such as PLATFORM_CREDIT or a server Vector Store environment binding that would not exist in a buyer-controlled environment.

Counter-DA:
Keeping portable intent in the schema is valuable because it freezes the product model. Claiming any portable level is currently runnable/sellable is not.

Decision: `FIX READINESS/CLAIMS NOW`; do not build the portable runtime inside this PR.

Invariant:

```text
PORTABLE INTENT != PORTABLE RUNTIME
SERVER SECRET/ENV BINDING != PORTABLE RESOURCE
```

All portable levels remain contract/design intent until a real portable artifact, provider credential path, Knowledge packaging/remote binding policy, and acceptance test exist.

## Findings that did not justify immediate implementation

### D1 — reservation IDs / idempotent settlement / crash leases

Real concern:
Aggregate `reserved_micros` has no reservation identity. Duplicate settlement/release or process crash can make recovery ambiguous.

Counter-DA result:
Current synchronous single-call runtime does not retry settlement and a stuck reservation fails conservative. Production wallet/webhook/retry work must add reservation identity and lease recovery before multi-worker/retry semantics are claimed.

Decision: `DEFERRED PRODUCTION BLOCKER`, not a reason to build the wallet control plane inside Creator Studio thin v0.

### D2 — reverse-proxy-aware per-user rate limiting

Real concern:
IP rate limiting is in-memory and may see the proxy address rather than the end user; multiple workers also have independent counters.

Counter-DA result:
Proper identity/rate policy depends on deployment topology and future auth. Keep current limiter as a dogfood guard only.

Decision: `DEPLOYMENT/PRODUCTION BLOCKER`.

### D3 — Stripe price/mode API verification

Real concern:
An HTTPS Payment Link can point at the wrong product, amount, currency or billing cadence.

Counter-DA result:
V0 checkout is intentionally creator-owned/manual and carries no Stripe secret/API integration. Add manual binding/readiness evidence before sale; automated Stripe verification remains later.

Decision: `MANUAL V0 GATE / AUTOMATE LATER`.

### D4 — creator budget allocation runtime

Real concern:
A public funded pool can be consumed unfairly by one user even while the total hard cap prevents unlimited loss.

Counter-DA result:
The canonical billing spec already freezes `EQUAL`, `INDIVIDUAL`, and `INDIVIDUAL_THEN_SHARED`. Correct enforcement needs user identity and belongs with USER_CREDIT/CREATOR_PAYS runtime.

Decision: `V1 RUNTIME BLOCKER`, with v0 warning/ready-state treatment where relevant.

### D5 — Level 2/3 real cryptography and activation

Real concern:
Contract-only protection can be misunderstood as implemented protection.

Counter-DA result:
Implementing encryption, signing infrastructure, entitlement, revocation and exit behavior now would violate the thin-v0 scope. Machine-readable readiness must block commercial claims instead.

Decision: `KEEP CONTRACT-ONLY / BLOCK READY-TO-SELL CLAIM`.

## Merge gate

The PR may return to `MERGE_READY` only after F1-F10 are either implemented and regression-tested or explicitly downgraded in product claims so the current runtime cannot contradict the contract.
