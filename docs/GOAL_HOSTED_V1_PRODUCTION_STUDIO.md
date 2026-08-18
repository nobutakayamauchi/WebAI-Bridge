# /goal — Hosted v1 fixed-domain Creator Studio path

Date: 2026-08-18
Method: `Ultimate Loop / Raison d'être / DA / Counter-DA / METEOR`
Status: `REALITY_LOOP_2 / CODE-SIDE PRE-MERGE CANDIDATE / EXACT-HEAD REALITY REVALIDATION REQUIRED`

## Protected outcome

A creator can run WebAI Bridge on a stable HTTPS hostname, create and directly publish a second paid Hosted/BYOK/PACKAGE_TEXT AI from authenticated smartphone Creator Studio, sell it through Stripe, and preserve fail-closed package/payment/browser/credential authority boundaries without mutating the deployed Git tree.

The bounded Hosted v1 goal does **not** require portable runtime, wallet/platform credit, creator-funded or sponsored inference, full subscription automation, multi-worker BYOK, DRM, or OpenAI Plugin delivery.

## Reality anchor

The first fixed-domain Oracle/iPhone run deployed:

```text
9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
```

and proved on real infrastructure:

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

That run also exposed production-only failures. It is architecture evidence, **not** certification of the newer PR head.

## Loop 1 — production composition findings already closed

### 1. Creator direct publish was disconnected from deterministic production rendering

Resolution: explicit profiles.

```text
BUYER_ONLY_COMMERCIAL_V1
→ commercial_bound:app
→ Studio OFF
→ package authority runtime/apps

CREATOR_STUDIO_COMMERCIAL_V1
→ commercial_handoff:app
→ Studio ON + creator auth
→ package authority state/apps
```

`commercial_bound:app` and `commercial_handoff:app` both preserve `commercial:app` as the canonical paid core while adding profile-specific browser/Creator behavior.

### 2. systemd sandbox would make Creator publish fail only in production

Bad composition:

```text
WEB_AI_CONFIG_DIR=/opt/webai-bridge/runtime/apps
ProtectSystem=strict
ReadWritePaths=/var/lib/webai-bridge
```

Creator-managed resolution:

```text
WEB_AI_CONFIG_DIR=/var/lib/webai-bridge/apps
package_authority=STATE_DIR
```

The deployed Git/runtime tree remains read-only.

### 3. Active paid runtime could start with guaranteed late failure

Both paid production profiles now require, when an active paid package exists:

```text
WEB_AI_ENTITLEMENT_COOKIE_SECRET
WEB_AI_STRIPE_SECRET_KEY
WEB_AI_STRIPE_WEBHOOK_SECRET
safe WEB_AI_ENV_FILE outside runtime
```

The secret-file and live-sale checks are shared so buyer-only and Creator-managed startup policy cannot silently diverge.

### 4. Second-product proof had mocked the package authority boundary

A real filesystem/registry E2E now proves:

- Package JSON + Instructions + Knowledge install through the actual bundle authority;
- Package JSON commits last;
- activation revalidates Knowledge digest;
- two active products coexist;
- active slug silent overwrite is refused;
- product 1 remains isolated.

### 5. Documentation had become false runtime evidence

Root/runtime/deploy/goal documentation is kept aligned to current Hosted behavior and explicit non-claims.

## Loop 2 — real Oracle/iPhone/Stripe findings

### 6. Stripe Payment Link metadata was weaker than runtime binding

The first real link did not carry the runtime-required package/access metadata.

Required remote contract:

```text
metadata.webai_package_id = {slug}
metadata.access_mode = BUY_ONCE
```

Runtime validates the verified Checkout Session and Payment Link against the package before fulfillment.

### 7. Stripe webhook still targeted a retired Quick Tunnel

A healthy local process and valid secret values did not prove the Stripe control plane pointed at the fixed domain.

Resolution: separate external deployment gate:

```text
runtime/stripe_external_acceptance.py
```

It validates:

- Payment Link URL and metadata binding;
- active/live mode;
- amount/currency/one-time line items;
- exact fixed-domain `{CHECKOUT_SESSION_ID}` completion redirect;
- exact fixed-domain webhook URL;
- required fulfillment events.

Counter-DA: this remains **outside `ExecStartPre`**. A temporary Stripe API outage must not prevent a healthy service restart.

### 8. External Stripe list truncation could create a false PASS

Counter-DA found the first external validator paginated Payment Links/webhooks but fetched only the first Payment Link line-items page.

Resolution:

- all Stripe list authorities use the same complete-pagination helper;
- Payment Links, webhook endpoints and Payment Link line items paginate to completion;
- non-object list entries, missing advancement ids, and repeated pagination cursors fail closed.

A 101st remote object cannot be silently ignored by the acceptance gate.

### 9. One-time `handoff_...` authority appeared in URL and journal

Observed on the real host:

```text
GET /checkout/handoff/{slug}?ticket=handoff_...
POST /checkout/activate/{slug}?ticket=handoff_...
```

Resolution:

```text
verified completion
→ hashed one-time handoff code
→ hidden POST body for same-browser activation
OR
→ clean /checkout/handoff/{slug} manual transfer page
→ POST /checkout/activate/{slug}
→ entitlement cookie
```

Properties:

- no handoff authority in handoff/activation URLs;
- POST-only activation;
- one-time atomic consume + TTL;
- no-store completion/handoff responses;
- production Uvicorn access logging disabled as defense in depth.

### 10. Counter-DA: a leaked Checkout Session id was still enough to mint new browser authority

Moving `handoff_...` out of the URL was insufficient. Before the deeper repair, anyone possessing a valid paid `session_id` could call the completion route and mint a fresh one-time handoff code.

