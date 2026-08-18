# /goal — Hosted v1 fixed-domain Creator Studio path

Date: 2026-08-18
Method: `Ultimate Loop / Raison d'être / DA / Counter-DA / METEOR`
Status: `REALITY_LOOP_2 / CODE_REPAIRS_IN_PROGRESS / EXACT_REVISION_REVALIDATION_REQUIRED`

## Protected outcome

A creator can run WebAI Bridge on a stable HTTPS hostname, create and directly publish a second paid Hosted/BYOK/Knowledge AI from the authenticated smartphone Creator Studio, sell it through the Stripe entitlement path, and preserve safe stop/recovery boundaries without mutating the deployed Git tree or leaking buyer/creator authority into URLs or retained logs.

The goal is **not** to implement every future payer, portable, wallet, subscription, plugin, or admin feature before the first bounded Hosted v1 release.

## Raison d'être

The product already proved the commercial chain in dogfood. PR #30 then connected Creator Studio to deterministic fixed-domain deployment and reached a code-side PRE-MERGE STOP.

The next step was deliberately not more simulation: deploy that exact revision to the controlled Oracle host and attack it from the real iPhone/Stripe boundary.

That real run on:

```text
9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
```

proved:

```text
exact revision + systemd preflight
→ fixed-domain Caddy HTTPS
→ iPhone creator login
→ second product direct publish without Git/SSH file transfer
→ live Stripe BUY_ONCE payment
→ fixed-domain webhook entitlement
→ iPhone buyer handoff
→ ephemeral BYOK
→ PACKAGE_TEXT retrieval + live provider response
→ entitlement revoke
→ same buyer immediately denied with 401
```

The same run also exposed real-environment faults that CI had not forced. Those findings are now inputs to a second Ultimate Loop. Therefore the successful old-revision evidence does **not** certify the newer branch head.

## Loop 1 — code-side findings already closed

### Finding 1 — direct publish was disconnected from production rendering

Observed:

```text
Creator Studio direct publish exists
BUT
render_deployment.py forced commercial:app + Studio OFF
```

Resolution: explicit profiles.

```text
BUYER_ONLY_COMMERCIAL_V1
→ commercial:app
→ Studio OFF

CREATOR_STUDIO_COMMERCIAL_V1
→ commercial_handoff:app
→ Studio ON
→ creator auth required
```

### Finding 2 — systemd sandbox would kill direct publish

Bad composition:

```text
WEB_AI_CONFIG_DIR=/opt/webai-bridge/runtime/apps
ProtectSystem=strict
ReadWritePaths=/var/lib/webai-bridge
```

Resolution:

```text
WEB_AI_CONFIG_DIR=/var/lib/webai-bridge/apps
package_authority=STATE_DIR
```

The Git/runtime tree stays read-only; mutable creator package authority stays in the private state tree.

### Finding 3 — active paid surface could start with guaranteed late failure

For active paid `commercial_handoff`, local preflight requires:

```text
WEB_AI_ENTITLEMENT_COOKIE_SECRET
WEB_AI_STRIPE_SECRET_KEY
WEB_AI_STRIPE_WEBHOOK_SECRET
```

Missing/structurally invalid values stop startup before a buyer reaches the broken route.

### Finding 4 — second-product acceptance was weaker than the product claim

Added real filesystem/registry E2E proving two direct-published products can coexist and that an active slug cannot be silently overwritten.

### Finding 5 — documentation had become false runtime evidence

Root/runtime/deploy documentation was aligned to the actual current Hosted path while preserving explicit non-claims.

### Finding 6 — valid secrets in an unsafe env file are still a breach

The deployment pins:

```text
WEB_AI_ENV_FILE=/etc/webai-bridge/webai-bridge.env
```

and rejects unsafe/missing/symlink/world-readable/group-writable runtime secret authority.

## Loop 2 — real Oracle/iPhone findings

### Reality finding 7 — one-time handoff authority appeared in URL and retained journal

Observed in the real host:

