# Distribution Security / Copy-Control Boundary

Date: 2026-08-16
Status: `FOUR_LEVEL_CONTRACT_FROZEN / ENFORCEMENT_PARTIAL`

## Finding

A portable AI Package delivered as a ZIP/file bundle can be copied after delivery. If the recipient controls the runtime and receives the package contents, WebAI Bridge cannot honestly claim perfect technical prevention of copying, inspection, modification, or Safety Kernel removal.

This is not a billing bug. It is a distribution-authority boundary.

## Hard invariants

```text
DELIVERED PACKAGE != TECHNICALLY NON-COPYABLE PACKAGE
PORTABLE != SECRET
PORTABLE != SAFETY ENFORCED
LICENSE TERMS != TECHNICAL COPY CONTROL
BUYER PASSPHRASE != PERFECT DRM
ACTIVATION != PERFECT DRM
```

No UI, package metadata, sales text, or creator warning may imply otherwise.

## Creator-facing protection levels

Creator Studio exposes one simple four-level choice. The levels are an operational protection posture, not a promise that local software can be made impossible to inspect or copy.

### Level 1 — License only

Contract value: `LEVEL_1_LICENSE_ONLY`

The buyer receives a portable package.

Properties:
- redistribution can be prohibited by license/terms;
- no buyer passphrase requirement;
- no seller activation requirement;
- buyer may use their own supported provider/model/API key;
- technical copy prevention is explicitly `NOT_GUARANTEED`.

V0 implementation: `AVAILABLE` as export/licensing intent.

Best fit:
- inexpensive packages;
- educational/open packages;
- creators who accept copy risk;
- packages whose value comes from updates/support rather than secrecy.

### Level 2 — Encrypted + buyer passphrase

Contract value: `LEVEL_2_BUYER_PASSPHRASE`

Target behavior:
- portable package is encrypted;
- buyer enrolls/provides a passphrase outside the exported package metadata;
- normal package opening/execution requires that buyer secret;
- seller secret is not required.

Security value:
- raises the barrier against casual copying;
- does not stop a buyer from deliberately sharing both package and passphrase;
- once content is decrypted for execution, a sufficiently capable recipient may still inspect memory/runtime or alter the software.

V0 implementation: `CONTRACT_ONLY / NOT_IMPLEMENTED`.

The Package JSON must never contain the buyer's actual passphrase.

### Level 3 — Buyer passphrase + seller/WebAI Bridge activation

Contract value: `LEVEL_3_DUAL_CONTROL_ACTIVATION`

Target behavior:

```text
BUYER SECRET
+
SELLER / WEBAI BRIDGE SIGNED ACTIVATION
=
NORMAL UNLOCK / EXECUTION
```

The seller side is **not** a raw password handed to the buyer. The intended design is a signed/server-verifiable activation or entitlement state retained under seller/WebAI Bridge control.

Target properties:
- buyer passphrase;
- seller/WebAI Bridge signed activation;
- account/license-bound entitlement;
- seat limit;
- optional concurrency limit;
- signed package/manifest;
- optional bounded offline lease;
- entitlement renewal/revocation;
- audit evidence.

Important limit:
If the buyer controls and can modify the runtime/source, activation remains a best-effort barrier rather than an absolute anti-copy guarantee. Stronger enforcement requires retaining a meaningful execution or secret boundary server-side.

V0 implementation: `CONTRACT_ONLY / NOT_IMPLEMENTED`.

The Package JSON must never contain the buyer passphrase, seller signing key, Stripe secret, or any equivalent secret material.

### Level 4 — Hosted only

Contract value: `LEVEL_4_HOSTED_ONLY`

The package executes on a WebAI Bridge controlled runtime and is not handed to the buyer as a portable package.

Properties:
- Instructions/Knowledge can remain server-side;
- Entitlement can be enforced server-side;
- Safety Kernel can be enforced server-side;
- provider/API credentials can remain server-side or be supplied as bounded BYOK at runtime;
- strongest current protection against casual package copying and secret extraction.

V0 implementation: `AVAILABLE` as the hosted boundary contract.

Recommended for:
- high-value proprietary Instructions;
- private/licensed Knowledge;
- sensitive workflows;
- creators who require strong entitlement enforcement;
- packages where Safety Kernel enforcement is a hard requirement.

## Protection-level mapping

