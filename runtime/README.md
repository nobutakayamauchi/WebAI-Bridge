# Runtime

State: `DOGFOOD / NOT_PRODUCTION`

This is the current hosted WebAI Bridge runtime. It serves an activated hosted AI Package through a smartphone URL, keeps creator Instructions server-side, resolves the inference payer before provider execution, and fails closed on package states it cannot yet enforce.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY='...'
export MIGRATION_FIXTURE_BUDGET_ID='dogfood-001'
uvicorn app:app --host 0.0.0.0 --port 8080
```

Open `/a/migration-fixture-ai`.

## Core execution invariant

```text
PACKAGE RUNNABLE
→ PAYER RESOLUTION
→ BUDGET AUTHORIZATION
→ MODEL RESOLUTION
→ PROVIDER EXECUTION
```

And:

```text
DRAFT != RUNNABLE
PAID HOSTED + NO ENTITLEMENT != RUNNABLE
PORTABLE INTENT != HOSTED RUNTIME
```

The current hosted runtime accepts only package status `dogfood` or `active`, hosted delivery with an available hosted runtime, and currently-free access. Paid hosted execution is intentionally blocked until entitlement enforcement exists.

## Creator Studio

Creator Studio is disabled by default. Enable the export-only surface with:

```bash
export WEB_AI_STUDIO_ENABLED=1
```

Then open `/studio`.

Studio validation:
- validates against the canonical package JSON Schema;
- checks payer/budget/model/Knowledge/checkout/distribution semantics;
- returns config validity separately from runtime/commercial readiness;
- does not call the provider;
- does not mutate live package files or runtime registry.

## Hosted Safety policy

`runtime/safety_kernel.md` is loaded at runtime startup and prepended before creator package Instructions.

The current classification is:

`PROMPT_POLICY_PLUS_PROVIDER_BASELINE`

It provides a server-controlled policy boundary but is not claimed to be perfect moderation or portable enforcement.

## BYOK

`BYOK` uses the end user's provider key for the request.

The runtime does not intentionally persist that key, but hosted BYOK is **server-proxy ephemeral**: the key reaches the WebAI Bridge server and is forwarded to the provider. The UI and package metadata disclose this explicitly.

## PLATFORM_CREDIT and ledger

`PLATFORM_CREDIT` requires:
- server provider credential;
- budget identity;
- positive hard cap;
- pre-call reservation;
- explicit Knowledge tool-cost reserve when Knowledge is enabled.

If provider-observed actual cost exceeds the reservation, the ledger records the actual cost rather than hiding the overrun. A one-request estimate overrun can therefore push recorded spend above the nominal hard cap after the external provider charge has already happened; subsequent reservations fail closed.

Reservation IDs, idempotent settlement and crash-lease recovery remain a production gate before retry/multi-worker wallet semantics are claimed.

## Request bounds

The runtime bounds:
- current message characters;
- history message count;
- history total characters;
- output-token request size;
- basic in-memory request rate.

The current IP/in-memory rate limiter is a dogfood guard only. Reverse-proxy-aware user identity and distributed quota enforcement require the deployment/auth layer.

## Package/path authority

Every runtime package is validated against `package-schema/package.schema.json` when loaded.

`instructions_file` must exactly match:

```text
apps/{slug}.instructions.md
```

and resolve inside `runtime/apps`.

## Runtime identity

Deployment Identity remains important, but `/runtime` diagnostics are disabled by default because they expose deployment/filesystem details.

Enable deliberately:

```bash
export WEB_AI_DIAGNOSTICS_ENABLED=1
```

Then `GET /runtime` reports service/unit, working directory, route surface, deployed revision, pricing version and ledger path. `UNSET` still means deployment identity has not been established.

## Knowledge

Current Knowledge is a hosted server binding. Set `knowledge.enabled=true`, supply the server-side vector store through the configured environment variable, and provide an explicit positive tool-cost reserve before platform-funded use.

Portable Knowledge packaging/binding does not exist yet.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Current limits

No paid entitlement enforcement, no purchased wallet, no persistent creator/BYOK secret store, no user authentication, no distributed quota system, no portable runtime/ZIP, no portable Knowledge packaging, no streaming, no Studio publish/write authority, and no production deployment claim.