```text
GET /checkout/handoff/{slug}?ticket=handoff_...
POST /checkout/activate/{slug}?ticket=handoff_...
```

Uvicorn's default access log retained the full request target, and the browser-visible URL itself contained the one-time authority.

This violated the external acceptance rule:

```text
NO CREDENTIAL / AUTHORITY TOKEN IN VISIBLE URL OR RETAINED EVIDENCE
```

A first response — disabling Uvicorn access logs — was necessary but insufficient because it did not remove authority from the browser URL.

#### Resolution

The current challenger changes the transport itself:

```text
verified Stripe completion
→ issue one-time handoff code; store only hash server-side
→ same-browser activation: hidden POST body
OR
→ clean /checkout/handoff/{slug} page in Safari
→ user copies one-time transfer code
→ POST body to /checkout/activate/{slug}
→ entitlement cookie
```

Properties:

- `handoff_...` is never embedded in handoff/activation URLs;
- activation is POST-only;
- one-time/TTL/atomic-consume semantics are retained;
- completion and handoff pages are `no-store`;
- completion page scrubs the Stripe `session_id` from the visible address bar after verification;
- production Uvicorn access logging is disabled as defense in depth;
- deployment manifest records that access logging/query-authority retention are disabled.

Cross-browser convenience is intentionally weaker than leaking an authority-bearing URL: a buyer moving from an embedded browser to Safari copies a short-lived one-time transfer code into a clean Safari claim page.

### Reality finding 8 — Stripe remote configuration can drift outside local preflight

The first real payment exposed two external mismatches:

- Payment Link metadata/redirect contract was not yet aligned to the package/runtime contract;
- the Stripe webhook endpoint still targeted a retired Quick Tunnel instead of the fixed hostname.

The local service was healthy and all secret **values** were present, so startup preflight could not detect this remote configuration drift.

#### Counter-DA

Do **not** make systemd startup depend on Stripe API availability. A temporary Stripe control-plane outage must not prevent an otherwise healthy service from restarting.

#### Resolution

Add a separate external deployment/acceptance validator:

```text
stripe_external_acceptance.py
```

It validates active runnable BUY_ONCE packages against Stripe remote state:

- Payment Link URL binding;
- `webai_package_id` metadata;
- `access_mode=BUY_ONCE` metadata;
- active/live mode;
- amount/currency/one-time line items;
- exact fixed-domain completion redirect with `{CHECKOUT_SESSION_ID}`;
- exact fixed-domain webhook endpoint;
- enabled live endpoint;
- both required Checkout fulfillment events.

This is a deployment gate, not a runtime liveness gate.

### Reality finding 9 — `_`/`-` compound Knowledge terms were opaque to component queries

Fixture:

```text
ACCEPTANCE_SECRET_PHRASE = ORACLE_FIXED_DOMAIN_SECOND_PRODUCT_20260818
```

Observed:

- query containing `ACCEPTANCE_SECRET_PHRASE` retrieved the chunk and yielded a correct Knowledge-dependent `YES`;
- query asking only whether the environment was `ORACLE / AWS / AZURE` returned `不明`.

Cause:

The ASCII tokenizer retained `_`/`-` compounds as one token, so `ORACLE` did not intersect `ORACLE_FIXED_DOMAIN_...`.

#### Resolution

Preserve the full compound token for specificity **and** index meaningful component tokens split on `_`/`-`.

Regression tests cover:

- underscore component retrieval;
- hyphen component retrieval;
- exact compound retrieval remains intact.

### Reality finding 10 — missing Checkout Session surfaced raw framework validation JSON

Observed on iPhone:

```json
{"detail":[{"type":"missing","loc":["query","session_id"],...}]}
```

A later request with a real Checkout Session ID completed successfully, so the observed 422 was not treated as proof of Stripe substitution failure.

#### Resolution

Make `session_id` optional at the route boundary, fail closed in application code, and return a human-readable no-store HTML error with HTTP 400 when it is absent.

This keeps the security requirement — no payment claim without a verified Stripe Session — while removing raw framework UX.

## Reality proof retained from the first fixed-domain run

