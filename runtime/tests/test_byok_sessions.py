from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from byok_sessions import ByokSessionStore


class FakeUsage:
    input_tokens = 10
    output_tokens = 4


class FakeResponse:
    output_text = "session-ok"
    usage = FakeUsage()


class FakeResponses:
    def __init__(self, sink):
        self.sink = sink

    def create(self, **kwargs):
        self.sink.append(kwargs)
        return FakeResponse()


class FakeOpenAI:
    created = []

    def __init__(self, api_key):
        self.api_key = api_key
        self.calls = []
        self.responses = FakeResponses(self.calls)
        type(self).created.append(self)


def load_commercial(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "0")
    monkeypatch.setenv("WEB_AI_BYOK_SESSION_TTL_SECONDS", "900")
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    FakeOpenAI.created = []
    for name in ["commercial", "app", "byok_sessions", "entitlements", "cost_router"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial")
    return module, TestClient(module.app, base_url="https://testserver")


def test_store_expires_forgets_and_is_package_scoped():
    store = ByokSessionStore(ttl_seconds=60, max_sessions=5)
    session = store.create(package_id="a", api_key="provider-secret", now=100)
    assert store.resolve(package_id="a", token=session.token, now=120) == "provider-secret"
    assert store.resolve(package_id="b", token=session.token, now=120) is None
    assert store.status(package_id="a", token=session.token, now=159)["connected"] is True
    assert store.resolve(package_id="a", token=session.token, now=160) is None

    session2 = store.create(package_id="a", api_key="provider-secret-2", now=200)
    assert store.forget(session2.token) is True
    assert store.resolve(package_id="a", token=session2.token, now=201) is None


def test_https_session_cookie_contains_only_opaque_token_and_chat_uses_ram_key(tmp_path, monkeypatch):
    module, client = load_commercial(tmp_path, monkeypatch)
    slug = "migration-fixture-ai"

    created = client.post("/api/byok/session", json={"slug": slug, "api_key": "buyer-provider-secret"})
    assert created.status_code == 200
    body = created.json()
    assert body["connected"] is True
    assert body["storage"] == "PROCESS_MEMORY_ONLY"
    assert body["browser_api_key_retained"] is False
    assert "buyer-provider-secret" not in created.text

    set_cookie = created.headers["set-cookie"]
    lower_cookie = set_cookie.lower()
    assert "buyer-provider-secret" not in set_cookie
    assert "httponly" in lower_cookie
    assert "secure" in lower_cookie
    assert "samesite=strict" in lower_cookie
    assert module.byok_cookie_name(slug) in set_cookie

    status = client.get(f"/api/byok/session/{slug}")
    assert status.status_code == 200
    assert status.json()["connected"] is True

    result = client.post(
        "/api/chat",
        json={"slug": slug, "message": "hello", "history": [], "payer_mode": "BYOK"},
    )
    assert result.status_code == 200
    assert result.json()["text"] == "session-ok"
    assert FakeOpenAI.created[-1].api_key == "buyer-provider-secret"


def test_public_https_rejects_legacy_provider_header(tmp_path, monkeypatch):
    _, client = load_commercial(tmp_path, monkeypatch)
    before = len(FakeOpenAI.created)
    result = client.post(
        "/api/chat",
        headers={"X-Provider-API-Key": "legacy-browser-key"},
        json={"slug": "migration-fixture-ai", "message": "hello", "history": [], "payer_mode": "BYOK"},
    )
    assert result.status_code == 400
    assert len(FakeOpenAI.created) == before


def test_forget_removes_ram_authority_and_cookie(tmp_path, monkeypatch):
    _, client = load_commercial(tmp_path, monkeypatch)
    slug = "migration-fixture-ai"
    assert client.post("/api/byok/session", json={"slug": slug, "api_key": "buyer-provider-secret"}).status_code == 200
    forgotten = client.delete(f"/api/byok/session/{slug}")
    assert forgotten.status_code == 200
    assert forgotten.json()["connected"] is False
    assert client.get(f"/api/byok/session/{slug}").json()["connected"] is False
    result = client.post(
        "/api/chat",
        json={"slug": slug, "message": "hello", "history": [], "payer_mode": "BYOK"},
    )
    assert result.status_code == 402


def test_session_creation_requires_https_in_public_mode(tmp_path, monkeypatch):
    module, _ = load_commercial(tmp_path, monkeypatch)
    http_client = TestClient(module.app, base_url="http://testserver")
    result = http_client.post(
        "/api/byok/session",
        json={"slug": "migration-fixture-ai", "api_key": "buyer-provider-secret"},
    )
    assert result.status_code == 426
