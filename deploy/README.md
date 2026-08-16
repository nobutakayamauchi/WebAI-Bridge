# WebAI Bridge — First Deployment Runbook

Status: `READY_FOR_EXTERNAL_DOGFOOD / NOT_DEPLOYED`

This runbook intentionally stops where real infrastructure evidence begins.

## Required external inputs

Before a public deployment can be claimed, resolve:

- an Ubuntu/Linux host you control;
- a public hostname for the AI endpoint;
- DNS pointing that hostname to the host;
- public HTTPS termination/reverse proxy;
- one paid-hosted test Package;
- one test buyer entitlement;
- optionally one buyer-owned provider API key for a single live BYOK call.

Do not put entitlement tokens or provider API keys into Git, Package JSON, generated deployment files, shell history, or command-line arguments.

## 1. Host layout

Canonical first deployment layout:

```text
/opt/webai-bridge/
  runtime/
  deploy/
  package-schema/
  ...

/var/lib/webai-bridge/
  entitlements.sqlite3
  ledger.sqlite3
```

The service account is `webai` by default.

Create the state directory as a private service-owned directory. The application and deployment preflight also tighten/check the SQLite files themselves.

The current Package installer writes newly installed Package JSON and Instructions owner-only.

## 2. Put the exact repository revision on the host

Deploy a specific Git commit, not an unspecified moving branch state.

From the deployed repository root:

```bash
git rev-parse HEAD
```

Keep that exact full SHA. Deployment config rendering embeds it as `DEPLOYED_REVISION`, and startup preflight compares it to local Git HEAD when Git metadata is present.

```text
CODE PRESENT != DEPLOYMENT IDENTITY
```

## 3. Create the runtime virtual environment

From `/opt/webai-bridge/runtime`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Do not start the public service yet.

## 4. Render deployment files

From repository root:

```bash
python3 deploy/render_deployment.py \
  --domain ai.example.com \
  --revision "$(git rev-parse HEAD)" \
  --output-dir /tmp/webai-deploy
```

Replace `ai.example.com` with the real hostname.

The renderer rejects:

- malformed/publicly unusable domain input;
- non-exact revisions;
- unsafe path characters that could alter the systemd unit;
- runtime/state directory overlap in either direction;
- unsafe Unix service names;
- world-writable output directory;
- symlink output targets.

Generated files:

```text
webai-bridge.service
Caddyfile
deployment-manifest.json
```

The manifest contains no secret values.

## 5. Operator environment bindings

The generated unit optionally reads:

```text
/etc/webai-bridge/webai-bridge.env
```

Use it only for operator-controlled runtime bindings that cannot live in Package JSON, such as an active Knowledge vector-store binding.

The generated unit loads this optional file **before** its locked security/Deployment Identity values. The unit then explicitly sets:

- route surface;
- runtime/config/state paths;
- diagnostics off;
- Creator Studio off;
- insecure HTTP override off;
- exact deployed revision.

Do not place buyer BYOK keys or buyer entitlement tokens in this environment file.

## 6. Install service/reverse-proxy configs

Review the generated files before placing them in the host's system locations.

The application service binds only to localhost:

```text
127.0.0.1:8080
```

The public hostname terminates HTTPS at the reverse proxy and forwards to that local service.

The generated systemd unit trusts forwarded proxy headers only from localhost.

Do not add request logging that captures:

- `X-WebAI-Entitlement`;
- `X-Provider-API-Key`.

Before starting the service, make sure the real systemd unit contains the exact deployed SHA rather than the example placeholder.

## 7. Startup preflight

The generated unit runs:

```text
ExecStartPre=.../deployment_preflight.py
```

A failed preflight prevents the service from starting.

Important startup failures include:

