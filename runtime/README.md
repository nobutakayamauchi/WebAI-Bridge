# Runtime

State: `DOGFOOD / NOT_PRODUCTION`

This is the first extracted WebAI Bridge runtime. It hosts an AI Package through a smartphone URL while keeping provider Instructions server-side and resolving who pays before provider execution.

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

## Creator Studio

Creator Studio is deliberately disabled by default. Enable the thin export-only surface with:

```bash
export WEB_AI_STUDIO_ENABLED=1
```

Then open `/studio`.

Studio validation:

- uses the canonical `package-schema/package.schema.json`;
- checks semantic payer/budget/model/Knowledge rules;
- reads model availability from the current pricing registry;
- does **not** call the AI provider;
- does **not** write live package files or mutate the runtime registry;
- returns package JSON for explicit operator export/deployment.

## Core invariant

```text
NO PAYER RESOLUTION
→ NO BUDGET AUTHORIZATION
→ NO MODEL EXECUTION
```

V0 payer modes:

- `BYOK`: user supplies a provider key for the current page/request path. The runtime does not intentionally persist the key.
- `PLATFORM_CREDIT`: server credential + explicit persistent budget. Budget is reserved before the provider call.

## Runtime identity

`GET /runtime` reports the service/unit, working directory, route surface, deployed revision, pricing version and ledger path. `UNSET` means deployment identity has not been established.

## Knowledge

Set `knowledge.enabled=true`, supply the server-side vector store through the configured environment variable, and provide an explicit platform tool-cost reserve before using `PLATFORM_CREDIT`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Current limits

No commercial payment enforcement, no purchased wallet, no persistent BYOK secret store, no authentication, no streaming, no Studio server-write/publish authority, and no production deployment claim yet.
