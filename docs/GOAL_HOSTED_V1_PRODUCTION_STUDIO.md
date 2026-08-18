# /goal — Hosted v1 fixed-domain Creator Studio path

Date: 2026-08-18
Method: `Ultimate Loop / Raison d'être / DA / Counter-DA / METEOR`
Status: `CODE_CHALLENGER / FIXED_DOMAIN_EXTERNAL_GATE_PENDING`

## Protected outcome

A creator can run WebAI Bridge on a stable HTTPS hostname, create and directly publish a second paid Hosted/BYOK/Knowledge AI from the authenticated smartphone Creator Studio, sell it through the existing Stripe entitlement path, and preserve safe stop/recovery boundaries without mutating the deployed Git tree.

The goal is **not** to implement every future payer, portable, wallet, subscription, plugin, or admin feature before the first bounded Hosted v1 release.

## Raison d'être

The current product already proved the hard commercial chain in live dogfood:

```text
Stripe payment
→ durable webhook entitlement
→ cross-browser handoff
→ iPhone Safari
→ ephemeral BYOK
→ PACKAGE_TEXT Knowledge
→ provider response
→ revocation
```

PR #29 also proved authenticated Creator Studio direct publish in code.

Therefore the next useful result is not another parallel runtime. It is to connect those proven parts to the deterministic fixed-domain deployment path while preserving authority boundaries.

## DA finding 1 — direct publish was disconnected from production rendering

Observed:

```text
Creator Studio direct publish exists
BUT
render_deployment.py forced commercial:app + Studio OFF
```

Failure mode:

- smartphone creator path works only in the dogfood launcher;
- fixed-domain operator path silently regresses to buyer-only/manual package management;
- product capability and deployment capability disagree.

Resolution:

Two explicit deployment profiles:

```text
BUYER_ONLY_COMMERCIAL_V1
→ commercial:app
→ Studio OFF

CREATOR_STUDIO_COMMERCIAL_V1
→ commercial_handoff:app
→ Studio ON
→ creator auth required
```

No automatic profile promotion is allowed. Creator Studio remains opt-in.

## Counter-DA finding 2 — systemd sandbox would kill direct publish

Initial challenger mistake:

```text
WEB_AI_CONFIG_DIR=/opt/webai-bridge/runtime/apps
ProtectSystem=strict
ReadWritePaths=/var/lib/webai-bridge
```

That combination makes the direct-publish code path read-only in real systemd even though unit tests can write a temporary directory.

Resolution:

Creator-managed deployment uses:

```text
WEB_AI_CONFIG_DIR=/var/lib/webai-bridge/apps
package_authority=STATE_DIR
```

The deployed Git/runtime tree stays read-only. Mutable product authority is restricted to the already-writable private state tree.

Buyer-only deployment keeps the previous runtime/apps authority because the running service does not need to mutate it.

## DA finding 3 — paid surface could start with guaranteed late failure

The commercial handoff path needs live secrets for:

- signed buyer cookie transport;
- Stripe Checkout/Payment Link server verification;
- durable webhook fulfillment.

Previously, missing values could survive startup and fail only when a buyer reached that route.

Resolution:

When `commercial_handoff` has at least one active paid package, preflight now requires:

```text
WEB_AI_ENTITLEMENT_COOKIE_SECRET
WEB_AI_STRIPE_SECRET_KEY
WEB_AI_STRIPE_WEBHOOK_SECRET
```

Missing or structurally invalid values fail before service start.

No secret values are rendered into systemd or deployment-manifest output.

## DA finding 4 — second-product acceptance was weaker than the product claim

PR #29 tested direct publish with mocked bundle install/activation functions. That proves route composition, but not the full authority path for a second real package.

Resolution:

Add a real filesystem/registry test that:

1. logs into Creator Studio;
2. direct-publishes product A using actual bundle install/activation;
3. verifies Package JSON, Instructions and Knowledge owner-only files;
4. verifies Knowledge digest and entitlement-enforced active state;
5. direct-publishes product B without code edits/file transfer;
6. verifies both products coexist and Knowledge stays isolated;
7. attempts to republish product A over active authority;
8. requires fail-closed refusal and byte-for-byte preservation of product A artifacts.

This is the code-level proof for:

```text
SECOND AI GENERATED FROM CONFIG ONLY
```

A fixed-domain real-host repeat remains an external gate.

## DA finding 5 — documentation had become false runtime evidence

Root/runtime/deployment documentation still described:

- Studio as export-only;
- paid entitlement as absent;
- direct publish as unavailable;
- older manual-only deployment flow.

That stale documentation can misroute a future model/operator even when the code is correct.

Resolution:

Align docs to current implementation while preserving explicit non-claims.

## Frozen Hosted v1 candidate scope

Required for this bounded release:

```text
HOSTED_ONLY
BUY_ONCE direct publish
BYOK inference
server-owned Instructions
PACKAGE_TEXT Knowledge
creator authentication
Stripe Payment Link
Stripe webhook entitlement
browser handoff
revocation
fixed-domain HTTPS deployment
exact revision identity
```

Not required for this gate:

```text
portable runtime
portable Knowledge secrecy
wallet/purchased platform credits
creator-funded shared inference
sponsored/hybrid payer routing
full subscription automation
multi-worker BYOK credential sharing
perfect DRM
OpenAI Plugin delivery
```

Those can re-enter as separate goals after the Hosted v1 proof.

## METEOR attack set for this challenger

Code/CI must reject or preserve safety under at least:

- Creator Studio enabled without creator auth;
- missing/unsafe creator password/session secret files;
- active paid handoff without cookie/Stripe/webhook secrets;
- product package/Instructions/Knowledge permission widening;
- Knowledge digest mismatch;
- draft package pretending to be active/runnable;
- active package silent overwrite;
- second product corrupting first product state;
- direct publish writing into deployed Git/runtime under systemd sandbox;
- route surface/profile mismatch;
- diagnostics or insecure HTTP being re-enabled by operator env overrides;
- secret values entering generated deployment artifacts.

Existing Stripe replay, webhook idempotency, checkout binding, cross-browser handoff, BYOK, entitlement/revocation, and Knowledge tests remain part of the regression surface.

## External reality gate

This branch cannot honestly prove real infrastructure from GitHub CI alone.

After code/CI passes, the remaining external sequence is:

```text
exact branch/revision deployed to controlled Linux host
→ state/apps + creator secret files created with safe ownership/mode
→ private Stripe/cookie/webhook environment configured
→ renderer --creator-studio
→ systemd preflight PASS
→ Caddy fixed-domain HTTPS PASS
→ Creator login / Studio PASS on smartphone
→ direct-publish a brand-new second product
→ live Stripe payment + webhook entitlement
→ buyer handoff + iPhone Safari
→ ephemeral BYOK + Knowledge response
→ revoke and immediate denial
```

No `PRODUCTION_PASS` claim is allowed before that evidence exists.

## Merge gate

Stop before merge when all code-side conditions are true:

```text
latest branch CI green
PR mergeable
branch based on current main / no unresolved composition conflict
new multi-product direct-publish test green
existing commercial/Stripe/BYOK/Knowledge tests green
no surviving code-side release blocker inside frozen Hosted v1 scope
external fixed-domain gates still explicitly unclaimed
```

Human merge remains a separate decision.
