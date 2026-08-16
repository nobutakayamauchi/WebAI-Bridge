# Paid Hosted BYOK External Dogfood Evidence — 2026-08-17

## Scope

This record captures the external iPhone dogfood of WebAI Bridge's bounded paid hosted shape:

```text
BUY_ONCE
+ HOSTED_ONLY
+ BYOK
+ Stripe Payment Link
+ server-side Stripe verification
+ one-time browser handoff
+ persistent signed HttpOnly buyer cookie
```

This is evidence of a dogfood gate, not a production-readiness claim.

## Environment observed

- Client: iPhone Safari over mobile network.
- Host: Oracle Ubuntu 24.04.4 LTS.
- Runtime bound to `127.0.0.1:8080`.
- Public HTTPS: temporary Cloudflare Quick Tunnel (`trycloudflare.com`).
- Paid package: `paid-dogfood-ai`.
- Access mode: `BUY_ONCE`.
- Delivery mode: `HOSTED_ONLY`.
- Inference payer: `BYOK`.
- Model path exercised: OpenAI through the buyer's API account.

The Quick Tunnel URL was temporary test infrastructure and is not a production domain.

## Real payment evidence

A live Stripe Payment Link for JPY 100 was used. The retrieved Checkout Session was observed as:

- `livemode=true`
- `status=complete`
- `payment_status=paid`
- `amount_total=100`
- `currency=jpy`
- metadata bound to `paid-dogfood-ai`
- access mode `BUY_ONCE`
- exact Payment Link ID binding verified server-side

The payment created a real PaymentIntent. Secret API credentials are deliberately not recorded here.

## Gates observed

### 1. Unpaid denial — PASS

Opening `/a/paid-dogfood-ai` without entitlement produced the buyer-access denial surface rather than the paid AI.

### 2. Automatic checkout verification — PASS

A real completed Stripe Checkout Session was submitted to the WebAI Bridge completion route. Server-side checks accepted the paid/complete session, amount, currency, package metadata, PaymentIntent, and exact Payment Link binding.

### 3. Duplicate Checkout claim — PASS

The first claim succeeded. Re-opening the same Checkout Session returned:

`This Checkout Session has already been claimed`

No second buyer authority was issued.

### 4. Cross-browser handoff — PASS

Dogfood exposed that an entitlement cookie created inside the payment browser context did not necessarily exist in normal Safari. The flow was changed to:

```text
verified Stripe payment
→ entitlement ACTIVE
→ short-lived one-time handoff ticket
→ handoff page
→ Safari opens the handoff page
→ explicit "use on this device" activation
→ signed HttpOnly entitlement cookie
→ paid AI
```

The handoff page was observed on iPhone and activation successfully opened the paid AI in Safari.

### 5. Handoff replay protection — PASS in automated tests

The handoff ticket is package/payment-bound, persisted only as a digest, single-use, and time-limited. Automated tests cover wrong-package use, replay, expiry, and revoked entitlement behavior.

### 6. Safari restart persistence — PASS

Safari was terminated and reopened. Navigating directly to `/a/paid-dogfood-ai` still opened the paid AI, proving the transferred buyer cookie survived the browser restart.

### 7. BYOK ephemeral session — PASS

The buyer entered an OpenAI API key into the paid UI and selected `APIを接続`. The UI reported `API接続済み`. The key itself was not retained in the browser after connection; the browser held only the opaque HttpOnly BYOK session identifier while the provider key remained in server process memory for the bounded session TTL.

### 8. Live paid chat — PASS

From the paid Safari session, the buyer sent:

`テストです。短く返答してください`

The paid AI returned a successful short response. This proves the external path through buyer entitlement, BYOK session, WebAI Bridge and the live provider returned a rendered answer on iPhone Safari.

## Security findings discovered during dogfood

The live test found and caused fixes for all of the following:

1. Raw buyer bearer-token copy/paste was unacceptable as the default buyer flow.
2. A Checkout Session needed exact Payment Link binding, not merely paid/amount metadata.
3. A revoked payment must not be able to resurrect entitlement by replaying its Checkout Session.
4. An ACTIVE Checkout Session must not be claimable again by a second browser.
5. iOS payment-browser cookies cannot be assumed to transfer into normal Safari.
6. Browser handoff therefore requires a separate short-lived one-time transfer authority.
7. Deployment preflight must identify the actual route surface; code existence is not deployment identity.

## Explicitly not claimed

This evidence does **not** establish:

- production domain or production TLS deployment;
- production-grade proxy/multi-worker rate limiting;
- Stripe webhook fulfillment/reconciliation;
- account login or cross-device recovery beyond the bounded handoff mechanism;
- PLATFORM_CREDIT or creator-funded inference;
- subscription auto-fulfillment;
- portable runtime;
- Knowledge/vector-store live retrieval;
- Level 2 encryption or Level 3 signed portable activation;
- full production abuse posture.

The proven commercial shape remains intentionally bounded to `BUY_ONCE + HOSTED_ONLY + BYOK`.