The old revision established that the major authority order is viable:

```text
PAYMENT VERIFIED
→ DURABLE ENTITLEMENT ACTIVE
→ BROWSER ACCESS
→ BYOK SESSION
→ MODEL EXECUTION
```

and that revocation remains authoritative:

```text
BYOK SESSION STILL EXISTS
+ ENTITLEMENT REVOKED
→ NEXT CHAT = 401
```

So:

```text
BYOK CONNECTED != ACCESS AUTHORITY
```

That result remains useful architecture evidence, but every code change to handoff/retrieval/deployment now requires exact-revision revalidation before release status advances.

## Frozen Hosted v1 candidate scope

Required for this bounded release:

```text
HOSTED_ONLY
BUY_ONCE direct publish
BYOK inference
server-owned Instructions
PACKAGE_TEXT Knowledge
creator authentication
Stripe Payment Link
Stripe webhook entitlement
queryless/body browser handoff
revocation
fixed-domain HTTPS deployment
exact revision identity
no credential/authority in visible URL or retained evidence
```

Not required for this gate:

```text
portable runtime
portable Knowledge secrecy
wallet/purchased platform credits
creator-funded shared inference
sponsored/hybrid payer routing
full subscription automation
multi-worker BYOK credential sharing
perfect DRM
OpenAI Plugin delivery
```

Those can re-enter as separate goals after the Hosted v1 proof.

## METEOR attack set for the current challenger

Code/CI must reject or preserve safety under at least:

- Creator Studio enabled without creator auth;
- missing/unsafe creator password/session secret files;
- active paid handoff without cookie/Stripe/webhook secrets;
- missing/symlinked/world-readable/group-writable commercial env file;
- product Package/Instructions/Knowledge permission widening;
- Knowledge digest mismatch;
- draft package pretending to be active/runnable;
- active package silent overwrite;
- second product corrupting first product state;
- direct publish writing into deployed Git/runtime under systemd sandbox;
- route surface/profile mismatch;
- diagnostics or insecure HTTP re-enabled by operator env overrides;
- secret values entering generated deployment artifacts;
- browser handoff authority appearing in any generated handoff/activation URL;
- activation via GET;
- handoff-code replay after first consume;
- stale/Quick-Tunnel Stripe webhook satisfying fixed-domain acceptance;
- Payment Link with wrong package metadata, amount, currency, recurring mode, or completion redirect;
- `_`/`-` compound Knowledge term failing component retrieval;
- missing checkout `session_id` exposing raw framework error rather than fail-closed human UX.

Existing Stripe replay, webhook idempotency, checkout binding, BYOK, entitlement/revocation, Knowledge authority, and Creator Studio tests remain in the regression surface.

## External reality gate — second pass

After the current branch CI is green, repeat on the controlled host with the **new exact head**:

```text
new exact branch revision deployed
→ renderer --creator-studio regenerated from that SHA
→ systemd preflight PASS under service identity
→ fixed-domain HTTPS PASS
→ production command includes --no-access-log
→ external Stripe contract validator PASS
→ creator login + existing package authority intact
→ product 1 unchanged
→ active slug overwrite refused
→ buyer payment/entitlement on this exact revision
→ no handoff authority in URL
→ no handoff authority retained in journal
→ queryless/body handoff succeeds on iPhone Safari
→ ephemeral BYOK
→ Knowledge component query retrieves ORACLE fixture
→ live provider response
→ revoke
→ immediate 401
```

No old-revision evidence is silently promoted to certify the new head.

## Merge gate

Stop before merge when all code-side conditions are true:

```text
latest branch CI green
PR mergeable
no unresolved composition conflict
queryless/body handoff tests green
external Stripe contract tests green
compound Knowledge retrieval tests green
existing commercial/Stripe/BYOK/Knowledge/Creator Studio tests green
no surviving code-side release blocker inside frozen Hosted v1 scope
latest exact revision still requires/has explicit real-host evidence
```

Even after the fixed-domain gate passes, PR #30 remains Draft until the human explicitly decides to merge.