That made the Stripe Session locator an accidental authority token.

#### Resolution — initiating-browser binding

Normal buyer flow is now:

```text
/a/{slug}
→ /api/buy/{slug}
→ generate public wb_... client_reference_id
→ signed HttpOnly package-scoped initiating-browser cookie
→ Stripe Payment Link + client_reference_id
→ payment/webhook entitlement
→ /checkout/complete/{slug}?session_id=...
→ verify Stripe Session + Payment Link
→ require Stripe client_reference_id == signed initiating-browser cookie
→ only then mint one-time body handoff code
```

Security consequences:

- Checkout Session id is a transaction locator, not sufficient browser authority;
- a valid paid Session without the initiating-browser proof returns 403;
- a mismatched public reference returns 403;
- browser proof is short-lived and cleared after successful completion;
- replay after proof consumption is denied;
- raw Payment Link is configuration, not the normal distribution URL;
- Creator publish output exposes `/a/{slug}` and `/api/buy/{slug}`, not the raw Stripe URL as the sale path.

The browser-only wrapper is used by both deterministic production profiles.

### 11. Missing Checkout Session exposed raw framework JSON

Observed on iPhone:

```json
{"detail":[{"type":"missing","loc":["query","session_id"],...}]}
```

Resolution: missing `session_id` fails closed in application code with human-readable no-store HTML 400. No payment/browser authority is minted.

### 12. PACKAGE_TEXT `_`/`-` compounds were opaque to component queries

Real fixture:

```text
ORACLE_FIXED_DOMAIN_SECOND_PRODUCT_20260818
```

`ACCEPTANCE_SECRET_PHRASE` retrieval proved PACKAGE_TEXT worked, but an `ORACLE`-only question did not match the underscore compound.

Resolution: preserve the full compound token **and** index meaningful `_`/`-` components. Regression tests cover underscore, hyphen, and exact-compound behavior.

### 13. BYOK session survived while access authority was revoked

The real run proved the desired order:

```text
BYOK SESSION STILL CONNECTED
+ ENTITLEMENT REVOKED
→ next /api/chat = 401
```

Invariant retained:

```text
BYOK CONNECTED != ACCESS AUTHORITY
```

## Counter-DA regression set

Current CI must preserve or reject safely under at least:

- Creator Studio exposed without creator auth;
- unsafe creator password/session files;
- active paid runtime without cookie/Stripe/webhook secrets;
- unsafe commercial env-file authority;
- buyer-only and Creator-managed preflight policy drift;
- mutable creator package authority under a read-only systemd tree;
- active Package/Knowledge integrity failure;
- product 2 corrupting product 1;
- active slug silent overwrite;
- raw Payment Link returned as normal Creator publish sale URL;
- checkout started without browser binding;
- valid paid Session presented without initiating-browser cookie;
- mismatched Stripe `client_reference_id`;
- browser-binding cookie tamper/wrong secret/expiry;
- handoff authority in a query URL;
- activation through GET;
- handoff-code replay;
- missing checkout Session raw framework error;
- stale Quick-Tunnel webhook satisfying fixed-domain acceptance;
- Payment Link metadata/amount/currency/recurrence/redirect drift;
- Stripe pagination truncation/repeated cursor;
- `_`/`-` compound component retrieval regression;
- revoke failing to override an existing BYOK session;
- generated production artifacts containing secrets;
- production route/profile mismatch;
- raw Uvicorn access logging re-enabled by the deterministic renderer.

## Frozen Hosted v1 candidate scope

Required:

```text
HOSTED_ONLY
BUY_ONCE direct publish
BYOK inference
server-owned Instructions
PACKAGE_TEXT Knowledge
creator authentication
Stripe Payment Link + webhook entitlement
browser-bound checkout initiation
body-only one-time handoff authority
revocation
fixed-domain HTTPS
exact revision identity
no credential/authority in visible URL or retained request evidence
```

Deferred:

```text
portable runtime / portable Knowledge secrecy
wallet / purchased platform credits
creator-funded shared inference
sponsored / hybrid payer routing
full subscription automation
multi-worker BYOK credential sharing
perfect DRM
OpenAI Plugin delivery
```

## Exact-head external reality gate

Code/CI success does not promote the old Oracle evidence to the new head. Before `HOSTED_V1_FIXED_DOMAIN_PASS`, redeploy the **exact latest PR #30 head** and re-run:

```text
exact SHA checkout/deploy
→ renderer --creator-studio regenerated from that SHA
→ generated service has --no-access-log
→ systemd handoff preflight PASS as service identity
→ fixed-domain HTTPS PASS
→ Stripe external acceptance PASS
→ creator login
→ existing package authority intact
→ product 1 unchanged
→ active slug overwrite refused
→ buyer opens /a/{slug} and checkout starts through /api/buy/{slug}
→ live Stripe payment/webhook entitlement
→ valid Session without browser proof denied
→ bound browser completion succeeds
→ no handoff authority in visible URL/journal
→ iPhone Safari body handoff
→ ephemeral BYOK
→ ORACLE component query retrieves PACKAGE_TEXT fixture
→ bounded live provider response
→ revoke
→ same buyer immediate 401
```

Do not create an extra paid test transaction merely to prove a code condition that can be proven without money. Use the smallest bounded live payment needed for the final exact-head chain.

## Merge gate

Stop before merge only when:

```text
latest exact branch CI green
PR remains open + Draft + mergeable
no unresolved review/composition blocker
all code-side DA/counter-DA findings in frozen Hosted v1 scope are closed
exact-head production evidence is either completed or explicitly the only remaining external gate
```

PR #30 must **not** be merged automatically. A merge is an irreversible boundary for this `/goal` and remains a separate human decision.