```text
LEVEL 1
mode                        = PORTABLE_LICENSE
portable_protection         = LICENSE_ONLY
buyer_passphrase_required   = false
seller_activation_required  = false
seat_limit                  = 0
protection_implementation   = AVAILABLE
copy_protection_guarantee   = NOT_GUARANTEED

LEVEL 2
mode                        = PORTABLE_LICENSE
portable_protection         = BUYER_PASSPHRASE
buyer_passphrase_required   = true
seller_activation_required  = false
seat_limit                  = 0
protection_implementation   = CONTRACT_ONLY
copy_protection_guarantee   = PLANNED_ENCRYPTION

LEVEL 3
mode                        = PORTABLE_LICENSE
portable_protection         = ACTIVATION_REQUIRED
buyer_passphrase_required   = true
seller_activation_required  = true
seat_limit                  = creator intent
protection_implementation   = CONTRACT_ONLY
copy_protection_guarantee   = PLANNED_ENTITLEMENT

LEVEL 4
mode                        = HOSTED_ONLY
portable_protection         = NOT_APPLICABLE
buyer_passphrase_required   = false
seller_activation_required  = false
seat_limit                  = 0
protection_implementation   = AVAILABLE
copy_protection_guarantee   = HOSTED_BOUNDARY
```

## Mandatory acknowledgement

Levels 1-3 require explicit creator acknowledgement that portable delivery exposes/copies package content and cannot guarantee technical anti-copy protection.

Level 4 does not require that acknowledgement because the package is not handed out as portable content.

## Buy-once rule

Buy-once does not automatically mean fully portable.

Valid products include:

```text
BUY_ONCE + LEVEL_1_LICENSE_ONLY
BUY_ONCE + LEVEL_2_BUYER_PASSPHRASE
BUY_ONCE + LEVEL_3_DUAL_CONTROL_ACTIVATION
BUY_ONCE + LEVEL_4_HOSTED_ONLY
```

For Levels 1-3, buyer-funded BYOK is the natural inference-cost default unless another payer policy is explicitly configured.

## Safety boundary

Level 4:
- Safety Kernel may be mandatory and server-enforced.

Levels 1-3:
- Safety Kernel can be bundled and required by contract;
- if the recipient controls a modifiable runtime, removal cannot be made impossible;
- do not claim otherwise.

Where Safety enforcement is essential, choose Level 4 or keep the safety-critical operation behind a server boundary.

## Service-exit / buy-once survivability

Level 3 creates a new obligation: a buy-once product should not become unusable merely because the seller or WebAI Bridge later shuts down.

Before Level 3 becomes sellable, define an exit path such as:
- permanent offline entitlement release after verified shutdown conditions;
- escrowed release mechanism;
- signed long-lived exit entitlement;
- documented migration/export path.

This is intentionally not implemented in thin v0, but it is part of the Level 3 acceptance contract.

## V0 behavior

V0 does not implement:
- package encryption;
- passphrase enrollment/storage;
- activation server;
- seller signing key infrastructure;
- device fingerprinting;
- entitlement revocation;
- offline leases;
- DRM.

Therefore:
- Level 1 may export now with explicit risk acknowledgement;
- Level 2 may be recorded/exported only as `CONTRACT_ONLY` intent and must warn that encryption is not implemented;
- Level 3 may be recorded/exported only as `CONTRACT_ONLY` intent and must warn that activation/seat enforcement/exit behavior are not implemented;
- Level 4 is the strongest currently realizable boundary;
- no portable package may claim guaranteed technical anti-copy protection.

## Future implementation order

1. Package encryption primitive and secret-free manifest.
2. Buyer passphrase enrollment that never stores plaintext passphrases in package metadata.
3. Account-bound entitlement and seller/WebAI Bridge signing keys.
4. Seat/concurrency cap.
5. Signed package manifest.
6. Bounded offline lease if offline usability is justified.
7. Revocation + audit evidence.
8. Buy-once exit-key / survivability mechanism.
9. Device binding only if real abuse evidence justifies the UX/privacy cost.

## Product message

For creators:

> Level 1 gives maximum portability. Level 2 adds a buyer-secret barrier. Level 3 adds seller-side entitlement control. Level 4 keeps the AI hosted when secrecy and enforcement matter most.

For buyers:

> Portable means you can take the package with you. It does not erase licensing terms, and no portable level is sold as impossible to copy or inspect.