- Deployment Identity unset/mismatched;
- insecure public debug/Studio settings;
- unsafe state paths/permissions;
- package/schema/Instructions inconsistencies;
- embedded secret-like Package JSON material;
- missing model pricing evidence;
- active Knowledge with missing binding;
- active Package with stale blockers/runtime readiness;
- active paid Package without reviewed checkout binding;
- active paid Package with shared/platform subsidy;
- active paid Package outside the current Hosted/BYOK-only commercial shape.

Do not bypass the preflight to make the service start.

## 8. Install a Studio export

Use the operator installer rather than manually copying two files:

```bash
cd /opt/webai-bridge/runtime
.venv/bin/python package_install_cli.py \
  --package /path/to/exported-package.json \
  --instructions /path/to/exported-instructions.md
```

The installed Package remains `draft`.

```text
INSTALL != ACTIVATE
```

## 9. Review checkout and activate

For SELF_SETUP, the Package must already carry creator checkout attestation.

For ASSISTED_SETUP, verify the real Stripe product/link matches:

- product;
- amount;
- currency;
- charge basis (one-time vs monthly).

Then activate explicitly:

```bash
.venv/bin/python entitlement_cli.py activate-config \
  --config apps/my-ai.json \
  --checkout-reviewed
```

Omit `--checkout-reviewed` only when the package's checkout binding is already in an accepted verified state.

Activation does not prove buyer payment.

## 10. Restart and observe running identity

The registry is process-local. File changes are not evidence that the running process loaded them.

After the intended package state changes, perform an explicit service restart and verify service status/logs.

```text
FILES CHANGED != RUNNING PROCESS CHANGED
```

Do not claim successful deployment merely because the service manager says the process is running.

## 11. Verify one buyer payment and issue one entitlement

After manually verifying the payment in the creator's payment account:

Buy-once example:

```bash
.venv/bin/python entitlement_cli.py issue \
  --config apps/my-ai.json \
  --payment-verified \
  --payment-ref NON_SECRET_PAYMENT_REFERENCE \
  --buyer-ref TEST_BUYER_REFERENCE \
  --base-url https://ai.example.com
```

For subscription, also provide a bounded positive `--days` value.

The CLI prints the bearer token once. Do not paste the token into logs/issues/Git.

## 12. Live perimeter acceptance

From a machine that reaches the **public HTTPS hostname**, run:

```bash
cd runtime
python live_acceptance.py \
  --base-url https://ai.example.com \
  --slug my-ai
```

The tool prompts for the buyer entitlement without echoing it.

It verifies:

1. HTTPS origin;
2. `/health`;
3. paid buyer-page security headers;
4. missing entitlement gets HTTP 401;
5. the supplied entitlement opens the exact active paid Hosted/BYOK-only Package;
6. provider call remains skipped by default.

The result contains no entitlement token.

## 13. One live BYOK provider call

Only after perimeter acceptance passes:

```bash
python live_acceptance.py \
  --base-url https://ai.example.com \
  --slug my-ai \
  --provider-call
```

The tool separately prompts for the provider API key without echoing it.

It performs one small chat request and records only non-secret evidence:

- model;
- payer mode;
- response character count;
- SHA-256 of response text.

It does not print the provider response text, buyer entitlement, or provider key.

## 14. iPhone/Safari dogfood

After command-line live acceptance passes, use the buyer handoff URL on the actual iPhone/Safari path.

Observe at minimum:

- fragment token is removed from the visible address after capture;
- reload/tab behavior is understandable;
- BYOK entry works;
- chat request works;
- invalid/revoked token fails cleanly;
- no secret appears in visible URLs;
- mobile layout remains usable.

This is a separate acceptance gate. Desktop/curl success does not establish iPhone correctness.

## Stop/claim boundary

Only after the corresponding evidence exists may these states advance:

```text
CODE MERGED
< HOST PREFLIGHT PASS
< PROCESS RUNNING
< PUBLIC HTTPS PASS
< BUYER ENTITLEMENT PASS
< LIVE PROVIDER PASS
< IPHONE PASS
```

None of the lower states imply the higher state.
