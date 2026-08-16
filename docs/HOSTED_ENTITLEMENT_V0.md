# Hosted Entitlement v0 — Manual Paid Sale Path

Date: 2026-08-16
Status: `BOUNDED_MANUAL_COMMERCIAL_PATH / NOT_PRODUCTION`

This is the first intentionally narrow paid-hosted path for WebAI Bridge.

## Supported product shape

```text
BUY_ONCE or SUBSCRIPTION
+ LEVEL_4_HOSTED_ONLY
+ BYOK only
+ creator-owned Stripe Payment Link
+ operator manually verifies payment
+ one bearer entitlement per payment
```

Anything outside that shape fails closed in the commercial gateway.

## Why this shape first

The first paid product must not create accidental unlimited inference subsidy.

Therefore paid-hosted v0 refuses `PLATFORM_CREDIT` and other shared/subsidized inference payer combinations. The buyer supplies their own provider API key. Access price and provider inference cost remain separate.

```text
ACCESS PRICE != INFERENCE COST
```

## Deployment entrypoint

Use:

```bash
uvicorn commercial:app --host 127.0.0.1 --port 8080
```

The commercial gateway reuses the tested core provider/cost path and adds buyer entitlement enforcement in front of paid package config/chat access.

Required persistent paths should be explicitly configured in deployment:

```bash
WEB_AI_ENTITLEMENT_DB=/var/lib/webai-bridge/entitlements.sqlite3
WEB_AI_LEDGER_PATH=/var/lib/webai-bridge/ledger.sqlite3
```

Do not place either database in a public web directory.

## Operator sale workflow

### 1. Create/export the package

Use Creator Studio. For the first commercial path choose:

- `BUY_ONCE` or `SUBSCRIPTION`;
- Level 4 Hosted Only;
- BYOK only;
- Stripe Payment Link present and correctly bound to the package price/cadence.

Studio export remains `draft` by design.

### 2. Deploy package files and explicitly activate

After the package JSON and Instructions file are placed in the runtime app directory:

```bash
cd runtime
python entitlement_cli.py activate-config --config apps/my-ai.json
```

Activation refuses:

- non-buy-once/non-subscription paid modes;
- portable modes;
- PLATFORM_CREDIT/shared subsidy;
- missing Stripe Payment Link;
- missing SELF_SETUP creator checkout attestation.

Activation changes the package to `active` and `ENTITLEMENT_ENFORCED`. It is an operator-only explicit mutation, not a public Studio publish endpoint.

### 3. Verify payment manually

Check the creator's Stripe account/dashboard. Do not issue an entitlement merely because checkout was opened or redirected.

Record a non-secret payment reference, ideally a Stripe payment/checkout reference visible to the operator.

### 4. Issue buyer entitlement

Buy-once:

```bash
python entitlement_cli.py issue \
  --config apps/my-ai.json \
  --payment-verified \
  --payment-ref pay_example_001 \
  --buyer-ref buyer-opaque-001 \
  --base-url https://ai.example.com
```

Buy-once deliberately has no `--days` expiry.

Subscription:

```bash
python entitlement_cli.py issue \
  --config apps/my-ai.json \
  --payment-verified \
  --payment-ref pay_example_002 \
  --buyer-ref buyer-opaque-002 \
  --days 31 \
  --base-url https://ai.example.com
```

Subscription issuance refuses to create a non-expiring entitlement.

The CLI prints the plaintext token exactly at issuance time. The SQLite store contains only its SHA-256 digest.

## 5. Hand off fragment URL

Example:

```text
https://ai.example.com/a/my-ai#access=webai_...
```

The URL fragment is not sent in the initial HTTP request. The paid buyer page copies it into browser `sessionStorage` and removes the fragment from the visible address bar before package-config access.

The buyer's BYOK provider key is separate. It is sent to the WebAI Bridge server for each provider request and is not intentionally persisted by the application.

## Revocation / recovery

Bearer token available:

```bash
python entitlement_cli.py revoke --token 'webai_...'
```

Bearer token no longer retained by the operator:

```bash
python entitlement_cli.py revoke-payment \
  --package my-ai \
  --payment-ref pay_example_001
```

An active payment reference cannot accidentally receive two simultaneous active entitlements. After revocation, the same payment reference may be used to issue a replacement token.

Inspect non-secret entitlement metadata:

```bash
python entitlement_cli.py list --package my-ai
```

## Security boundary

Hard rule:

```text
BEARER TOKEN = ACCESS AUTHORITY
```

If the buyer shares their token, the recipient can use the AI until expiry or revocation. This v0 does not claim:

- identity-bound authentication;
- device binding;
- concurrency enforcement;
- perfect anti-sharing;
- Stripe webhook verification;
- DRM.

The token is high entropy and stored only as a digest server-side, but bearer-token sharing remains a real product limitation.

## Proxy/logging requirements before public deployment

Do not intentionally log:

- `X-WebAI-Entitlement`;
- `X-Provider-API-Key`;
- query/body secrets.

The access token is passed in a URL fragment specifically to avoid placing it in ordinary HTTP request URLs. Reverse proxy and application logging must still be reviewed before deployment.

## Current acceptance evidence

CI covers:

- token plaintext absent from entitlement DB;
- wrong/expired/cross-package token rejection;
- config endpoint blocked without buyer token;
- direct chat bypass blocked before provider call;
- valid token + BYOK execution;
- revocation;
- duplicate active payment-ref issuance blocked;
- payment-ref revocation and reissue;
- paid PLATFORM_CREDIT refused;
- unsupported paid modes refused;
- free hosted regression;
- explicit operator activation;
- issue requires `--payment-verified`;
- subscription requires expiry;
- buy-once refuses artificial time expiry.

Live provider, live Stripe, deployment identity, reverse-proxy logging, TLS, and iPhone acceptance remain separate evidence gates.
