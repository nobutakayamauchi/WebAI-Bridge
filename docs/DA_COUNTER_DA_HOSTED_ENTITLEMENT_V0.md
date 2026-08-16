# DA / Counter-DA — Hosted Entitlement v0

Date: 2026-08-16
Status: `ACTIVE_REVIEW / BOUNDED_COMMERCIAL_GATE`

## Protected outcome

A creator can manually sell the first hosted WebAI Bridge package without accidentally exposing a universal paid URL or inheriting uncontrolled buyer inference cost.

Frozen first commercial shape:

```text
BUY_ONCE or SUBSCRIPTION
+ LEVEL_4_HOSTED_ONLY
+ BYOK only
+ creator-owned Stripe Payment Link
+ manual payment verification
+ buyer bearer entitlement
```

## Findings that survived Counter-DA and were fixed

### F1 — Paid URL alone was not entitlement

A permanent shared URL could be copied and bypass the access price.

Fix:
- paid config/chat requires a high-entropy buyer entitlement;
- one bearer entitlement is issued only after operator payment verification;
- token is package-bound.

Invariant:

```text
PAID URL != BUYER ENTITLEMENT
```

### F2 — Storing plaintext bearer tokens would turn a DB leak into immediate access

Fix:
- only SHA-256 token digest is stored;
- plaintext token is returned only at issuance;
- token list exposes only a short digest prefix and non-secret metadata.

Limit:
A bearer token possessed by a buyer can still be voluntarily shared. This v0 is not identity-bound authentication or DRM.

### F3 — Operator could lose the plaintext token and then be unable to revoke a leaked entitlement

Fix:
- every entitlement requires a non-secret `payment_ref`;
- operator can revoke by `(package_id, payment_ref)` without retaining the plaintext bearer token.

### F4 — Duplicate operator issuance could create multiple active tokens for one payment

Fix:
- one active entitlement per `(package_id, payment_ref)`;
- reissue is allowed after explicit revocation.

### F5 — Subscription could accidentally become permanent

Fix:
- `SUBSCRIPTION` issuance requires positive `--days`;
- `BUY_ONCE` deliberately forbids `--days` so its semantics are not confused with a subscription lease.

### F6 — Operator could issue access without affirming payment verification

Fix:
- CLI requires explicit `--payment-verified`;
- payment verification remains human/manual and is not inferred from redirect/opened checkout.

Invariant:

```text
CHECKOUT OPENED != PAYMENT VERIFIED
```

### F7 — Paid hosted + PLATFORM_CREDIT could recreate uncontrolled subsidy before per-user allocation exists

Fix:
- first paid hosted path is BYOK-only;
- commercial activation and runtime both reject shared/platform-funded payer combinations.

Invariant:

```text
PAID HOSTED V0 + SHARED SUBSIDY = BLOCKED
```

### F8 — Root-mounting the core app left a future route-order/path-normalization bypass surface

The first wrapper mounted `core.app` at `/` after entitlement routes. Even if current routing preferred the explicit routes, commercial authority should not depend on route ordering forever.

Fix:
- no root mount of `core.app`;
- commercial entrypoint explicitly exposes each intended route;
- paid config/chat are always wrapped by entitlement authority.

### F9 — URL fragment cleanup crashed in the real browser

The paid UI used `const history = []`, shadowing the browser History API. `history.replaceState(...)` therefore targeted the array instead of `window.history`.

Fix:
- conversation state renamed to `conversationHistory`;
- fragment removal calls `window.history.replaceState(...)`;
- static regression test pins this behavior.

### F10 — Protecting only API endpoints with HTTPS was insufficient

If `/a/package#access=...` itself loads over HTTP, an active network attacker can replace the page JavaScript and steal the bearer token and BYOK credential before later HTTPS API calls matter.

Fix:
- paid buyer page itself requires secure transport;
- paid config and all commercial chat require secure transport;
- insecure HTTP is allowed only with explicit `WEB_AI_ALLOW_INSECURE_HTTP=1` for local tests/development;
- production service example trusts forwarded scheme headers only from localhost proxy.

Invariant:

```text
SECRET-HANDLING PAGE OVER HTTP != SAFE
```

### F11 — Paid buyer page could be cached/framed or given unnecessary exfiltration surfaces

Fix on paid buyer page:
- `Cache-Control: no-store`;
- `Referrer-Policy: no-referrer`;
- `X-Frame-Options: DENY`;
- `X-Content-Type-Options: nosniff`;
- restrictive Permissions Policy;
- CSP blocks external/default resources and limits network connections to same-origin.

This remains browser hardening, not a claim of perfect client security.

### F12 — Studio still said hosted entitlement was entirely unimplemented after the manual gateway existed

Fix:
- commercial entrypoint adapts Studio readiness only for the narrow supported shape;
- BUY_ONCE/SUBSCRIPTION + Hosted + BYOK-only becomes `DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION`;
- Studio export remains draft and `commercial_enforcement=NOT_IMPLEMENTED` until explicit operator activation;
- portable/subsidized/other paid modes are not upgraded.

Invariant:

```text
AVAILABLE MANUAL ACTIVATION PATH != SILENT AUTO-ACTIVATION
```

## Counter-DA: real concerns deliberately deferred

### D1 — Bearer token sharing

A buyer can share their token. Solving this properly requires authenticated identity/account binding or another stronger authority model.

Decision: explicit v0 limitation. Do not add invasive device fingerprinting merely to create the appearance of DRM.

### D2 — Automated Stripe verification

Current operator verifies payment manually. Webhook/event verification will reduce labor and race/error risk later.

Decision: defer until live sales justify it. Manual verification is bounded and auditable through `payment_ref`.

### D3 — Subscription renewal lifecycle

Current subscription issuance is a bounded expiry token. Renewal requires operator reissue/renewal workflow.

Decision: acceptable for first manual sales; automated recurring entitlement lifecycle belongs with Stripe webhook/account work.

### D4 — Distributed rate limiting / authenticated abuse controls

Current rate limiting is in-process/IP-oriented and not a production distributed abuse system.

Decision: deployment/production gate. Bearer entropy is not a substitute for abuse controls.

### D5 — Reverse-proxy logging correctness

Code and docs prohibit intentional logging of `X-WebAI-Entitlement` and `X-Provider-API-Key`, but actual proxy configuration must be observed on the deployed host.

Decision: deployment evidence gate. No public deployment claim before inspection.

### D6 — Live provider / live Stripe / iPhone

Fake-provider CI proves authority flow only. It does not prove provider API compatibility, Stripe reality, Safari behavior or deployed TLS/proxy behavior.

Decision: separate runtime evidence gates.

## Merge gate

PR may merge when:
- entitlement bypass tests are green;
- payment-bound issuance/revocation tests are green;
- subscription/buy-once semantics are green;
- paid subsidy bypass is green;
- browser fragment regression is green;
- no core root-mount bypass surface remains;
- HTTPS fail-closed test is green;
- commercial Studio adapter tests are green;
- main is not ahead;
- PR is mergeable.

Merge does **not** mean production-ready or deployed.
