# WebAI Bridge — Fixed-Domain Hosted v1 Runbook

Status: `HOSTED_V1_CANDIDATE / REALITY_LOOP_2 / EXTERNAL_REVALIDATION_REQUIRED`

This runbook prepares the stable public-host deployment. The first Oracle/iPhone fixed-domain run proved the core chain and then fed production-only findings back into the current challenger. The older live revision does not certify a newer branch head; redeploy and revalidate the exact current revision.

## Deployment profiles

Two deterministic profiles exist.

### Buyer-only

```text
commercial:app
Creator Studio: OFF
Package authority: runtime/apps (read-only to the service)
```

Use this when packages are prepared by an operator outside the running service.

### Creator-managed

```text
commercial_handoff:app
Creator Studio: ON + creator authentication required
Package authority: state/apps
Direct publish: BUY_ONCE + HOSTED_ONLY + BYOK + PACKAGE_TEXT Knowledge
```

Use this when the creator must add products from the smartphone Studio without SSH file transfer.

The creator-managed profile keeps mutable package authority under the private state tree because the service uses `ProtectSystem=strict` and only the state directory is writable.

## Required external inputs

Before a public deployment can be claimed, resolve:

- an Ubuntu/Linux host you control;
- a public hostname;
- DNS pointing that hostname to the host;
- Caddy or equivalent public HTTPS termination;
- creator-owned Stripe Payment Link(s);
- Stripe server/restricted API key and webhook signing secret;
- one buyer-owned provider API key for the live BYOK acceptance call.

Do not put creator passwords, Stripe secrets, entitlement tokens, handoff codes, or buyer provider keys into Git, Package JSON, generated deployment files, shell history, URLs, screenshots, or issue/PR text.

## 1. Host layout

Recommended layout:

```text
/opt/webai-bridge/
  runtime/
  deploy/
  package-schema/
  ...

/var/lib/webai-bridge/
  apps/                         # creator-managed package authority
  entitlements.sqlite3
  ledger.sqlite3
  handoff.sqlite3
  checkout-state.sqlite3
  creator-password.secret       # creator-managed profile only
  creator-session.secret        # creator-managed profile only
```

The service account is `webai` by default.

Create the state directory as a private service-owned directory. For creator-managed deployment, create `apps/` as owner-only and service-writable.

Example shell shape; adapt ownership to the actual service account:

```bash
sudo install -d -m 0700 -o webai -g webai /var/lib/webai-bridge
sudo install -d -m 0700 -o webai -g webai /var/lib/webai-bridge/apps
```

## 2. Pin the exact repository revision

Deploy a specific Git commit, not an unspecified moving branch state.

```bash
cd /opt/webai-bridge
git rev-parse HEAD
```

Keep the full SHA. Rendering embeds it as `DEPLOYED_REVISION`; startup preflight compares it to local Git HEAD when Git metadata exists.

```text
CODE PRESENT != DEPLOYMENT IDENTITY
```

## 3. Runtime environment

From `/opt/webai-bridge/runtime`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Do not start the public service yet.

## 4. Render deployment files

Buyer-only:

```bash
cd /opt/webai-bridge
python3 deploy/render_deployment.py \
  --domain ai.example.com \
  --revision "$(git rev-parse HEAD)" \
  --output-dir /tmp/webai-deploy
```

Creator-managed:

```bash
cd /opt/webai-bridge
python3 deploy/render_deployment.py \
  --domain ai.example.com \
  --revision "$(git rev-parse HEAD)" \
  --creator-studio \
  --output-dir /tmp/webai-deploy
```

Replace `ai.example.com` with the real hostname.

Generated artifacts:

```text
webai-bridge.service
Caddyfile
deployment-manifest.json
```

The manifest contains paths and policy state, not secret values. Production Uvicorn access logging is disabled by the renderer because default access logs retain the full request target/query string. This is defense in depth; buyer handoff authority is also no longer carried in URLs.

The renderer rejects malformed domains, non-exact revisions, unsafe service/path identifiers, overlapping runtime/state directories, world-writable output directories, and symlink output targets.

## 5. Creator authentication files

Skip this section for buyer-only deployment.

The creator-managed renderer points to:

```text
/var/lib/webai-bridge/creator-password.secret
/var/lib/webai-bridge/creator-session.secret
```

