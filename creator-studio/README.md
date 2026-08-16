# Creator Studio — thin v0

Status: `BOUNDED_CHALLENGER / EXPORT_ONLY / READINESS_AWARE`

Creator Studio replaces hand-edited AI Package JSON with a smartphone-oriented form. It deliberately does **not** become a full admin SaaS in v0.

## Run

```bash
export WEB_AI_STUDIO_ENABLED=1
cd runtime
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `/studio`. The Studio is disabled by default.

## What v0 does

1. AI name / slug / description
2. Instructions
3. hosted Knowledge server-binding reference
4. access intent + JPY price
5. explicit access `charge_basis`
6. Stripe Payment Link metadata: `SELF_SETUP` / `ASSISTED_SETUP`
7. inference payer: BYOK / bounded PLATFORM_CREDIT
8. model policy from the current pricing registry
9. four distribution-protection presets
10. semantic/economic/distribution validation
11. machine-readable readiness
12. Package JSON + Instructions export

Validation is read/compute only. It does not publish, mutate the runtime registry, call an AI provider, charge a card, or create an entitlement.

## Three different states

A central DA finding is now a hard distinction:

```text
CONFIG_VALID != READY_TO_RUN != READY_TO_SELL
```

`CONFIG PASS` means the package contract is internally valid enough to export as a draft. It does **not** mean the package can be sold or executed safely.

The validation result therefore reports:

- configuration state;
- runtime state;
- commercial state;
- explicit blockers.

Creator Studio always exports `status = draft`. A draft is not runnable merely because an operator copies it into the runtime directory.

## Checkout boundary

Paid access may reference a creator-owned Stripe Payment Link.

- `SELF_SETUP`: creator supplies an HTTPS checkout URL and explicitly attests that product, amount, currency and billing basis match the package configuration.
- `ASSISTED_SETUP`: checkout may remain pending while setup support helps complete it.

Hard rules:

```text
PAYMENT LINK != VERIFIED ENTITLEMENT
CHECKOUT URL != VERIFIED PRICE BINDING
```

V0 does not automatically inspect Stripe product/price state. Self-setup binding is creator-attested; assisted setup remains manual-review/pending. Paid hosted execution is fail-closed until verified entitlement exists.

## Access price basis

Specific modes have an explicit basis:

- `BUY_ONCE` -> `ONE_TIME`
- `SUBSCRIPTION` -> `MONTHLY`
- `PER_USE` -> `PER_RUN`
- `FREE` -> `FREE`

Generic `PAID` and `ALLOWANCE_THEN_PAID` remain useful draft intent, but their charge basis is explicitly `UNSPECIFIED_*` and therefore a commercial-readiness blocker.

## Hosted BYOK

Hosted BYOK is ephemeral, not invisible:

```text
NOT PERSISTED != NEVER SEEN BY SERVER
```

The key is not intentionally persisted by this runtime, but each hosted request sends it through the WebAI Bridge server so the server can call the provider while keeping creator Instructions/Knowledge server-side.

## Four protection levels

```text
LEVEL 1 — LICENSE ONLY
portable contract intent
no technical anti-copy guarantee
portable runtime NOT IMPLEMENTED

LEVEL 2 — BUYER PASSPHRASE
planned portable encryption + buyer passphrase
CONTRACT_ONLY
portable runtime NOT IMPLEMENTED

LEVEL 3 — DUAL CONTROL ACTIVATION
planned buyer passphrase + seller/WebAI Bridge signed activation
seat intent
CONTRACT_ONLY
portable runtime NOT IMPLEMENTED

LEVEL 4 — HOSTED ONLY
current hosted runtime boundary
portable package is not handed out
paid entitlement still NOT IMPLEMENTED
```

Levels 1-3 require explicit creator acknowledgement of copy/inspection/modification risk. Current Studio exports contract metadata only; it does **not** generate a runnable portable ZIP.

Actual buyer passphrases, seller signing keys, provider secrets and Stripe secrets must never be written into Package JSON.

## Hosted safety policy

The hosted runtime prepends `runtime/safety_kernel.md` before creator package Instructions.

This is classified honestly as:

`PROMPT_POLICY_PLUS_PROVIDER_BASELINE`

It is not claimed to be perfect moderation, DRM, or an unremovable safeguard after portable/modifiable code leaves the hosted boundary.

## Cost/runtime limits surfaced by DA

- total history characters are bounded, not only message count;
- runtime package documents are validated against the canonical schema;
- `instructions_file` is constrained to `apps/{slug}.instructions.md`;
- runtime diagnostics are opt-in;
- observed provider cost is recorded even when it exceeds a pre-call reservation;
- current in-memory IP rate limiting is dogfood-only, not a production identity/quota system;
- creator/user wallet allocation and reservation-id crash recovery remain later production gates.

## Non-goals in thin v0

- custom card handling
- purchased user wallet
- automatic Stripe product/price verification
- webhook entitlement enforcement
- creator payouts
- persistent BYOK secret storage
- runnable portable ZIP generation
- portable Knowledge packaging
- package encryption/passphrase enrollment
- activation/signing/revocation infrastructure
- guaranteed DRM
- production deployment claim

## Evidence

See:
- `docs/GOAL_CREATOR_STUDIO_V0.md`
- `docs/DA_COUNTER_DA_CREATOR_STUDIO_V0.md`
- `docs/BILLING_AND_CHECKOUT.md`
- `docs/DISTRIBUTION_SECURITY.md`
