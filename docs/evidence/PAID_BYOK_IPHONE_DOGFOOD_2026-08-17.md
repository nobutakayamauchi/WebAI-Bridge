# Paid Hosted BYOK iPhone Dogfood Evidence — 2026-08-17

## Scope proven

Real external dogfood proved the bounded commercial shape:

```text
BUY_ONCE
+ HOSTED_ONLY
+ BYOK
+ real Stripe Payment Link
+ live Stripe webhook fulfillment
+ persistent server-side entitlement
+ one-time browser handoff
+ signed Secure HttpOnly buyer cookie
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
- Canonical serving revision observed during the final pass: `cb4e830783377bad0be6cc16edc6f18416fdcb62`
- Runtime profile: `PAID_BUY_ONCE_BROWSER_HANDOFF_DOGFOOD`
- Final dogfood state directory: `/home/ubuntu/.local/state/webai-bridge-paid-webhook-dogfood-v3`
- Deployment preflight observed `active_packages=1`, `active_paid_packages=1`, `validated_route_surface=commercial_handoff:app`, Stripe checkout verification configured, handoff TTL 600 seconds.

## Final observed end-to-end sequence

1. A real JPY 100 Stripe Checkout Session completed in live mode for `paid-dogfood-ai`.
2. Stripe emitted `checkout.session.completed`.
3. The live webhook was delivered through the temporary Cloudflare HTTPS tunnel to `/webhooks/stripe`.
4. WebAI Bridge returned `200 OK` for the final webhook delivery.
5. The entitlement database then contained exactly one entitlement row: `{'entitlements': 1}`.
6. Safari opened `/checkout/complete/paid-dogfood-ai?...` using the verified paid Checkout Session.
7. WebAI Bridge displayed `購入確認が完了しました` and issued a short-lived one-time browser handoff.
8. The buyer pressed `この端末でAIを使う` once.
9. The handoff was consumed and Safari reached the protected paid AI page `WebAI Bridge Paid Dogfood`.
10. The buyer entered a fresh OpenAI BYOK key directly into the Safari UI and pressed `APIを接続`.
11. The UI changed to `API接続済み`; the key input disappeared and the browser retained only an opaque HttpOnly session identifier.
12. A live message was sent from iPhone Safari (`テスト、簡単にかえして`).
13. The provider response rendered successfully (`テスト確認しました。`).

The final proven path was therefore:

```text
real buyer payment
→ Stripe live Checkout
→ checkout.session.completed
→ Cloudflare HTTPS
→ WebAI Bridge webhook signature verification
→ Payment Link binding verification
→ entitlement fulfillment
→ Safari checkout completion verification
→ one-time browser handoff
→ signed buyer entitlement cookie
→ paid AI page
→ ephemeral BYOK session
→ OpenAI
→ live response rendered on iPhone Safari
```

## Security gates observed

- No raw long-lived buyer access token was required by the normal buyer flow.
- Stripe webhook signature validation was active; a local correctly signed probe returned `200 OK` before the live delivery was retried.
- Payment Link URL binding was fail-closed.
- Checkout claim and webhook event processing are persisted separately from entitlement lifecycle.
- Buyer authorization still resolves against server-side entitlement state; the signed cookie is transport, not the authority database itself.
- Handoff token is short-lived, one-time, package/payment-bound, and digest-only at rest.
- BYOK key is not persisted in browser storage. After connection, the server retains it only in short-lived process memory and the browser carries an opaque HttpOnly session identifier.
- The Stripe server key used by WebAI Bridge was a fresh restricted live key with read-only Checkout Sessions and Payment Links permissions.
- The final evidence output did not intentionally print the Stripe server key, OpenAI key, buyer cookie, or entitlement bearer material.

## Failures that produced findings

### Provider quota
An earlier FREE/BYOK provider call surfaced OpenAI `insufficient_quota`; adding prepaid API credit resolved it. This was not a WebAI entitlement defect.

### iOS browser boundary
A direct payment redirect can land inside an app/in-app browser context that normal Safari does not share. The one-time browser handoff makes the buyer explicitly finish activation in Safari before minting the entitlement cookie there.

### Webhook resend key / CLI friction
Stripe CLI resend required capabilities that were awkward to manage from a phone. Dashboard `再送` was the lower-friction live retry path for this dogfood.

### Payment Link URL binding mismatch
The live webhook initially failed with:

```text
Stripe Payment Link URL binding mismatch
```

The configured Payment Link URL contained a one-character typo (`pXD` instead of `bXD`). This was correctly rejected by fail-closed binding validation. A fresh `v3` state directory was created with the correct canonical Payment Link URL; the next live resend returned `200 OK`.

### Mobile multi-terminal failure mode
Keeping Uvicorn, Cloudflare Quick Tunnel, and an operator shell foregrounded in separate Termius tabs was operationally fragile on iPhone. Termius termination repeatedly killed foreground processes and forced rework.

The successful final pass switched both long-running processes to background execution with `nohup`, leaving one interactive SSH shell for inspection. This is now the recommended mobile dogfood posture.

## Explicitly NOT claimed

This evidence does **not** prove:

- permanent production DNS/TLS;
- stable tunnel URL availability;
- production-grade abuse/rate limiting or multi-worker coordination;
- webhook reconciliation for missed/late events beyond the tested live resend/idempotent processing path;
- subscription auto-fulfillment;
- PLATFORM_CREDIT or creator-funded inference;
- creator wallet/budget allocation;
- live Knowledge/vector retrieval;
- portable runtime;
- Level 2 encryption or Level 3 signed activation;
- production uptime/SLOs;
- that Cloudflare Quick Tunnel is production infrastructure.

## Promotion criterion

The paid browser flow may be promoted only if the canonical commercial gateway retains:

```text
verified Stripe payment
→ verified Stripe webhook
→ idempotent entitlement fulfillment
→ single Checkout claim
→ short-lived one-time handoff ticket
→ Secure HttpOnly buyer cookie
→ server-side entitlement recheck on every protected request
→ ephemeral BYOK session
```

and the full test suite remains green.
