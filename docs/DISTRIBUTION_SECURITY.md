# Distribution Security / Copy-Control Boundary

Date: 2026-08-16
Status: `FROZEN_FOR_V0_CONTRACT / ENFORCEMENT_PARTIAL`

## Finding

A portable AI Package delivered as a ZIP/file bundle can be copied after delivery. If the recipient controls the runtime and receives the package contents, WebAI Bridge cannot honestly claim perfect technical prevention of copying, inspection, modification, or Safety Kernel removal.

This is not a billing bug. It is a distribution-authority boundary.

## Hard invariant

```text
DELIVERED PLAINTEXT PACKAGE != TECHNICALLY NON-COPYABLE PACKAGE

PORTABLE != SECRET

PORTABLE != SAFETY ENFORCED

LICENSE TERMS != TECHNICAL COPY CONTROL
```

No UI, package metadata, sales text, or creator warning may imply otherwise.

## Distribution classes

### 1. HOSTED_ONLY

The package executes on a WebAI Bridge controlled runtime.

Properties:
- Instructions/Knowledge can remain server-side.
- Entitlement can be enforced server-side.
- Safety Kernel can be enforced server-side.
- API/provider credentials can remain server-side or be provided as bounded BYOK at runtime.
- Strongest available protection against casual package copying.

Recommended for:
- high-value proprietary Instructions;
- private or licensed Knowledge;
- regulated/sensitive workflows;
- creators who require strong entitlement enforcement;
- packages where Safety Kernel enforcement is a hard requirement.

### 2. PORTABLE_LICENSE_ONLY

The package may be exported/copied to the buyer's environment.

Properties:
- redistribution can be prohibited by license/terms;
- no claim of technical copy prevention;
- no claim that hidden Instructions remain hidden;
- no claim that Safety Kernel cannot be modified/removed;
- buyer may use their own supported provider/model/API key according to the package contract.

This is the lowest-friction buy-once mode.

Recommended for:
- creators who accept copy risk;
- inexpensive packages;
- open/educational packages;
- packages whose value comes from updates/support rather than secrecy.

### 3. PORTABLE_ACTIVATED

The package may be downloaded, but normal execution requires a valid entitlement/activation state.

Target properties:
- account/license-bound activation;
- seat/device/concurrency limits where justified;
- signed package/manifest;
- optional bounded offline lease;
- server-verifiable entitlement renewal/revocation.

Important limit:
If the buyer controls and can modify the runtime/source, activation remains a best-effort barrier rather than an absolute anti-copy guarantee. Stronger enforcement requires retaining a meaningful execution or secret boundary server-side.

V0 status: `CONTRACT_ONLY / NOT_IMPLEMENTED`.

## Creator choice

Creator Studio must ask separately:

1. Delivery mode: hosted / portable / both.
2. Portable protection intent:
   - `LICENSE_ONLY`
   - `ACTIVATION_REQUIRED`
3. Seat limit intent when activation is requested.
4. Explicit acknowledgement that portable delivery exposes/copies package content and cannot guarantee technical anti-copy protection.

## Buy-once rule

Buy-once does not automatically mean fully portable.

Valid combinations include:

```text
BUY_ONCE + HOSTED_ONLY
BUY_ONCE + PORTABLE_LICENSE_ONLY
BUY_ONCE + PORTABLE_ACTIVATED
```

For `PORTABLE_LICENSE_ONLY`, the buyer may select supported provider/model and use their own API key after purchase. Inference cost is therefore buyer-funded unless another payer policy is explicitly configured.

For `PORTABLE_ACTIVATED`, the same provider/model freedom may exist, but normal package execution additionally checks entitlement according to the activation contract.

## Safety boundary

Hosted:
- Safety Kernel may be mandatory and server-enforced.

Portable:
- Safety Kernel is bundled/recommended by contract;
- if the recipient controls a modifiable runtime, removal cannot be made impossible;
- do not claim otherwise.

Where Safety enforcement is essential, choose `HOSTED_ONLY` or retain the safety-critical operation behind a server boundary.

## V0 behavior

V0 does not implement activation servers, device fingerprinting, DRM, or remote revocation.

Therefore:
- `HOSTED_ONLY` can be represented as the strongest current control intent;
- `PORTABLE_LICENSE_ONLY` is allowed with explicit risk acknowledgement;
- `PORTABLE_ACTIVATED` may be represented as planned intent but must emit a blocking/not-for-sale warning until entitlement enforcement exists;
- no portable package may claim `copy_protection = GUARANTEED`.

## Future implementation order

1. Account-bound entitlement, not hardware fingerprinting by default.
2. Seat/concurrency cap.
3. Signed package manifest.
4. Short-lived activation token / offline lease if offline usability is needed.
5. Revocation and audit evidence.
6. Only add device binding when an actual abuse case justifies the UX/privacy cost.

## Product message

For creators:

> Keep it hosted if the AI must stay secret or tightly controlled. Allow portability when buyer freedom matters more than perfect copy control.

For buyers:

> Portable means you can take the package with you. It does not mean the creator's licensing terms disappear.
