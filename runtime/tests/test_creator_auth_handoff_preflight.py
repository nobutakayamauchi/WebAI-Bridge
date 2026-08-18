from __future__ import annotations

import os
from pathlib import Path

import deployment_preflight_handoff as handoff


def _write_private(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _canonical_public_studio_failure() -> dict:
    return {
        "ok": False,
        "status": "FAIL",
        "active_packages": 1,
        "active_paid_packages": 1,
        "findings": [{
            "code": "PUBLIC_STUDIO_ENABLED",
            "scope": "deployment",
            "message": "Creator Studio must remain off on the public commercial runtime",
        }],
        "warnings": [],
    }


def _good_env(tmp_path: Path) -> dict[str, str]:
    password = tmp_path / "creator-password.secret"
    session = tmp_path / "creator-session.secret"
    _write_private(password, "creator-password-abcdefghijklmnopqrstuvwxyz")
    _write_private(session, "creator-session-secret-abcdefghijklmnopqrstuvwxyz0123456789")
    return {
        "WEB_AI_ROUTE_SURFACE": "commercial_handoff:app",
        "WEB_AI_STUDIO_ENABLED": "1",
        "WEB_AI_CREATOR_AUTH_ENABLED": "1",
        "WEB_AI_CREATOR_PASSWORD_FILE": str(password),
        "WEB_AI_CREATOR_SESSION_SECRET_FILE": str(session),
        "WEB_AI_CREATOR_SESSION_TTL_SECONDS": "43200",
        "WEB_AI_ENTITLEMENT_COOKIE_SECRET": "c" * 48,
        "WEB_AI_STRIPE_SECRET_KEY": "rk_live_creator_preflight_test",
        "WEB_AI_STRIPE_WEBHOOK_SECRET": "whsec_creator_preflight_test",
    }


def test_handoff_preflight_allows_studio_only_when_creator_auth_and_live_sale_secrets_are_valid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handoff, "run_preflight", lambda **kwargs: _canonical_public_studio_failure())
    monkeypatch.setattr(handoff, "_package_text_findings", lambda source: (set(), []))

    env = _good_env(tmp_path)
    result = handoff.run_handoff_preflight(env=env)
    assert result["ok"] is True
    assert result["creator_studio_enabled"] is True
    assert result["creator_auth_protected"] is True
    assert result["creator_auth_mode"] == "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1"
    assert result["live_sale_secrets_configured"] is True
    assert result["findings"] == []

    env["WEB_AI_CREATOR_AUTH_ENABLED"] = "0"
    result = handoff.run_handoff_preflight(env=env)
    codes = {item["code"] for item in result["findings"]}
    assert result["ok"] is False
    assert result["creator_auth_protected"] is False
    assert "PUBLIC_STUDIO_ENABLED" in codes
    assert "CREATOR_AUTH_DISABLED" in codes


def test_handoff_preflight_fails_before_start_when_paid_sale_secrets_are_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(handoff, "run_preflight", lambda **kwargs: _canonical_public_studio_failure())
    monkeypatch.setattr(handoff, "_package_text_findings", lambda source: (set(), []))
    env = _good_env(tmp_path)
    env.pop("WEB_AI_ENTITLEMENT_COOKIE_SECRET")
    env.pop("WEB_AI_STRIPE_SECRET_KEY")
    env.pop("WEB_AI_STRIPE_WEBHOOK_SECRET")

    result = handoff.run_handoff_preflight(env=env)
    codes = {item["code"] for item in result["findings"]}
    assert result["ok"] is False
    assert result["live_sale_secrets_configured"] is False
    assert {
        "ENTITLEMENT_COOKIE_SECRET_MISSING",
        "STRIPE_SECRET_KEY_MISSING_OR_INVALID",
        "STRIPE_WEBHOOK_SECRET_MISSING",
    } <= codes


def test_handoff_preflight_does_not_require_paid_sale_secrets_without_active_paid_package(tmp_path: Path, monkeypatch) -> None:
    base = _canonical_public_studio_failure()
    base["active_paid_packages"] = 0
    monkeypatch.setattr(handoff, "run_preflight", lambda **kwargs: base)
    monkeypatch.setattr(handoff, "_package_text_findings", lambda source: (set(), []))
    env = _good_env(tmp_path)
    env.pop("WEB_AI_ENTITLEMENT_COOKIE_SECRET")
    env.pop("WEB_AI_STRIPE_SECRET_KEY")
    env.pop("WEB_AI_STRIPE_WEBHOOK_SECRET")

    result = handoff.run_handoff_preflight(env=env)
    assert result["ok"] is True
    assert result["live_sale_secrets_configured"] is True
