from __future__ import annotations

import copy
import importlib
import json
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


class FakeUsage:
    input_tokens = 100
    output_tokens = 20


class FakeResponse:
    output_text = "paid-ok"
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


@pytest.fixture()
def commercial(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    FakeOpenAI.created = []
    for name in ["commercial", "app", "entitlements", "cost_router", "entitlement_cli"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial")
    return module, TestClient(module.app), tmp_path


def make_paid(app_config: dict, *, mode="BUY_ONCE") -> None:
    app_config["status"] = "active"
    app_config["access"]["mode"] = mode
    app_config["access"]["charge_basis"] = "ONE_TIME" if mode == "BUY_ONCE" else "MONTHLY"
    app_config["access"]["price_amount_minor"] = 1500
    app_config["access"]["commercial_enforcement"] = "ENTITLEMENT_ENFORCED"
    app_config["access"]["checkout"] = {
        "provider": "STRIPE_PAYMENT_LINK",
        "setup_mode": "SELF_SETUP",
        "payment_link_url": "https://buy.stripe.com/test",
        "binding_verification": "CREATOR_ATTESTED",
        "fulfillment": "MANUAL_HANDOFF",
        "entitlement_verification": "NOT_IMPLEMENTED",
    }
    app_config["billing"]["allowed_payer_modes"] = ["BYOK"]
    app_config["billing"]["default_payer_mode"] = "BYOK"
    app_config["billing"]["byok_transport"] = "SERVER_PROXY_EPHEMERAL"
    app_config["billing"].pop("platform_credit", None)
    app_config["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": [],
    }


def write_paid_config(module, tmp_path: Path, *, mode="BUY_ONCE", activated=True) -> Path:
    source = copy.deepcopy(module.core.registry.get("migration-fixture-ai"))
    source.pop("_instructions", None)
    make_paid(source, mode=mode)
    if not activated:
        source["status"] = "draft"
        source["access"]["commercial_enforcement"] = "NOT_IMPLEMENTED"
        source["readiness"] = {
            "configuration": "VALIDATED",
            "runtime": "BLOCKED_PAID_HOSTED_ENTITLEMENT_NOT_IMPLEMENTED",
            "commercial": "MANUAL_REVIEW_REQUIRED",
            "blockers": ["PAID_HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"],
        }
    path = tmp_path / f"{mode.lower()}.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    return path


def post_chat(client, token=None, key="buyer-key", payer_mode="BYOK"):
    headers = {}
    if token is not None:
        headers["X-WebAI-Entitlement"] = token
    if key is not None:
        headers["X-Provider-API-Key"] = key
    return client.post(
        "/api/chat",
        headers=headers,
        json={
            "slug": "migration-fixture-ai",
            "message": "hello",
            "history": [],
            "payer_mode": payer_mode,
        },
    )


def issue(module, payment_ref="pay_1", *, expires_at=None, buyer_ref="buyer-1"):
    return module.entitlements.issue(
        package_id="migration-fixture-ai",
        buyer_ref=buyer_ref,
        payment_ref=payment_ref,
        expires_at=expires_at,
    )


def test_entitlement_store_hashes_plaintext_and_revokes(commercial):
    module, _, tmp_path = commercial
    token = issue(module, "pay_hash", buyer_ref="order-1")
    assert token.startswith("webai_")
    assert module.entitlements.authorize(package_id="migration-fixture-ai", token=token)
    raw = (tmp_path / "entitlements.sqlite3").read_bytes()
    assert token.encode() not in raw
    rows = module.entitlements.list_for_package("migration-fixture-ai")
    assert rows[0]["buyer_ref"] == "order-1"
    assert rows[0]["payment_ref"] == "pay_hash"
    assert "token" not in rows[0]
    assert module.entitlements.revoke(token) is True
    assert module.entitlements.authorize(package_id="migration-fixture-ai", token=token) is False


def test_payment_reference_prevents_accidental_duplicate_active_issue_and_allows_reissue_after_revoke(commercial):
    module, _, _ = commercial
    first = issue(module, "pay_unique")
    with pytest.raises(ValueError, match="active entitlement"):
        issue(module, "pay_unique")
    assert module.entitlements.revoke_payment(package_id="migration-fixture-ai", payment_ref="pay_unique") == 1
    second = issue(module, "pay_unique")
    assert second != first


def test_expired_or_wrong_package_token_is_rejected(commercial):
    module, _, _ = commercial
    token = issue(module, "pay_expire", expires_at=int(time.time()) + 5)
    assert module.entitlements.authorize(package_id="migration-fixture-ai", token=token, now=int(time.time()) + 10) is False
    assert module.entitlements.authorize(package_id="other-ai", token=token) is False


def test_paid_page_can_load_shell_but_config_requires_entitlement(commercial):
    module, client, _ = commercial
    cfg = module.core.registry.get("migration-fixture-ai")
    make_paid(cfg)
    page = client.get("/a/migration-fixture-ai")
    assert page.status_code == 200
    assert "購入者アクセスコード" in page.text
    assert client.get("/apps/migration-fixture-ai/public-config").status_code == 401
    assert client.get(
        "/apps/migration-fixture-ai/public-config",
        headers={"X-WebAI-Entitlement": "webai_wrong"},
    ).status_code == 401


def test_valid_entitlement_unlocks_config_and_chat_with_byok(commercial):
    module, client, _ = commercial
    cfg = module.core.registry.get("migration-fixture-ai")
    make_paid(cfg)
    token = issue(module, "pay_valid", buyer_ref="order-2")

    config = client.get(
        "/apps/migration-fixture-ai/public-config",
        headers={"X-WebAI-Entitlement": token},
    )
    assert config.status_code == 200

    missing_key = post_chat(client, token=token, key=None)
    assert missing_key.status_code == 402
    assert FakeOpenAI.created == []

    result = post_chat(client, token=token, key="buyer-secret")
    assert result.status_code == 200
    assert result.json()["payer_mode"] == "BYOK"
    assert FakeOpenAI.created[-1].api_key == "buyer-secret"


def test_direct_chat_without_entitlement_never_reaches_provider(commercial):
    module, client, _ = commercial
    make_paid(module.core.registry.get("migration-fixture-ai"))
    result = post_chat(client, token=None, key="buyer-secret")
    assert result.status_code == 401
    assert FakeOpenAI.created == []


def test_revoked_entitlement_stops_existing_buyer(commercial):
    module, client, _ = commercial
    make_paid(module.core.registry.get("migration-fixture-ai"))
    token = issue(module, "pay_revoke")
    assert post_chat(client, token=token).status_code == 200
    assert module.entitlements.revoke_payment(package_id="migration-fixture-ai", payment_ref="pay_revoke") == 1
    before = len(FakeOpenAI.created)
    assert post_chat(client, token=token).status_code == 401
    assert len(FakeOpenAI.created) == before


def test_paid_hosted_v0_refuses_platform_credit_even_with_valid_token(commercial):
    module, client, _ = commercial
    cfg = module.core.registry.get("migration-fixture-ai")
    make_paid(cfg)
    cfg["billing"]["allowed_payer_modes"] = ["BYOK", "PLATFORM_CREDIT"]
    cfg["billing"]["platform_credit"] = {
        "enabled": True,
        "budget_id_env": "MIGRATION_FIXTURE_BUDGET_ID",
        "hard_limit_usd_micros": 500000,
    }
    token = issue(module, "pay_subsidy")
    result = post_chat(client, token=token, key=None, payer_mode="PLATFORM_CREDIT")
    assert result.status_code == 503
    assert FakeOpenAI.created == []


def test_only_buy_once_and_subscription_are_supported_for_manual_paid_hosted(commercial):
    module, client, _ = commercial
    cfg = module.core.registry.get("migration-fixture-ai")
    make_paid(cfg, mode="BUY_ONCE")
    token = issue(module, "pay_modes")
    assert client.get(
        "/apps/migration-fixture-ai/public-config",
        headers={"X-WebAI-Entitlement": token},
    ).status_code == 200

    make_paid(cfg, mode="SUBSCRIPTION")
    assert client.get(
        "/apps/migration-fixture-ai/public-config",
        headers={"X-WebAI-Entitlement": token},
    ).status_code == 200

    cfg["access"]["mode"] = "PER_USE"
    assert client.get(
        "/apps/migration-fixture-ai/public-config",
        headers={"X-WebAI-Entitlement": token},
    ).status_code == 503


def test_free_hosted_still_works_without_entitlement(commercial):
    module, client, _ = commercial
    cfg = module.core.registry.get("migration-fixture-ai")
    assert cfg["access"]["mode"] == "FREE"
    assert client.get("/apps/migration-fixture-ai/public-config").status_code == 200
    assert post_chat(client, token=None, key="free-byok").status_code == 200


def test_activate_config_is_explicit_and_fails_closed_for_subsidized_paid_package(commercial, tmp_path):
    module, _, _ = commercial
    cli = importlib.import_module("entitlement_cli")
    config_path = write_paid_config(module, tmp_path, activated=False)

    assert cli.cmd_activate_config(SimpleNamespace(config=str(config_path))) == 0
    activated = json.loads(config_path.read_text(encoding="utf-8"))
    assert activated["status"] == "active"
    assert activated["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert activated["readiness"]["runtime"] == "READY"

    subsidized = json.loads(config_path.read_text(encoding="utf-8"))
    subsidized["status"] = "draft"
    subsidized["access"]["commercial_enforcement"] = "NOT_IMPLEMENTED"
    subsidized["billing"]["allowed_payer_modes"] = ["BYOK", "PLATFORM_CREDIT"]
    subsidized["billing"]["platform_credit"] = {
        "enabled": True,
        "budget_id_env": "BUDGET_ID",
        "hard_limit_usd_micros": 100000,
    }
    subsidized_path = tmp_path / "subsidized.json"
    subsidized_path.write_text(json.dumps(subsidized), encoding="utf-8")
    with pytest.raises(SystemExit, match="BYOK-only"):
        cli.cmd_activate_config(SimpleNamespace(config=str(subsidized_path)))


def test_cli_requires_payment_attestation_and_subscription_expiry(commercial, tmp_path):
    module, _, _ = commercial
    cli = importlib.import_module("entitlement_cli")
    buy_once = write_paid_config(module, tmp_path, mode="BUY_ONCE", activated=True)

    base_args = dict(
        config=str(buy_once),
        payment_verified=False,
        payment_ref="pay_cli",
        buyer_ref="buyer-cli",
        days=None,
        base_url="",
        db=str(tmp_path / "cli.sqlite3"),
    )
    with pytest.raises(SystemExit, match="payment-verified"):
        cli.cmd_issue(SimpleNamespace(**base_args))

    base_args["payment_verified"] = True
    base_args["days"] = 30
    with pytest.raises(SystemExit, match="BUY_ONCE"):
        cli.cmd_issue(SimpleNamespace(**base_args))

    subscription = write_paid_config(module, tmp_path, mode="SUBSCRIPTION", activated=True)
    sub_args = dict(base_args)
    sub_args.update(config=str(subscription), payment_ref="pay_sub_cli", days=None)
    with pytest.raises(SystemExit, match="requires --days"):
        cli.cmd_issue(SimpleNamespace(**sub_args))

    sub_args["days"] = 31
    assert cli.cmd_issue(SimpleNamespace(**sub_args)) == 0
