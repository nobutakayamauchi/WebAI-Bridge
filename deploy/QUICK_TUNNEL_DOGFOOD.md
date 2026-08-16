# Quick Tunnel Dogfood — Temporary External HTTPS

Status: `DOGFOOD_ONLY / NOT_PRODUCTION`

Purpose: reach the external HTTPS/iPhone/provider evidence gates before owning or configuring a permanent domain.

Cloudflare Quick Tunnels are explicitly a testing/development path. They generate a random public `trycloudflare.com` hostname that proxies to a local service. Do not use this as the production distribution URL.

Official reference:
- https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

## Why use it here

The first external dogfood does not need Stripe or a permanent domain. The checked-in free fixture can prove:

```text
real host
→ public HTTPS edge
→ commercial gateway
→ FREE Hosted package
→ buyer BYOK transport
→ live provider
→ iPhone/Safari
```

Paid entitlement/Stripe evidence remains a separate later gate.

## 1. Start the WebAI Bridge commercial gateway locally

The public tunnel should point only to the localhost-bound service:

```text
127.0.0.1:8080
```

Use the normal deployment identity/preflight requirements. Do not set `WEB_AI_ALLOW_INSECURE_HTTP=1` for the externally reachable process.

The public request must arrive at the commercial gateway as HTTPS through trusted proxy headers. If the commercial gateway returns HTTP 426 through the tunnel, treat that as a failed transport gate; do not weaken the HTTPS rule just to make the tunnel pass.

## 2. Start a temporary Quick Tunnel

With `cloudflared` installed on the same host:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

The command prints a random public URL similar to:

```text
https://random-words.trycloudflare.com
```

Keep that terminal/process running during the dogfood session.

Do not treat the random URL as stable product infrastructure.

## 3. Perimeter-only free acceptance

From a second machine/network if possible:

```bash
cd runtime
python live_free_acceptance.py \
  --base-url https://random-words.trycloudflare.com \
  --slug migration-fixture-ai
```

This performs no provider call and proves only:

- public HTTPS URL responds;
- health responds;
- free Hosted page exists;
- public config is the expected FREE Hosted package;
- BYOK is allowed.

## 4. One live BYOK provider call

After perimeter acceptance passes:

```bash
python live_free_acceptance.py \
  --base-url https://random-words.trycloudflare.com \
  --slug migration-fixture-ai \
  --provider-call
```

The provider API key is entered through a hidden interactive prompt. It is not placed in the command line or acceptance output.

The acceptance evidence records only:

- model;
- payer mode;
- response character count;
- response SHA-256.

It does not print the provider response text or provider key.

## 5. iPhone/Safari

Open:

```text
https://random-words.trycloudflare.com/a/migration-fixture-ai
```

Observe:

- mobile page renders;
- BYOK input is usable;
- one real chat request succeeds;
- provider key does not appear in the URL;
- failure/reload behavior is understandable.

Record this separately from command-line acceptance.

## Boundaries

Quick Tunnel success does **not** establish:

- permanent DNS ownership;
- production TLS/reverse-proxy configuration;
- stable URL availability;
- paid entitlement correctness;
- real Stripe payment;
- production abuse/rate-limit posture.

It exists only to shorten the path to real external runtime evidence.