Create both as long random owner-only files readable by the service account. Do not pass the values on the command line.

One safe pattern is to enter the private service account shell and generate them directly:

```bash
sudo -u webai sh -c 'umask 077; python3 - <<"PY"
import secrets
from pathlib import Path
root = Path("/var/lib/webai-bridge")
for name in ("creator-password.secret", "creator-session.secret"):
    path = root / name
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
        path.chmod(0o600)
PY'
```

The Studio login password is read from the first file. Read it only in a private administrative session when needed; do not paste it into Git or logs.

## 6. Commercial secret environment

The generated systemd unit optionally reads:

```text
/etc/webai-bridge/webai-bridge.env
```

For the active paid browser/webhook path, configure at minimum:

```text
WEB_AI_ENTITLEMENT_COOKIE_SECRET=<long random secret>
WEB_AI_STRIPE_SECRET_KEY=<Stripe server or restricted key>
WEB_AI_STRIPE_WEBHOOK_SECRET=<Stripe webhook signing secret>
```

Keep the environment file root/service-readable only. Buyer BYOK keys and buyer entitlement tokens do **not** belong there.

The optional environment file is loaded before locked deployment values. It cannot override the rendered route surface, state/config paths, Studio mode, diagnostics mode, insecure-HTTP setting, or exact revision.

For creator-managed deployment with an active paid package, the handoff preflight fails startup if the entitlement-cookie secret, Stripe API key, or webhook secret is missing.

## 7. Install systemd and Caddy

Review the rendered files, then place them in the host's system locations.

The application binds only to:

```text
127.0.0.1:8080
```

Caddy terminates public HTTPS and forwards to localhost. The generated Uvicorn command trusts forwarded proxy headers only from localhost and runs with `--no-access-log`.

Do not add proxy/application request logging that captures credentials, cookies, authorization headers, checkout session identifiers, provider keys, form bodies, or URL query values. If you add operational logging later, design an explicit redaction policy first.

## 8. Startup preflight

Buyer-only systemd uses:

```text
deployment_preflight.py
```

Creator-managed systemd uses:

```text
deployment_preflight_handoff.py
```

A failed preflight prevents startup.

Important failure classes include:

- deployment identity unset/mismatched;
- insecure public diagnostics/HTTP;
- Creator Studio exposed without safe creator auth;
- mutable package authority missing or unsafe;
- state files/parents unsafe or world-readable;
- package/schema/Instructions/Knowledge inconsistencies;
- embedded secret-like Package material;
- missing model pricing evidence;
- active Package with stale readiness/blockers;
- paid Package without entitlement enforcement or checkout binding;
- paid Package with unsupported platform subsidy;
- active paid handoff missing cookie/Stripe/webhook secrets.

Do not bypass preflight to make the service start.

## 9. Add products

### Creator-managed path

Open:

```text
https://ai.example.com/creator/login
```

then `/studio`.

The direct-publish path is:

```text
Studio input
→ validate
→ explicit publish confirmation
→ private temporary Package JSON + Instructions + Knowledge
→ authority-safe three-artifact install
→ Package JSON committed last
→ Knowledge SHA verification
→ activation
→ registry reload
→ /a/{slug}
```

Direct publish v1 supports `BUY_ONCE` only. It refuses silent overwrite of an already-active package.

### Buyer-only/operator path

Use the package installer/activation CLI deliberately. For PACKAGE_TEXT Knowledge, use `package_bundle_cli.py` so Package JSON, Instructions and Knowledge remain one verified authority bundle.

```text
INSTALL != ACTIVATE
```

## 10. Stripe remote contract and webhook

Configure the live Stripe webhook endpoint to:

```text
https://ai.example.com/webhooks/stripe
```

with both fulfillment events:

```text
checkout.session.completed
checkout.session.async_payment_succeeded
```

Each live BUY_ONCE Payment Link must also match the Package contract:

```text
metadata.webai_package_id = {slug}
metadata.access_mode = BUY_ONCE
amount/currency = Package access price
one-time price
active + live mode
completion redirect = https://ai.example.com/checkout/complete/{slug}?session_id={CHECKOUT_SESSION_ID}
```

After the local service is healthy, load the private environment and run the separate external validator:

