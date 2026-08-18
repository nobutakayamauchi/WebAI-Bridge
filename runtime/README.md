# Runtime

State: `HOSTED_V1_CANDIDATE / FIXED_DOMAIN_REALITY_LOOP_2 / EXACT-HEAD REVALIDATION_REQUIRED`

This is the current hosted WebAI Bridge runtime. It serves activated AI Packages through smartphone URLs, keeps creator Instructions and hosted Knowledge server-side, separates access price from inference cost, and fails closed on package/payment/browser authority it cannot verify.

## Runtime surfaces

### Buyer-only commercial surface

```text
commercial_bound:app
```

Use when package authority is prepared outside the running service and Creator Studio remains unavailable. It preserves `commercial:app` as the canonical paid core and adds initiating-browser Stripe binding.

### Creator-managed commercial surface

```text
commercial_handoff:app
```

This extends the same canonical paid core with:

- initiating-browser Stripe binding;
- server-owned `PACKAGE_TEXT` Knowledge;
- creator-authenticated Creator Studio;
- direct Package JSON + Instructions + Knowledge publish;
- authority-safe activation and in-process registry reload.

Public Creator Studio is fail-closed unless creator authentication is safely configured.

## Core execution invariant

```text
PACKAGE RUNNABLE
→ ACCESS AUTHORIZATION
→ PAYER RESOLUTION
→ CREDENTIAL RESOLUTION
→ BUDGET AUTHORIZATION
→ MODEL RESOLUTION
→ PROVIDER EXECUTION
→ USAGE / LEDGER
```

And:

```text
DRAFT != RUNNABLE
INSTALL != ACTIVATE
PAYMENT LINK != VERIFIED PAYMENT
CHECKOUT SESSION LOCATOR != BROWSER AUTHORITY
BYOK CONNECTED != ACCESS AUTHORITY
PAID HOSTED + NO ENTITLEMENT != RUNNABLE
PORTABLE INTENT != HOSTED RUNTIME
```

## Paid Hosted v1 path

The bounded commercial shape is:

```text
BUY_ONCE
+ HOSTED_ONLY
+ BYOK
+ Stripe Payment Link
+ durable webhook entitlement
+ browser-bound checkout initiation
+ one-time POST-body handoff
```

Creator Studio direct publish v1 intentionally accepts `BUY_ONCE` only.

The first Oracle/iPhone fixed-domain run on revision `9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1` demonstrated:

```text
live Stripe payment
→ fixed-domain webhook fulfillment
→ durable entitlement
→ iPhone Safari buyer handoff
→ ephemeral BYOK
→ PACKAGE_TEXT Knowledge
→ live provider response
→ revocation
→ same buyer immediately denied with 401
```

That old-revision run found production-only weaknesses and therefore does **not** certify the newer branch head.

## Creator Studio

On `commercial_handoff:app`, an authenticated creator can explicitly publish a validated BUY_ONCE bundle:

```text
validate
→ explicit publish confirmation
→ private temporary artifacts
→ Package JSON + Instructions + Knowledge install
→ Package JSON authority commit last
→ Knowledge digest verification
→ activate entitlement enforcement
→ registry reload
→ buyer path /a/{slug}
```

A later Studio publish cannot silently overwrite an already-active package. Publish output uses the WebAI buyer path / browser-bound checkout route, not the raw Stripe Payment Link as the normal sale URL.

## Creator authentication

When Studio is public, preflight requires:

- `WEB_AI_CREATOR_AUTH_ENABLED=1`;
- private creator password file outside runtime/Git;
- private creator session-signing secret outside runtime/Git;
- safe file/parent permissions;
- bounded session TTL;
- HTTPS.

The browser receives a signed Secure/HttpOnly creator session cookie. Creator credentials are not placed in URLs.

## Stripe, browser binding, and buyer entitlement

Durable webhook fulfillment and browser possession are intentionally separate authorities.

Normal buyer flow:

```text
/a/{slug}
→ /api/buy/{slug}
→ generate public client_reference_id
→ sign it into a short-lived HttpOnly package-scoped browser cookie
→ redirect to the configured Stripe Payment Link with client_reference_id
→ Stripe payment
→ webhook creates/preserves durable entitlement
→ fixed-domain completion carries session_id as a locator
→ server verifies Stripe Session + Payment Link
→ Session client_reference_id must match the signed initiating-browser cookie
→ one-time handoff code
→ POST /checkout/activate/{slug}
→ signed entitlement cookie
```

Security rules:

- a valid paid Checkout Session without initiating-browser proof returns 403;
- a mismatched `client_reference_id` returns 403;
- browser-binding cookie tamper/expiry/wrong package fails closed;
- the browser-binding proof is cleared after successful completion;
- `handoff_...` authority is never placed in handoff/activation URLs;
- handoff activation is POST-only, one-time and TTL-bounded;
- completion/handoff pages are no-store;
- production Uvicorn access logging is disabled as defense in depth;
- raw Payment Link is configuration, not the normal buyer distribution URL.

