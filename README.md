# WebAI-Bridge

Create, distribute, monetize, and run portable Web AI packages with Knowledge, BYOK, and cost-aware inference routing.

## Product boundary

WebAI Bridge is not only a GPT migration utility. It is an **AI Package Platform** with four independent controls:

1. **AI Package** — name, description, Instructions, Knowledge, model/routing policy.
2. **Access** — free, included allowance, paid access, buy-once, subscription, per-use.
3. **Inference payer** — BYOK, platform/user credit, creator-funded, sponsored, or hybrid.
4. **Delivery** — hosted URL, portable package, or both.

Hard rule:

```text
ACCESS PRICE != INFERENCE COST
NO PAYER RESOLUTION -> NO BUDGET AUTHORIZATION -> NO MODEL EXECUTION
```

## Repository structure

```text
creator-studio/   Smartphone creator surface
runtime/          Hosted runtime, buyer UI, auth, entitlement, Stripe handoff/webhook, Knowledge, ledger
cost-router/      Cost/payer boundary and pricing logic
package-schema/   Canonical AI Package contract
deploy/           Dogfood and fixed-domain deployment tooling
docs/             Product, security, distribution and /goal evidence
```

## Current hosted state

`HOSTED V1 CANDIDATE / LIVE DOGFOOD PROVEN / FIXED-DOMAIN RELEASE EVIDENCE PENDING`

The current Hosted path has already passed real-device dogfood for the important commercial chain:

```text
Stripe payment
→ durable webhook entitlement
→ one-time browser handoff
→ iPhone Safari
→ ephemeral buyer BYOK
→ server-owned PACKAGE_TEXT Knowledge
→ provider response
→ revocation
```

Creator Studio now supports authenticated direct publish of a validated three-artifact bundle:

```text
Package JSON + Instructions + Knowledge
→ authority-safe install
→ explicit activation
→ registry reload
→ buyer URL
```

The creator surface is fail-closed behind creator-only authentication when exposed publicly. Active package authority cannot be silently overwritten by a later Studio publish.

## What is still not claimed

The repository does **not** yet claim generic production completion.

Remaining external release evidence includes:

- fixed public hostname/DNS;
- stable HTTPS reverse proxy rather than Quick Tunnel dogfood;
- exact deployed revision + systemd preflight on that host;
- production secret-file permissions/logging review;
- one complete Creator Studio direct-publish cycle on the fixed-domain host;
- one buyer purchase/use/revoke cycle on that same deployed revision;
- final iPhone/Safari acceptance after the fixed-domain deployment.

Portable runtime, purchased platform credits/wallets, creator-funded shared inference, sponsored/hybrid payer modes, and OpenAI Plugin delivery are separate future scopes. They are not required to call the bounded Hosted/BYOK sale path usable.

## Deployment profiles

The deterministic renderer keeps two surfaces separate:

```text
buyer-only commercial host
→ commercial:app
→ Studio disabled

creator-managed commercial host
→ commercial_handoff:app
→ creator-authenticated Studio/direct publish
```

Creator mode is opt-in. It does not place creator, Stripe, entitlement, or provider secret values in generated deployment artifacts.

See `deploy/README.md` and the current `/goal` records under `docs/` for the exact external acceptance boundary.

## Origin / evidence

The original dogfood evidence remains in `nobutakayamauchi/RS-AI-limit-development`, Issue #10 and Draft PR #11. This repository is now the product implementation source; the Limit Development repository remains the experimental evidence source.

## License

No license is granted yet. Package portability and code licensing will be decided deliberately rather than inferred from repository visibility.
