# Paid Hosted BYOK iPhone Dogfood Evidence — 2026-08-17

## Scope proven

Real external dogfood proved the bounded commercial shape:

```text
BUY_ONCE
+ HOSTED_ONLY
+ BYOK
+ Stripe Payment Link
+ server-side Stripe verification
+ one-time browser handoff
+ persistent buyer entitlement cookie
+ iPhone Safari
+ live OpenAI inference
```

This is dogfood evidence, not a production-readiness claim.

## Environment

- Host: Oracle Ubuntu 24.04
- Runtime: localhost Uvicorn on `127.0.0.1:8080`
- Public perimeter: temporary Cloudflare Quick Tunnel
- Package: `paid-dogfood-ai`
- Checkout amount: JPY 100 BUY_ONCE dogfood payment
- Inference payer: BYOK
- Model path: OpenAI provider / allowed package model
- Serving checkout after PR #18: `a49f9611a44749686de0c61ce0fc6a4647b0ca3f`
- Deployment preflight observed `PREFLIGHT_PASS`, `active_packages=1`, `active_paid_packages=1`, `validated_route_surface=commercial_handoff:app`, Stripe checkout verification configured, handoff TTL 600 seconds.

## Observed sequence

1. Unentitled Safari access to `/a/paid-dogfood-ai` was denied.
2. A real JPY 100 Stripe Checkout completed and was verified server-side.
3. Direct auto-fulfillment initially worked, but iOS exposed a browser-boundary defect: the entitlement cookie could land in an embedded/in-app browser context and normal Safari then appeared unpurchased.
4. The defect was converted into a one-time handoff design:
   - entitlement becomes ACTIVE only after verified payment;
   - a random handoff token is issued for 10 minutes;
   - only its SHA-256 digest is persisted;
   - the token is package/payment-bound and atomically one-time consumable;
   - normal Safari consumes it and receives the signed Secure HttpOnly entitlement cookie.
5. The verified paid Checkout Session was reused for handoff retesting to avoid charging an additional JPY 100. No payment truth was fabricated; Stripe still reported the original Checkout Session as `paid` and `complete` for the configured Payment Link.
6. iPhone Safari displayed the handoff page: `購入確認が完了しました` with `この端末でAIを使う`.
7. One activation consumed the handoff ticket and redirected to the paid AI.
8. Safari was fully closed and reopened. Direct access to `/a/paid-dogfood-ai` still succeeded, proving the buyer entitlement cookie survived Safari restart.
9. The buyer connected an OpenAI BYOK key. The UI changed to `API接続済み`; the raw API key field disappeared and only an opaque HttpOnly session remained browser-side.
10. A live paid chat request was sent from iPhone Safari and a provider response rendered successfully.

## Security gates observed

- No raw long-lived `webai_...` buyer access token was required by the buyer flow.
- Duplicate Checkout Session claim was rejected (`This Checkout Session has already been claimed`).
- Handoff token is short-lived, one-time, and digest-only at rest.
- Buyer entitlement authorization still resolves against server-side entitlement state; cookie possession is transport, not the authority database itself.
- BYOK key is not persisted as browser storage; after connection the server retains it only in short-lived process memory and the browser carries an opaque HttpOnly session identifier.
- Stripe secret key was configured as a restricted live key with read-only Checkout Sessions and Payment Links permissions for dogfood. A key accidentally pasted into chat during testing was treated as compromised and replaced before continuing.

## Failures that produced fixes

### Stripe API quota / provider 502
An early FREE/BYOK provider call surfaced OpenAI `insufficient_quota`; adding prepaid API credit resolved it. This was not a WebAI entitlement defect.

### Checkout replay
An ACTIVE payment could initially be replayed from another browser to mint another cookie. PR #16 changed Checkout fulfillment to single-claim and CI proved first claim succeeds while duplicate/revoked replay fails closed.

### iOS browser boundary
A successful Stripe redirect could set a buyer cookie in an embedded browser context that normal Safari did not share. PR #17 introduced the one-time browser handoff. PR #18 corrected Deployment Identity/preflight for the handoff dogfood route.

## Explicitly NOT claimed

This evidence does **not** prove:

- permanent production DNS/TLS;
- production-grade abuse/rate limiting or multi-worker coordination;
- Stripe webhook fulfillment/reconciliation;
- subscription auto-fulfillment;
- PLATFORM_CREDIT or creator-funded inference;
- creator wallet/budget allocation;
- live Knowledge/vector retrieval;
- portable runtime;
- Level 2 encryption or Level 3 signed activation;
- production uptime/SLOs;
- that Cloudflare Quick Tunnel is production infrastructure.

## Promotion criterion

The browser-handoff behavior may be promoted from a dogfood-only wrapper into the canonical commercial gateway only if the canonical route retains:

```text
verified Stripe payment
→ single Checkout claim
→ ACTIVE entitlement
→ short-lived one-time handoff ticket
→ Secure HttpOnly buyer cookie
→ server-side entitlement recheck on every protected request
→ ephemeral BYOK session
```

and the full test suite remains green.