from __future__ import annotations

import importlib
import os
import stat
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from creator_auth import (
    COOKIE_NAME,
    CreatorAuthConfig,
    creator_auth_findings,
    password_matches,
    sign_creator_session,
    verify_creator_session,
)

RUNTIME_DIR = Path(__file__).resolve().parents[1]


def _write_private(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def test_creator_session_expires_and_password_rotation_invalidates_cookie() -> None:
    config = CreatorAuthConfig(
        password="creator-password-abcdefghijklmnopqrstuvwxyz",
        session_secret="session-secret-abcdefghijklmnopqrstuvwxyz0123456789",
        session_ttl_seconds=3600,
        auth_id="auth-v1",
    )
    cookie = sign_creator_session(config=config, now=1_000_000)
    assert verify_creator_session(config=config, cookie=cookie, now=1_000_001)
    assert not verify_creator_session(config=config, cookie=cookie, now=1_003_601)
    rotated = CreatorAuthConfig(
        password=config.password + "-rotated",
        session_secret=config.session_secret,
        session_ttl_seconds=3600,
        auth_id="auth-v2",
    )
    assert not verify_creator_session(config=rotated, cookie=cookie, now=1_000_001)
    assert password_matches(config=config, supplied=config.password)
    assert not password_matches(config=config, supplied="wrong-password")


def test_creator_auth_preflight_fails_closed_on_missing_or_open_secrets(tmp_path: Path) -> None:
    env = {"WEB_AI_STUDIO_ENABLED": "1", "WEB_AI_CREATOR_AUTH_ENABLED": "0"}
    findings = creator_auth_findings(env=env, runtime_dir=RUNTIME_DIR)
    assert {item["code"] for item in findings} == {"CREATOR_AUTH_DISABLED"}

    password = tmp_path / "creator-password.secret"
    session = tmp_path / "creator-session.secret"
    _write_private(password, "creator-password-abcdefghijklmnopqrstuvwxyz")
    _write_private(session, "creator-session-secret-abcdefghijklmnopqrstuvwxyz0123456789")
    env = {
        "WEB_AI_STUDIO_ENABLED": "1",
        "WEB_AI_CREATOR_AUTH_ENABLED": "1",
        "WEB_AI_CREATOR_PASSWORD_FILE": str(password),
        "WEB_AI_CREATOR_SESSION_SECRET_FILE": str(session),
        "WEB_AI_CREATOR_SESSION_TTL_SECONDS": "43200",
    }
    assert creator_auth_findings(env=env, runtime_dir=RUNTIME_DIR) == []

    os.chmod(password, 0o644)
    findings = creator_auth_findings(env=env, runtime_dir=RUNTIME_DIR)
    assert "CREATOR_PASSWORD_FILE_PERMISSIONS_TOO_OPEN" in {item["code"] for item in findings}
    assert stat.S_IMODE(password.stat().st_mode) == 0o644


def test_public_studio_requires_creator_login_and_uses_secure_cookie(tmp_path: Path, monkeypatch) -> None:
    password_value = "creator-password-abcdefghijklmnopqrstuvwxyz"
    password = tmp_path / "creator-password.secret"
    session = tmp_path / "creator-session.secret"
    _write_private(password, password_value)
    _write_private(session, "creator-session-secret-abcdefghijklmnopqrstuvwxyz0123456789")
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)

    monkeypatch.setenv("WEB_AI_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_CHECKOUT_STATE_DB", str(tmp_path / "checkout-state.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "0")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", "e" * 48)
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "1")
    monkeypatch.setenv("WEB_AI_CREATOR_AUTH_ENABLED", "1")
    monkeypatch.setenv("WEB_AI_CREATOR_PASSWORD_FILE", str(password))
    monkeypatch.setenv("WEB_AI_CREATOR_SESSION_SECRET_FILE", str(session))
    monkeypatch.setenv("WEB_AI_CREATOR_SESSION_TTL_SECONDS", "3600")

    for name in [
        "commercial_handoff", "commercial", "app", "entitlements", "handoff_tickets",
        "checkout_state", "cost_router", "byok_sessions", "knowledge_studio",
    ]:
        sys.modules.pop(name, None)

    gateway = importlib.import_module("commercial_handoff")
    client = TestClient(gateway.app, base_url="https://testserver")

    denied_page = client.get("/studio", follow_redirects=False)
    assert denied_page.status_code == 303
    assert denied_page.headers["location"].startswith("/creator/login")
    assert client.get("/api/studio/options").status_code == 401

    login_page = client.get("/creator/login")
    assert login_page.status_code == 200
    assert "Creator access key" in login_page.text
    assert "Cache-Control" in login_page.headers

    wrong = client.post(
        "/creator/login",
        data={"password": "wrong-password", "next": "/studio"},
        follow_redirects=False,
    )
    assert wrong.status_code == 401
    assert COOKIE_NAME not in wrong.headers.get("set-cookie", "")

    login = client.post(
        "/creator/login",
        data={"password": password_value, "next": "/studio"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/studio"
    set_cookie = login.headers.get("set-cookie", "")
    assert COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie

    studio = client.get("/studio")
    assert studio.status_code == 200
    assert "Knowledge" in studio.text
    options = client.get("/api/studio/options")
    assert options.status_code == 200
    assert options.json()["knowledge_backend"] == "PACKAGE_TEXT"

    logout = client.post("/creator/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert client.get("/api/studio/options").status_code == 401
