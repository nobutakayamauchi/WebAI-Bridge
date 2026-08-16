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

## Current limits

No commercial payment enforcement, no purchased wallet, no persistent BYOK secret store, no authentication, no streaming, and no production deployment claim yet.