```bash
cd /opt/webai-bridge/runtime
set -a; . /etc/webai-bridge/webai-bridge.env; set +a
.venv/bin/python stripe_external_acceptance.py --domain ai.example.com --config-dir /var/lib/webai-bridge/apps
```

The Stripe server/restricted key used here needs read access to Payment Links (including line items) and webhook endpoints. The command emits only status/findings, never secret values.

**Do not add this remote check to `ExecStartPre`.** A Stripe API outage must not turn an otherwise healthy local process restart into an outage. This is a deployment/acceptance gate, not a runtime liveness dependency.

Durable webhook fulfillment remains required so a paid entitlement does not depend on the buyer returning through the browser completion page successfully.

Do not treat opening checkout, a redirect, or a client-side success page as payment verification.

## 11. Browser handoff

The fixed-domain acceptance run found that an earlier one-time `handoff_...` authority token was placed in the query string and therefore appeared in the browser URL and Uvicorn journal.

The repaired contract is:

```text
verified Stripe completion
→ one-time handoff code stored hashed server-side
→ completion page uses hidden POST body for same-browser activation
OR
→ user copies one-time code into clean /checkout/handoff/{slug} page in Safari
→ POST /checkout/activate/{slug}
→ entitlement cookie
```

Rules:

- handoff authority must never appear in a URL;
- activation is POST-only;
- code is one-time and TTL-bounded;
- completion/handoff pages are `Cache-Control: no-store`;
- after verification, the completion page scrubs Stripe `session_id` from the visible address bar;
- do not retain or screenshot the one-time transfer code.

A missing `session_id` on the completion route fails closed with a human-readable HTML error rather than raw FastAPI validation JSON.

## 12. Process/revision verification

After deployment or code revision changes, restart the service and verify the actual running service against the rendered revision and preflight result.

For creator-managed product publishing, registry reload occurs in-process after a successful direct publish; a product file appearing on disk alone is still not sufficient evidence of activation.

```text
FILES CHANGED != RUNNING PROCESS CHANGED
```

## 13. Live buyer acceptance

Use the public HTTPS hostname. Verify at minimum:

1. `/health` works;
2. buyer security headers are present;
3. unpaid/missing entitlement is denied;
4. external Stripe contract validator passes;
5. live Stripe payment produces durable entitlement;
6. browser handoff reaches the exact paid Package with no authority in URLs/logs;
7. buyer connects ephemeral BYOK;
8. one small provider request succeeds;
9. PACKAGE_TEXT Knowledge is retrieved when the product uses it, including a component inside an `_`/`-` compound fixture;
10. revocation immediately denies the same buyer again.

Existing `live_acceptance.py` can be used for the bounded perimeter/provider checks where applicable. Do not record secret values or provider response text in evidence.

## 14. Creator-managed second-product proof

On the fixed-domain deployed revision, create a **new second product from Studio without editing repository code or transferring files over SSH**.

Required evidence:

```text
second slug appears as active
its Instructions/Knowledge are isolated from product 1
its Knowledge digest validates
product 1 remains unchanged
active slug overwrite is refused
buyer path is reachable
```

This is the real-infrastructure counterpart to the CI config-only/multi-product proof.

## 15. iPhone/Safari acceptance

Repeat the final buyer flow on the actual iPhone/Safari path after each code revision that changes handoff, entitlement, BYOK, Knowledge, or deployment behavior. Confirm checkout handoff, BYOK connection, chat, Knowledge result, reload/restart behavior, revoked access, and absence of authority/credential values in visible URLs and retained request logs.

Desktop/CI success does not establish the mobile boundary.

## Stop / claim boundary

Advance claims only with corresponding evidence:

```text
CODE / CI PASS
< FIXED-DOMAIN HOST PREFLIGHT PASS
< PROCESS + REVISION IDENTITY PASS
< PUBLIC HTTPS PASS
< STRIPE REMOTE CONTRACT PASS
< CREATOR DIRECT-PUBLISH PASS
< BUYER PAYMENT / ENTITLEMENT / QUERYLESS HANDOFF / BYOK PASS
< SECOND-PRODUCT PASS
< IPHONE + REVOKE PASS
```

None of the lower states imply the higher state. A previous revision's production evidence does not certify a later revision.
