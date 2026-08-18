from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import sys
from pathlib import Path

from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

CREATOR_PASSWORD = "creator-multi-product-password-abcdefghijklmnopqrstuvwxyz"
CREATOR_SESSION_SECRET = "creator-multi-product-session-secret-abcdefghijklmnopqrstuvwxyz0123456789"


def _private(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _payload(*, slug: str, model: str, phrase: str, payment_link: str) -> dict:
    return {
        "display_name": f"Direct Publish {slug}",
        "slug": slug,
        "description": "Creator Studio direct-publish multi-product proof",
        "instructions": "Package Knowledgeを参照し、短く答えてください。",
        "welcome": "質問してください。",
        "knowledge_enabled": True,
        "knowledge_text": f"この商品の確認用合言葉は「{phrase}」です。\n",
        "knowledge_vector_store_env": "",
        "knowledge_reserve_tokens": 0,
        "knowledge_platform_tool_reserve_usd": "0",
        "knowledge_max_context_chars": 4000,
        "knowledge_max_chunks": 3,
        "knowledge_chunk_chars": 1200,
        "access_mode": "BUY_ONCE",
        "access_price_jpy": 500,
        "included_runs": 0,
        "checkout_setup_mode": "SELF_SETUP",
        "stripe_payment_link_url": payment_link,
        "stripe_link_matches_configuration": True,
        "allowed_payer_modes": ["BYOK"],
        "default_payer_mode": "BYOK",
        "platform_budget_id_env": "",
        "platform_hard_limit_usd": "0",
        "default_model": model,
        "allowed_models": [model],
        "protection_level": "LEVEL_4_HOSTED_ONLY",
        "portable_seat_limit": 1,
        "portable_copy_risk_acknowledged": False,
        "max_input_chars": 12000,
        "max_history_messages": 12,
        "max_history_chars": 48000,
        "max_output_tokens": 256,
        "publish_confirmed": True,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_creator_can_direct_publish_second_product_without_code_or_file_transfer_and_cannot_overwrite_active(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)
    password = tmp_path / "creator-password.secret"
    session = tmp_path / "creator-session.secret"
    _private(password, CREATOR_PASSWORD)
    _private(session, CREATOR_SESSION_SECRET)

    monkeypatch.setenv("WEB_AI_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_CHECKOUT_STATE_DB", str(tmp_path / "checkout-state.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "1")
    monkeypatch.setenv("WEB_AI_CREATOR_AUTH_ENABLED", "1")
    monkeypatch.setenv("WEB_AI_CREATOR_PASSWORD_FILE", str(password))
    monkeypatch.setenv("WEB_AI_CREATOR_SESSION_SECRET_FILE", str(session))
    monkeypatch.setenv("WEB_AI_CREATOR_SESSION_TTL_SECONDS", "3600")

    for name in [
        "commercial_handoff", "commercial", "app", "entitlements", "handoff_tickets",
        "checkout_state", "cost_router", "byok_sessions", "creator_auth",
    ]:
        sys.modules.pop(name, None)

    gateway = importlib.import_module("commercial_handoff")
    client = TestClient(gateway.app)
    login = client.post(
        "/creator/login",
        data={"password": CREATOR_PASSWORD, "next": "/studio"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    options = client.get("/api/studio/options")
    assert options.status_code == 200, options.text
    model = options.json()["models"][0]

    first_slug = "direct-product-alpha"
    second_slug = "direct-product-beta"
    first = client.post(
        "/api/studio/publish",
        json=_payload(
            slug=first_slug,
            model=model,
            phrase="青いアルファ",
            payment_link="https://buy.stripe.com/direct-alpha",
        ),
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "PUBLISHED"
    assert first.json()["package_id"] == first_slug
    assert first.json()["active_packages"] == 1

    first_paths = {
        "package": config_dir / f"{first_slug}.json",
        "instructions": config_dir / f"{first_slug}.instructions.md",
        "knowledge": config_dir / f"{first_slug}.knowledge.md",
    }
    first_hashes = {name: _sha(path) for name, path in first_paths.items()}
    for path in first_paths.values():
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    first_package = json.loads(first_paths["package"].read_text(encoding="utf-8"))
    assert first_package["status"] == "active"
    assert first_package["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert first_package["knowledge"]["artifact_sha256"] == _sha(first_paths["knowledge"])

    second = client.post(
        "/api/studio/publish",
        json=_payload(
            slug=second_slug,
            model=model,
            phrase="赤いベータ",
            payment_link="https://buy.stripe.com/direct-beta",
        ),
    )
    assert second.status_code == 200, second.text
    assert second.json()["package_id"] == second_slug
    assert second.json()["active_packages"] == 2
    assert set(gateway.base.core.registry.apps) == {first_slug, second_slug}

    second_package_path = config_dir / f"{second_slug}.json"
    second_knowledge_path = config_dir / f"{second_slug}.knowledge.md"
    second_package = json.loads(second_package_path.read_text(encoding="utf-8"))
    assert second_package["status"] == "active"
    assert second_package["knowledge"]["artifact_sha256"] == _sha(second_knowledge_path)
    assert "赤いベータ" in second_knowledge_path.read_text(encoding="utf-8")
    assert "青いアルファ" in first_paths["knowledge"].read_text(encoding="utf-8")

    # Active authority cannot be silently replaced by a later Studio publish.
    overwrite = client.post(
        "/api/studio/publish",
        json=_payload(
            slug=first_slug,
            model=model,
            phrase="上書きされてはいけない",
            payment_link="https://buy.stripe.com/direct-alpha-replacement",
        ),
    )
    assert overwrite.status_code == 409, overwrite.text
    detail = overwrite.json()["detail"]
    assert detail["stage"] == "install"
    assert "Refusing to overwrite existing 'active' package" in detail["error"]
    assert {name: _sha(path) for name, path in first_paths.items()} == first_hashes
