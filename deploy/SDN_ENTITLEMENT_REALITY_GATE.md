# SDN → WebAI Bridge Entitlement Reality Gate

Status: `CODE GREEN / EXACT-REVISION EXTERNAL EVIDENCE REQUIRED`

This gate validates the trusted external entitlement contract introduced for Sales Distribution Network V1. It does not replace the existing fixed-domain deployment runbook; use `deploy/README.md` for host/systemd/Caddy deployment and keep exact deployment identity.

## Exact candidate

Deploy the exact commit shown by WebAI Bridge Draft PR #40, not a moving branch name. Record:

```bash
git rev-parse HEAD
```

The observed deployed SHA must equal the PR head being promoted.

## Secret authority

Create one strong service-to-service secret outside Git and place it in the existing private environment file:

```text
/etc/webai-bridge/webai-bridge.env
```

Add:

```text
WEB_AI_EXTERNAL_ENTITLEMENT_SERVICE_TOKEN=<32+ character high-entropy secret>
```

Use the same value only in the SDN deployment secret store. Never put it in URLs, query strings, screenshots, issues, PR text, shell history, or source files.

## Surface

The candidate commercial surface must expose over public HTTPS:

```text
POST /api/internal/entitlements/grant
POST /api/internal/entitlements/{external_ref}/handoff
POST /api/internal/entitlements/{external_ref}/revoke
```

All three require:

```text
Authorization: Bearer <service token>
```

Missing/unconfigured authority must fail closed.

## Acceptance order

Using an already-active BUY_ONCE WebAI package in the sandbox/dogfood deployment:

1. Grant with a fresh SDN order reference.
2. Repeat the identical grant. It must return the same external reference idempotently.
3. Attempt the same order reference with another buyer reference. It must be rejected.
4. Request browser handoff. The code must be returned in the response body only.
5. POST that handoff code through the existing `/checkout/activate/{package}` buyer path and prove browser access is authorized.
6. Revoke the external entitlement.
7. Prove existing entitlement/browser authority no longer authorizes the product according to WebAI's current revoke semantics.
8. Repeat revoke. It must be idempotent.
9. Replay the original grant after revoke. It must remain denied; revoked access cannot be resurrected.

## Cross-repo gate

After the standalone authority gate passes, run the SDN acceptance client against the exact deployed WebAI revision, then bind the same deployed pair into the Stripe sandbox chain:

```text
Referral
→ Checkout
→ verified Stripe webhook
→ Order
→ WebAI grant
→ browser-bound delivery
→ full refund
→ WebAI revoke
→ Commission/Ledger reversal
```

Partial refund is not automated in V1 and must stop at a Human Gate.

## Promotion rule

Unit/CI success is not external Reality evidence. Do not merge/promote solely because tests are green. Record exact WebAI SHA, exact SDN SHA, HTTPS endpoint identity, and observed acceptance results before closing the external gate.
