from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=20):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResponse:
    def __init__(self, text="ok", usage=True):
        self.output_text = text
        self.usage = FakeUsage() if usage else None


class FakeResponses:
    def __init__(self, response=None, exc=None, sink=None):
        self.response = response or FakeResponse()
        self.exc = exc
        self.sink = sink if sink is not None else []

    def create(self, **kwargs):
        self.sink.append(kwargs)
        if self.exc:
            raise self.exc
        return self.response


class FakeOpenAI:
    created = []
    response = FakeResponse()
    exc = None

    def __init__(self, api_key):
        self.api_key = api_key
        type(self).created.append(self)
        self.calls = []
        self.responses = FakeResponses(type(self).response, type(self).exc, self.calls)


@pytest.fixture()
def appmod(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("OPENAI_API_KEY", "platform-secret")
    monkeypatch.setenv("MIGRATION_FIXTURE_BUDGET_ID", "dogfood-budget")
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    FakeOpenAI.created = []
    FakeOpenAI.response = FakeResponse()
    FakeOpenAI.exc = None
    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    for name in ["app", "cost_router"]:
        sys.modules.pop(name, None)
    return importlib.import_module("app")


@pytest.fixture()
def client(appmod):
    return TestClient(appmod.app)


def post(client, *, payer_mode="BYOK", key="user-secret", message="hello", history=None):
    headers = {}
    if key is not None:
        headers["X-Provider-API-Key"] = key
    return client.post("/api/chat", headers=headers, json={"slug": "migration-fixture-ai", "message": message, "history": history or [], "payer_mode": payer_mode})


def test_health_and_public_config_do_not_leak_instructions(client):
    assert client.get("/health").status_code == 200
    res = client.get("/apps/migration-fixture-ai/public-config")
    assert res.status_code == 200
    body = json.dumps(res.json())
    assert "BRIDGE-DOGFOOD-001" not in body
    assert "_instructions" not in body


def test_unknown_slug_is_404(client):
    assert client.get("/apps/nope/public-config").status_code == 404


def test_byok_requires_key(client):
    res = post(client, payer_mode="BYOK", key=None)
    assert res.status_code == 402
    assert FakeOpenAI.created == []


def test_byok_uses_user_key_without_platform_spend(client, appmod):
    res = post(client, payer_mode="BYOK", key="my-key")
    assert res.status_code == 200
    assert FakeOpenAI.created[-1].api_key == "my-key"
    assert appmod.ledger.budget_snapshot("dogfood-budget") is None


def test_platform_credit_uses_platform_key_and_records_spend(client, appmod):
    res = post(client, payer_mode="PLATFORM_CREDIT", key=None)
    assert res.status_code == 200
    assert FakeOpenAI.created[-1].api_key == "platform-secret"
    snap = appmod.ledger.budget_snapshot("dogfood-budget")
    assert snap is not None and snap["spent_micros"] > 0 and snap["reserved_micros"] == 0


def test_platform_budget_exhaustion_blocks_before_provider(client, appmod):
    appmod.registry.get("migration-fixture-ai")["billing"]["platform_credit"]["hard_limit_usd_micros"] = 1
    before = len(FakeOpenAI.created)
    res = post(client, payer_mode="PLATFORM_CREDIT", key=None)
    assert res.status_code == 402
    assert len(FakeOpenAI.created) == before


def test_provider_failure_releases_platform_reservation(client, appmod):
    FakeOpenAI.exc = RuntimeError("boom")
    res = post(client, payer_mode="PLATFORM_CREDIT", key=None)
    assert res.status_code == 502
    snap = appmod.ledger.budget_snapshot("dogfood-budget")
    assert snap is not None and snap["reserved_micros"] == 0 and snap["spent_micros"] == 0


def test_unknown_price_blocks_platform_execution(client, appmod):
    cfg = appmod.registry.get("migration-fixture-ai")
    cfg["routing"]["default_model"] = "unknown-model"
    cfg["routing"]["allowed_models"].append("unknown-model")
    before = len(FakeOpenAI.created)
    res = post(client, payer_mode="PLATFORM_CREDIT", key=None)
    assert res.status_code == 503
    assert len(FakeOpenAI.created) == before


def test_platform_knowledge_without_tool_cost_policy_blocks(client, appmod, monkeypatch):
    cfg = appmod.registry.get("migration-fixture-ai")
    cfg["knowledge"]["enabled"] = True
    cfg["knowledge"]["platform_tool_reserve_usd_micros"] = 0
    monkeypatch.setenv("MIGRATION_FIXTURE_VECTOR_STORE_ID", "vs_test")
    assert post(client, payer_mode="PLATFORM_CREDIT", key=None).status_code == 503


def test_input_and_history_limits(client, appmod):
    cfg = appmod.registry.get("migration-fixture-ai")
    cfg["usage"]["max_input_chars"] = 3
    assert post(client, message="1234").status_code == 413
    cfg["usage"]["max_input_chars"] = 12000
    cfg["usage"]["max_history_messages"] = 1
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert post(client, history=history).status_code == 413


def test_request_construction_keeps_private_instructions_server_side(client):
    res = post(client, payer_mode="BYOK", key="k", message="code word?")
    assert res.status_code == 200
    call = FakeOpenAI.created[-1].calls[-1]
    assert "BRIDGE-DOGFOOD-001" in call["instructions"]
    assert call["store"] is False
    assert call["model"] == "gpt-5.6-luna"
    assert "tools" not in call


def test_knowledge_binding_comes_from_server_env(client, appmod, monkeypatch):
    cfg = appmod.registry.get("migration-fixture-ai")
    cfg["knowledge"]["enabled"] = True
    monkeypatch.setenv("MIGRATION_FIXTURE_VECTOR_STORE_ID", "vs_server_only")
    res = post(client, payer_mode="BYOK", key="k")
    assert res.status_code == 200
    call = FakeOpenAI.created[-1].calls[-1]
    assert call["tools"] == [{"type": "file_search", "vector_store_ids": ["vs_server_only"]}]
