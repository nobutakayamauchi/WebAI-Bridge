# Runtime

State: `HOSTED_V1_CANDIDATE / FIXED_DOMAIN_REALITY_LOOP_2 / REVALIDATION_REQUIRED`

This is the current hosted WebAI Bridge runtime. It serves activated AI Packages through smartphone URLs, keeps creator Instructions and hosted Knowledge server-side, separates access price from inference cost, and fails closed on package/payment states it cannot enforce.

## Runtime surfaces

### Buyer-only commercial surface

```text
commercial:app
```

Use when package authority is prepared outside the running service and Creator Studio must remain unavailable.

### Creator-managed commercial surface

```text
commercial_handoff:app
```

This extends the canonical commercial gateway with:

- server-owned `PACKAGE_TEXT` Knowledge;
- creator-authenticated Creator Studio;
- direct Package JSON + Instructions + Knowledge publish;
- authority-safe activation and in-process registry reload;
- the existing Stripe webhook/browser handoff/buyer routes.

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
PAID HOSTED + NO ENTITLEMENT != RUNNABLE
PORTABLE INTENT != HOSTED RUNTIME
```

## Paid hosted path

The bounded v1 commercial shape is:

```text
BUY_ONCE
+ HOSTED_ONLY
+ BYOK
+ Stripe Payment Link
+ durable webhook entitlement
+ browser handoff
```

The code also retains bounded subscription/manual entitlement support, but Creator Studio direct publish v1 intentionally accepts BUY_ONCE only.

The fixed-domain Oracle/iPhone acceptance run on revision `9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1` demonstrated the core real chain:

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

That run also found production-only weaknesses. The current branch contains follow-up repairs, so the old live evidence does **not** certify the newer branch head. Exact-revision revalidation is required before a fixed-domain PASS claim.

## Creator Studio

Creator Studio validation covers:

- canonical Package JSON Schema;
- access price and charge basis;
- payer/model/budget policy;
- Stripe checkout binding metadata;
- delivery/readiness boundaries;
- Instructions;
- server-owned Knowledge.

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
→ buyer path
```

A later Studio publish cannot silently overwrite an already-active package. Active authority requires a separate lifecycle operation.

## Creator authentication

When Studio is public, the preflight requires:

- `WEB_AI_CREATOR_AUTH_ENABLED=1`;
- private creator password file outside the runtime/Git tree;
- private creator session-signing secret file outside the runtime/Git tree;
- owner-only file permissions;
- bounded session TTL;
- HTTPS.

The browser receives a signed Secure/HttpOnly creator session cookie. Creator credentials are not placed in URLs.

## Stripe and buyer entitlement

The commercial gateway supports:

- exact Stripe Payment Link/package/price/currency checks on checkout fulfillment;
- persistent single-claim Checkout Session authority;
- durable Stripe webhook fulfillment so entitlement does not depend on a surviving redirect;
- short-lived one-time browser handoff codes;
- signed buyer cookies whose authority is rechecked against the entitlement database;
- revocation that immediately invalidates an existing buyer session.

### Browser handoff authority rule

A real fixed-domain run found that the earlier implementation carried `handoff_...` authority in query strings. That made a one-time authority value visible in the address bar and retainable by access logs.

The current challenger therefore uses:

```text
Stripe completion session_id
→ server verifies paid Checkout Session
→ server issues hashed one-time handoff code
→ same-browser activation: hidden POST body
OR
→ cross-browser transfer: user copies one-time code to a clean /checkout/handoff/{slug} page
→ POST /checkout/activate/{slug}
→ entitlement cookie
```

The handoff code is never embedded in the handoff/activation URL. Production rendering also disables Uvicorn access logs as defense in depth against retaining query-bearing request targets. Completion pages are `no-store` and scrub the Checkout `session_id` from the visible address bar after server verification.

