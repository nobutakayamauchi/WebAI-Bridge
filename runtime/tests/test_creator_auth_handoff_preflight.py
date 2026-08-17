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


def test_handoff_preflight_allows_studio_only_when_creator_auth_is_valid(tmp_path: Path, monkeypatch) -> None:
    password = tmp_path / "creator-password.secret"
    session = tmp_path / "creator-session.secret"
    _write_private(password, "creator-password-abcdefghijklmnopqrstuvwxyz")
    _write_private(session, "creator-session-secret-abcdefghijklmnopqrstuvwxyz0123456789")
    monkeypatch.setattr(handoff, "run_preflight", lambda **kwargs: _canonical_public_studio_failure())
    monkeypatch.setattr(handoff, "_package_text_findings", lambda source: (set(), []))

    env = {
        "WEB_AI_ROUTE_SURFACE": "commercial_handoff:app",
        "WEB_AI_STUDIO_ENABLED": "1",
        "WEB_AI_CREATOR_AUTH_ENABLED": "1",
        "WEB_AI_CREATOR_PASSWORD_FILE": str(password),
        "WEB_AI_CREATOR_SESSION_SECRET_FILE": str(session),
        "WEB_AI_CREATOR_SESSION_TTL_SECONDS": "43200",
    }
    result = handoff.run_handoff_preflight(env=env)
    assert result["ok"] is True
    assert result["creator_studio_enabled"] is True
    assert result["creator_auth_protected"] is True
    assert result["creator_auth_mode"] == "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1"
    assert result["findings"] == []

    env["WEB_AI_CREATOR_AUTH_ENABLED"] = "0"
    result = handoff.run_handoff_preflight(env=env)
    codes = {item["code"] for item in result["findings"]}
    assert result["ok"] is False
    assert result["creator_auth_protected"] is False
    assert "PUBLIC_STUDIO_ENABLED" in codes
    assert "CREATOR_AUTH_DISABLED" in codes
