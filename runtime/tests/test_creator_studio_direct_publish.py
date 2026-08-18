from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import knowledge_studio


SLUG = "studio-direct-publish-test"
PAYMENT_LINK = "https://buy.stripe.com/test-direct-publish"


def _payload(*, confirmed: bool) -> dict:
    return {
        "display_name": "Direct Publish Test",
        "slug": SLUG,
        "description": "Creator Studio direct publish fixture",
        "instructions": "Knowledgeを参照して短く答えてください。",
        "welcome": "質問してください。",
        "knowledge_enabled": True,
        "knowledge_text": "確認用合言葉は青いペンギンです。",
        "knowledge_vector_store_env": "",
        "knowledge_reserve_tokens": 0,
        "knowledge_platform_tool_reserve_usd": "0",
        "knowledge_max_context_chars": 6000,
        "knowledge_max_chunks": 4,
        "knowledge_chunk_chars": 1800,
        "access_mode": "BUY_ONCE",
        "access_price_jpy": 100,
        "included_runs": 0,
        "checkout_setup_mode": "SELF_SETUP",
        "stripe_payment_link_url": PAYMENT_LINK,
        "stripe_link_matches_configuration": True,
        "allowed_payer_modes": ["BYOK"],
        "default_payer_mode": "BYOK",
        "platform_budget_id_env": "",
        "platform_hard_limit_usd": "0",
        "default_model": "gpt-5.6-luna",
        "allowed_models": ["gpt-5.6-luna"],
        "protection_level": "LEVEL_4_HOSTED_ONLY",
        "portable_seat_limit": 1,
        "portable_copy_risk_acknowledged": False,
        "max_input_chars": 12000,
        "max_history_messages": 12,
        "max_history_chars": 48000,
        "max_output_tokens": 256,
        "publish_confirmed": confirmed,
    }


class _Registry:
    def __init__(self) -> None:
        self.reloaded = False
        self.apps = {
            "paid-dogfood-ai": {"status": "active"},
            SLUG: {"status": "active"},
        }

    def reload(self) -> None:
        self.reloaded = True

    def get(self, slug: str) -> dict:
        assert slug == SLUG
        return {
            "slug": SLUG,
            "status": "active",
            "access": {"commercial_enforcement": "ENTITLEMENT_ENFORCED"},
        }


class _Core:
    def __init__(self, config_dir: Path) -> None:
        self.CONFIG_DIR = config_dir
        self.registry = _Registry()

    @staticmethod
    def require_studio_enabled() -> None:
        return None

    @staticmethod
    def enforce_rate_limit(_request) -> None:
        return None


def test_direct_publish_requires_explicit_confirmation_and_uses_bundle_authority(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)
    core = _Core(config_dir)
    base = SimpleNamespace(app=FastAPI(), core=core)

    package = {
        "slug": SLUG,
        "status": "draft",
        "access": {
            "mode": "BUY_ONCE",
            "commercial_enforcement": "NOT_IMPLEMENTED",
            "checkout": {
                "provider": "STRIPE_PAYMENT_LINK",
                "payment_link_url": PAYMENT_LINK,
                "setup_mode": "SELF_SETUP",
                "binding_verification": "CREATOR_ATTESTED",
            },
        },
        "knowledge": {"artifact_sha256": "a" * 64},
    }

    monkeypatch.setattr(
        knowledge_studio,
        "build_knowledge_studio_result",
        lambda **_kwargs: {"package": package, "warnings": [], "exports": {}},
    )

    calls: list[dict] = []

    def fake_install_bundle(**kwargs):
        package_source = kwargs["package_source"]
        instructions_source = kwargs["instructions_source"]
        knowledge_source = kwargs["knowledge_source"]
        assert kwargs["config_dir"] == config_dir
        assert kwargs["replace_nonrunnable"] is True
        assert json.loads(package_source.read_text(encoding="utf-8"))["slug"] == SLUG
        assert "Knowledgeを参照" in instructions_source.read_text(encoding="utf-8")
        assert "青いペンギン" in knowledge_source.read_text(encoding="utf-8")
        for path in (package_source, instructions_source, knowledge_source):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        calls.append({"stage": "install"})
        return {
            "installed": True,
            "authority_commit": "PACKAGE_JSON_LAST",
            "package_path": str(config_dir / f"{SLUG}.json"),
        }

    def fake_activate_bundle(**kwargs):
        assert kwargs["config_path"] == config_dir / f"{SLUG}.json"
        assert kwargs["checkout_reviewed"] is False
        calls.append({"stage": "activate"})
        return {
            "activated": True,
            "knowledge_verified": True,
            "knowledge_sha256": "a" * 64,
            "runtime": "READY",
            "commercial": "MANUAL_REVIEW_REQUIRED",
            "checkout_binding_verification": "CREATOR_ATTESTED",
        }

    monkeypatch.setattr(knowledge_studio.package_bundle_cli, "install_bundle", fake_install_bundle)
    monkeypatch.setattr(knowledge_studio.package_bundle_cli, "activate_bundle", fake_activate_bundle)

    knowledge_studio.install_knowledge_studio_routes(base)
    client = TestClient(base.app)

    denied = client.post("/api/studio/publish", json=_payload(confirmed=False))
    assert denied.status_code == 400
    assert calls == []

    published = client.post("/api/studio/publish", json=_payload(confirmed=True))
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "PUBLISHED"
    assert body["package_id"] == SLUG
    assert body["authority_commit"] == "PACKAGE_JSON_LAST"
    assert body["knowledge_verified"] is True
    assert body["checkout_url"] == f"/api/buy/{SLUG}"
    assert body["buyer_path"] == f"/a/{SLUG}"
    assert body["stripe_payment_link_configured"] is True
    assert PAYMENT_LINK not in json.dumps(body, ensure_ascii=False)
    assert body["active_packages"] == 2
    assert body["secrets_in_output"] is False
    assert core.registry.reloaded is True
    assert calls == [{"stage": "install"}, {"stage": "activate"}]


def test_direct_publish_rejects_subscription_v1(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)
    base = SimpleNamespace(app=FastAPI(), core=_Core(config_dir))
    knowledge_studio.install_knowledge_studio_routes(base)
    payload = _payload(confirmed=True)
    payload["access_mode"] = "SUBSCRIPTION"
    response = TestClient(base.app).post("/api/studio/publish", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == "Direct publish v1 supports BUY_ONCE only"