For the production-style `commercial_handoff` surface with active paid packages, startup preflight requires the entitlement-cookie secret, Stripe server/restricted key, and Stripe webhook secret to be configured before the process is allowed to serve.

### External Stripe deployment contract

Local startup preflight proves local secret/config safety; it cannot prove that Stripe's remote objects still point at the intended production host.

Run `stripe_external_acceptance.py` as a separate external gate to validate live Payment Link and webhook bindings. It checks:

- active/live Payment Link;
- package metadata binding (`webai_package_id`, `BUY_ONCE`);
- configured amount/currency/one-time price;
- exact fixed-domain completion redirect containing `{CHECKOUT_SESSION_ID}`;
- exact fixed-domain webhook URL;
- required Checkout fulfillment events.

This validator is intentionally **not** an `ExecStartPre` dependency: ordinary service restart must not fail merely because Stripe's API is temporarily unavailable.

## BYOK

Hosted BYOK is **server-proxy ephemeral**.

The buyer enters a provider API key over HTTPS. The key is kept only in the current process-memory BYOK session, the browser input is cleared, and the browser receives an opaque HttpOnly session cookie. Forget/TTL/process restart removes the key.

The current BYOK store is intentionally single-process memory. Multi-worker/shared-host credential-session semantics are not claimed.

## Knowledge

Current first-class hosted Knowledge is `PACKAGE_TEXT`:

- canonical `{slug}.knowledge.md` server artifact;
- SHA-256 bound from Package JSON;
- bounded local lexical retrieval including Japanese/CJK handling;
- ASCII `_`/`-` compounds indexed as both the full compound and component terms;
- retrieved text treated as untrusted reference context rather than creator/system instruction authority.

The component indexing was added after fixed-domain acceptance demonstrated that `ORACLE` could not retrieve a fact stored only as `ORACLE_FIXED_DOMAIN_...` when the compound was treated as one opaque token.

Legacy/provider vector-store binding remains a separate supported shape where configured. Portable Knowledge packaging is not implemented.

## Safety policy

`runtime/safety_kernel.md` is loaded by the hosted runtime and prepended before creator package Instructions.

Classification:

```text
PROMPT_POLICY_PLUS_PROVIDER_BASELINE
```

This is a server-controlled policy boundary, not a claim of perfect moderation or portable enforcement.

## Deployment identity and package authority

Deployment Identity records the exact service, working directory, route surface and Git revision. Diagnostics remain off by default on public deployments.

For a creator-managed production host, mutable package authority belongs outside the deployed Git/runtime tree, for example:

```text
/var/lib/webai-bridge/apps
```

This keeps `ProtectSystem=strict` meaningful while allowing Creator Studio to publish only under the explicitly writable private state tree.

```text
CODE PRESENT != RUNNING REVISION
FILES CHANGED != RUNNING PROCESS CHANGED
```

## Request and abuse bounds

The runtime bounds current input, history count/size, output tokens, and basic request rate. The current process-local rate limiting is not claimed as a distributed quota/abuse system.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI includes commercial checkout/webhook/handoff, entitlement, ephemeral BYOK, Knowledge, Creator Studio, direct publish, package authority, deployment renderer/preflight, external Stripe contract validation, and end-to-end regression coverage.

## Current non-goals / remaining limits

Not required for the bounded Hosted/BYOK v1 release:

- portable runtime/ZIP execution;
- portable Knowledge secrecy;
- purchased platform wallet/credits;
- creator-funded or sponsored shared inference;
- hybrid payer routing;
- persistent buyer BYOK secret storage;
- generic multi-worker credential sessions;
- perfect DRM;
- OpenAI Plugin delivery.

A generic production claim remains withheld until the **latest** exact branch revision is redeployed and the fixed-domain HTTPS, Creator Studio second-product, live Stripe remote contract, buyer purchase/handoff/BYOK/Knowledge, no-authority-in-URL/log evidence, and revoke/401 boundaries are revalidated on that same revision.
