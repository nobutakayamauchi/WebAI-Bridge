# Quick Tunnel Dogfood — Temporary External HTTPS

Status: `DOGFOOD_ONLY / NOT_PRODUCTION`

Purpose: reach the external HTTPS/iPhone/provider evidence gates before owning or configuring a permanent domain.

Cloudflare Quick Tunnels are explicitly a testing/development path. They generate a random public `trycloudflare.com` hostname that proxies to a local service. Do not use this as the production distribution URL.

Official reference:
- https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

## Why use it here

The external dogfood path can prove:

```text
real host
→ public HTTPS edge
→ commercial gateway
→ Hosted package
→ buyer BYOK transport
→ live provider
→ iPhone/Safari
```

Paid Stripe/entitlement evidence is a separate gate and has its own evidence record. A Quick Tunnel is still temporary perimeter infrastructure only.

## Mobile operator rule: background long-running processes

When operating from iPhone/Termius, do **not** keep Uvicorn and `cloudflared` attached to separate foreground SSH tabs. Mobile terminal suspension/termination can kill them and force the entire dogfood path to be rebuilt.

Preferred dogfood posture:

```text
one interactive SSH shell
+ WebAI Bridge in background
+ cloudflared in background
+ logs tailed on demand
```

Example pattern:

```bash
nohup <webai-host-command> > /tmp/webai-paid.log 2>&1 &
nohup cloudflared tunnel --url http://127.0.0.1:8080 > /tmp/webai-cloudflared.log 2>&1 &
```

Then inspect without owning extra terminal tabs:

```bash
pgrep -af 'uvicorn.*8080|cloudflared.*8080' || true
tail -n 30 /tmp/webai-paid.log
grep -o 'https://[^ ]*trycloudflare\.com' /tmp/webai-cloudflared.log | head -n1
```

This is a mobile dogfood convenience, not the production service manager. Production should use the normal systemd/Caddy deployment path.

## 1. Start the WebAI Bridge commercial gateway locally

The public tunnel should point only to the localhost-bound service:

```text
127.0.0.1:8080
```

Use the normal deployment identity/preflight requirements. Do not set `WEB_AI_ALLOW_INSECURE_HTTP=1` for the externally reachable process.

The public request must arrive at the commercial gateway as HTTPS through trusted proxy headers. If the commercial gateway returns HTTP 426 through the tunnel, treat that as a failed transport gate; do not weaken the HTTPS rule just to make the tunnel pass.

On desktop/server-oriented dogfood, foreground execution is acceptable. On iPhone/Termius, use the background pattern above.

## 2. Start a temporary Quick Tunnel

Foreground form:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

Mobile background form:

```bash
nohup cloudflared tunnel --url http://127.0.0.1:8080 > /tmp/webai-cloudflared.log 2>&1 &
sleep 6
grep -o 'https://[^ ]*trycloudflare\.com' /tmp/webai-cloudflared.log | head -n1
```

The command yields a random public URL similar to:

```text
https://random-words.trycloudflare.com
```

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

## Paid browser-handoff dogfood note

For the BUY_ONCE paid path, keep the same background-process rule but use the paid handoff launcher/state directory. The live paid acceptance must separately prove:

```text
real Stripe Checkout
→ live webhook 2xx
→ entitlement persisted
→ Safari checkout completion
→ one-time handoff
→ protected paid page
→ ephemeral BYOK
→ live provider response
```

Do not infer paid correctness from FREE acceptance alone.

## Boundaries

Quick Tunnel success does **not** establish:

- permanent DNS ownership;
- production TLS/reverse-proxy configuration;
- stable URL availability;
- production abuse/rate-limit posture;
- production service supervision;
- missed-event reconciliation.

It exists only to shorten the path to real external runtime evidence.