A raw Payment Link can still produce a valid Stripe payment and durable webhook entitlement, but without `/api/buy/{slug}` the browser deliberately cannot mint access authority.

### Revocation

Buyer cookies are rechecked against the entitlement database. The real fixed-domain run proved:

```text
BYOK session still connected
+ entitlement revoked
→ next /api/chat = 401
```

## Paid startup preflight

Both deterministic paid profiles share commercial secret/environment checks when active paid packages exist:

```text
WEB_AI_ENV_FILE must be safe and outside runtime
WEB_AI_ENTITLEMENT_COOKIE_SECRET present
WEB_AI_STRIPE_SECRET_KEY structurally valid
WEB_AI_STRIPE_WEBHOOK_SECRET structurally valid
```

Profile-specific preflights:

```text
BUYER_ONLY_COMMERCIAL_V1
→ deployment_preflight_bound.py

CREATOR_STUDIO_COMMERCIAL_V1
→ deployment_preflight_handoff.py
```

They delegate canonical paid checks rather than creating independent commercial policy.

## External Stripe deployment contract

Local startup safety cannot prove Stripe's remote objects still match the fixed-domain deployment. Run `stripe_external_acceptance.py` as a separate deployment/acceptance gate.

It validates:

- active/live Payment Link;
- exact package metadata (`webai_package_id`, `BUY_ONCE`);
- amount/currency/one-time line items;
- exact fixed-domain `{CHECKOUT_SESSION_ID}` completion redirect;
- exact fixed-domain webhook URL;
- required Checkout fulfillment events.

Payment Links, webhook endpoints and Payment Link line items are paginated to completion. Missing advancement ids, non-object data, or repeated pagination cursors fail closed so remote objects beyond the first page cannot be hidden by truncation.

This validator is intentionally **not** `ExecStartPre`: a temporary Stripe API/control-plane outage must not prevent a healthy local service restart.

## BYOK

Hosted BYOK is **server-proxy ephemeral**.

The buyer enters a provider API key over HTTPS. The key is retained only in current process memory; the browser input is cleared and receives an opaque HttpOnly session cookie. Forget/TTL/process restart removes the key.

The current BYOK store is intentionally single-process memory. Multi-worker/shared-host credential-session semantics are not claimed.

## Knowledge

Current first-class Hosted Knowledge is `PACKAGE_TEXT`:

- canonical `{slug}.knowledge.md` server artifact;
- SHA-256 bound from Package JSON;
- bounded local lexical retrieval including Japanese/CJK handling;
- ASCII `_`/`-` compounds indexed as both full compounds and component terms;
- retrieved text remains untrusted reference context below server Safety/Creator Instructions.

Component indexing was added after the real acceptance fixture `ORACLE_FIXED_DOMAIN_...` could not be retrieved by an `ORACLE`-only query.

Portable Knowledge packaging/secrecy is not implemented.

## Safety policy

`runtime/safety_kernel.md` is loaded by the hosted runtime and prepended before creator package Instructions.

Classification:

```text
PROMPT_POLICY_PLUS_PROVIDER_BASELINE
```

This is a server-controlled policy boundary, not a claim of perfect moderation or portable enforcement.

## Deployment identity and package authority

Deployment Identity records the exact service, working directory, route surface and Git revision. Diagnostics remain off by default on public deployment.

Creator-managed mutable package authority belongs outside the deployed Git/runtime tree, for example:

```text
/var/lib/webai-bridge/apps
```

This keeps `ProtectSystem=strict` meaningful while allowing authenticated direct publish only under the explicitly writable private state tree.

```text
CODE PRESENT != RUNNING REVISION
FILES CHANGED != RUNNING PROCESS CHANGED
```

## Request and abuse bounds

The runtime bounds input size, history count/size, output tokens, and basic request rate. Current process-local rate limiting is not claimed as a distributed quota/abuse system.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI covers commercial checkout/webhook/handoff, browser binding, entitlement/revocation, ephemeral BYOK, PACKAGE_TEXT retrieval, Creator Studio/direct publish, package authority, deterministic deployment renderer/preflight, external Stripe remote-contract validation, pagination failure modes, and end-to-end regression paths.

## Current non-goals / remaining limits

Not required for bounded Hosted/BYOK v1:

- portable runtime/ZIP execution;
- portable Knowledge secrecy;
- purchased platform wallet/credits;
- creator-funded or sponsored shared inference;
- hybrid payer routing;
- persistent buyer BYOK secret storage;
- generic multi-worker credential sessions;
- perfect DRM;
- OpenAI Plugin delivery.

A generic production claim remains withheld until the **latest exact PR head** is redeployed and the fixed-domain HTTPS, Stripe remote contract, browser-bound buyer flow, Creator second-product authority, live BYOK/Knowledge result, no-authority-in-URL/log boundary, and revoke/401 behavior are revalidated on that same revision.
