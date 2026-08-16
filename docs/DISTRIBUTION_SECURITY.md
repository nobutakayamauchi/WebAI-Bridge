# Distribution Security / Copy-Control Boundary

Date: 2026-08-16
Status: `FOUR_LEVEL_CONTRACT_FROZEN / HOSTED_RUNTIME_ONLY`

## Core finding

A portable AI Package delivered into a buyer-controlled environment cannot honestly be promised as perfectly non-copyable, non-inspectable or non-modifiable.

A second DA finding is equally important: **WebAI Bridge does not yet have a runnable portable package/ZIP runtime at all.** Current portable Levels 1-3 are product contracts and future implementation targets, not current execution claims.

## Hard invariants

```text
DELIVERED PACKAGE != TECHNICALLY NON-COPYABLE PACKAGE
PORTABLE != SECRET
PORTABLE != SAFETY ENFORCED
LICENSE TERMS != TECHNICAL COPY CONTROL
BUYER PASSPHRASE != PERFECT DRM
ACTIVATION != PERFECT DRM
PORTABLE INTENT != PORTABLE RUNTIME
SERVER SECRET/ENV BINDING != PORTABLE RESOURCE
```

## Level 1 — License only

Contract: `LEVEL_1_LICENSE_ONLY`

Target:
- buyer receives a portable package;
- redistribution may be prohibited by terms/license;
- no technical copy-protection claim;
- buyer can eventually use supported BYOK provider/model paths.

Current state:
- `protection_implementation = AVAILABLE` means the selected protection is intentionally **no technical protection beyond terms**;
- `runtime_implementation = NOT_IMPLEMENTED` because WebAI Bridge does not yet generate a runnable portable artifact;
- `copy_protection_guarantee = NOT_GUARANTEED`.

Therefore Level 1 is **not currently a sellable runnable ZIP** merely because the contract validates.

## Level 2 — Buyer passphrase

Contract: `LEVEL_2_BUYER_PASSPHRASE`

Target:
- portable package encryption;
- buyer passphrase enrolled outside package metadata;
- buyer secret required for normal opening/execution.

Current state:
- `protection_implementation = CONTRACT_ONLY`;
- `runtime_implementation = NOT_IMPLEMENTED`;
- `copy_protection_guarantee = PLANNED_ENCRYPTION`.

No actual buyer passphrase is stored in Package JSON.

## Level 3 — Dual-control activation

Contract: `LEVEL_3_DUAL_CONTROL_ACTIVATION`

Target:

```text
BUYER PASSPHRASE
+
SELLER / WEBAI BRIDGE SIGNED ACTIVATION
=
NORMAL UNLOCK
```

The seller factor is not a raw seller password handed to the buyer. The future design is a seller/WebAI Bridge controlled signing/entitlement boundary.

Target properties may include:
- account-bound entitlement;
- seat/concurrency cap;
- signed manifest;
- bounded offline lease;
- renewal/revocation;
- audit evidence;
- buy-once service-exit path.

Current state:
- `protection_implementation = CONTRACT_ONLY`;
- `runtime_implementation = NOT_IMPLEMENTED`;
- `copy_protection_guarantee = PLANNED_ENTITLEMENT`.

No buyer passphrase or seller signing key is Package JSON data.

## Level 4 — Hosted only

Contract: `LEVEL_4_HOSTED_ONLY`

Current hosted runtime exists.

Current strengths:
- creator Instructions remain server-side;
- hosted Knowledge can remain server-side;
- provider/platform credentials can remain server-side;
- hosted Safety policy can be prepended by the server;
- package contents are not handed to the buyer as a runnable portable bundle.

Important DA correction:
- paid buyer entitlement is **not implemented yet**;
- therefore Level 4 is the strongest current secrecy/runtime boundary, **not** a claim that paid access control is already complete;
- paid hosted packages fail closed in the current runtime until entitlement enforcement exists.

Hosted Safety is currently classified as `PROMPT_POLICY_PLUS_PROVIDER_BASELINE`. It is not claimed as perfect moderation.

## BYOK security boundary

Hosted BYOK does not persist the key intentionally, but the key passes through the WebAI Bridge server for each provider request.

```text
NOT PERSISTED != NEVER SEEN BY SERVER
```

A future truly buyer-direct provider path is naturally aligned with portable execution, but that portable runtime does not yet exist.

## Portable Knowledge / payer boundary

Current Knowledge uses a server-side vector-store environment binding. Current PLATFORM_CREDIT also depends on server-side credential/budget identity.

Those cannot simply be copied into a portable package and assumed to work.

Portable readiness therefore explicitly blocks:
- server Knowledge binding without a portable packaging/remote-resource policy;
- server-funded payer configuration without a portable authorization path;
- all Levels 1-3 until a real portable runtime artifact exists.

## Mandatory acknowledgement

Levels 1-3 require creator acknowledgement that:
- package contents may become inspectable/copyable/modifiable;
- no perfect anti-copy guarantee exists;
- the current thin v0 does not generate a runnable portable package.

## Buy-once

All four combinations remain valid **product targets**:

```text
BUY_ONCE + LEVEL_1_LICENSE_ONLY
BUY_ONCE + LEVEL_2_BUYER_PASSPHRASE
BUY_ONCE + LEVEL_3_DUAL_CONTROL_ACTIVATION
BUY_ONCE + LEVEL_4_HOSTED_ONLY
```

But current readiness differs:
- Levels 1-3: blocked by missing portable runtime, plus any protection/resource blockers;
- Level 4 paid: blocked by missing hosted buyer entitlement.

So `BUY_ONCE` is a frozen commercial contract, not a statement that delivery is already implemented.

## Level 3 service-exit obligation

Before Level 3 buy-once becomes sellable, define survivability if seller/WebAI Bridge disappears. Candidate mechanisms:
- signed long-lived exit entitlement;
- verified shutdown release;
- escrow/recovery mechanism;
- documented migration path.

No such mechanism is currently claimed.

## Implementation order

1. Portable runtime/artifact format and acceptance test.
2. Portable provider/BYOK configuration path.
3. Portable Knowledge packaging or explicit remote-resource contract.
4. Level 1 delivery/license packaging.
5. Package encryption + secret-free manifest.
6. Buyer passphrase enrollment.
7. Seller/WebAI Bridge signing + entitlement.
8. Seat/concurrency + bounded offline lease if justified.
9. Revocation/audit.
10. Buy-once exit/survivability mechanism.
11. Device binding only if real abuse evidence justifies its UX/privacy cost.

## Product message

For creators:

> Level 4 is the current hosted runtime. Levels 1-3 define how portable distribution should eventually be protected; they are not runnable portable products yet.

For buyers:

> Portable means freedom when that runtime exists. It will never be advertised as impossible to inspect or copy.
