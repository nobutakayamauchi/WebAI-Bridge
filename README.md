# WebAI-Bridge

Create, distribute, monetize, and run Web AI packages with Knowledge, BYOK, entitlement enforcement, and cost-aware inference routing.

## Product boundary

WebAI Bridge is an **AI Package Platform** with four independent controls:

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
runtime/          Hosted runtime, buyer UI, auth, entitlement, Stripe checkout/webhook, Knowledge, ledger
deploy/           Dogfood and deterministic fixed-domain deployment tooling
cost-router/      Cost/payer boundary and pricing logic
package-schema/   Canonical AI Package contract
docs/             Product, security, distribution and /goal evidence
```

## Current Hosted state

`HOSTED V1 CANDIDATE / REAL FIXED-DOMAIN CHAIN PROVEN ON OLDER REVISION / EXACT-HEAD REVALIDATION REQUIRED`

The controlled Oracle/iPhone run proved the important real commercial chain on one exact revision:

```text
fixed-domain HTTPS
→ authenticated smartphone Creator Studio
→ second paid product direct publish
→ live Stripe payment
→ fixed-domain webhook entitlement
→ iPhone buyer handoff
→ ephemeral buyer BYOK
→ server-owned PACKAGE_TEXT Knowledge
→ provider response
→ revocation
→ same buyer immediately denied
```

That run deliberately fed its production-only failures back into PR #30. Therefore the older live evidence is not silently promoted to certify the newer branch head.

## Current buyer authority contract

The current challenger makes Stripe payment authority and browser possession separate:

```text
buyer /a/{slug}
→ /api/buy/{slug}
→ public Stripe client_reference_id
+ signed HttpOnly initiating-browser cookie
→ Stripe Payment Link
→ durable webhook entitlement
→ verified Checkout Session locator
+ matching initiating-browser proof
→ one-time POST-body handoff
→ signed entitlement cookie
```

Important invariants:

```text
PAYMENT LINK != VERIFIED PAYMENT
CHECKOUT SESSION LOCATOR != BROWSER AUTHORITY
BYOK CONNECTED != ACCESS AUTHORITY
```

A valid paid Checkout Session without the signed initiating-browser proof is denied. One-time `handoff_...` authority is never placed in handoff/activation URLs. Deterministic production rendering also disables raw Uvicorn access logging as defense in depth.

## Creator Studio

Authenticated Creator Studio can directly publish a validated Hosted/BYOK/PACKAGE_TEXT BUY_ONCE bundle:

```text
Package JSON + Instructions + Knowledge
→ private three-artifact install
→ Package JSON authority commit last
→ Knowledge digest verification
→ explicit activation
→ registry reload
→ buyer path /a/{slug}
```

Active package authority cannot be silently overwritten by a later Studio publish. The normal sale path exposed after publish is the WebAI buyer/browser-bound checkout route, not the raw Stripe Payment Link.

## Deployment profiles

The deterministic renderer keeps two production surfaces explicit:

```text
BUYER_ONLY_COMMERCIAL_V1
→ commercial_bound:app
→ Studio disabled
→ browser-bound Stripe checkout

CREATOR_STUDIO_COMMERCIAL_V1
→ commercial_handoff:app
→ creator-authenticated Studio/direct publish
→ browser-bound Stripe checkout
```

Both delegate the canonical paid runtime and share active-paid secret/environment preflight checks. Creator mode keeps mutable package authority under the private state directory rather than the read-only deployed Git tree.

## External Stripe acceptance

`runtime/stripe_external_acceptance.py` is a deployment/acceptance gate, not a process-liveness dependency. It verifies live Payment Link metadata/amount/currency/one-time/redirect bindings and the fixed-domain webhook/event contract. Stripe list APIs are paginated to completion and pagination anomalies fail closed.

## PACKAGE_TEXT Knowledge

Hosted first-class Knowledge is a private server artifact bound to Package JSON by SHA-256. Lexical retrieval handles Japanese/CJK and indexes ASCII `_`/`-` compounds as both full terms and meaningful components; this was added after a real `ORACLE_FIXED_DOMAIN_...` fixture exposed a component-retrieval blind spot.

## What is still not claimed

The repository does **not** yet claim generic production completion. Before the bounded Hosted v1 merge/release decision, the **latest exact PR head** still needs fixed-domain revalidation of:

- deterministic renderer + systemd preflight;
- public HTTPS and exact running revision;
- live Stripe remote contract;
- Creator/product authority integrity and active-overwrite refusal;
- browser-bound live buyer payment/handoff on iPhone Safari;
- no buyer authority in visible URLs/retained request evidence;
- ephemeral BYOK + PACKAGE_TEXT component retrieval + bounded provider response;
- revoke → immediate denial.

Portable runtime, portable Knowledge secrecy, purchased platform credits/wallets, creator-funded shared inference, sponsored/hybrid payer modes, full subscription automation, multi-worker BYOK, DRM, and OpenAI Plugin delivery are separate future scopes.

See `deploy/README.md` and `docs/GOAL_HOSTED_V1_PRODUCTION_STUDIO.md` for the exact acceptance and stop boundaries.

## Origin / evidence

The original dogfood evidence remains in `nobutakayamauchi/RS-AI-limit-development`, Issue #10 and Draft PR #11. This repository is now the product implementation source; the Limit Development repository remains an experimental evidence source.

## License

No license is granted yet. Package portability and code licensing will be decided deliberately rather than inferred from repository visibility.
