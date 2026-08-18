from __future__ import annotations

import os
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import deployment_preflight_bound as bound


def _canonical_result(*, active_paid_packages: int = 1) -> dict:
    return {
        "ok": True,
        "status": "PASS",
        "findings": [],
        "warnings": [],
        "active_packages": active_paid_packages,
        "active_paid_packages": active_paid_packages,
    }


def test_bound_preflight_requires_commercial_env_file_and_live_sale_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bound, "run_preflight", lambda **_kwargs: _canonical_result())
    result = bound.run_bound_preflight(env={"WEB_AI_ROUTE_SURFACE": "commercial_bound:app"})
    codes = {item["code"] for item in result["findings"]}

    assert result["ok"] is False
    assert "COMMERCIAL_ENV_FILE_UNSET" in codes
    assert "ENTITLEMENT_COOKIE_SECRET_MISSING" in codes
    assert "STRIPE_SECRET_KEY_MISSING_OR_INVALID" in codes
    assert "STRIPE_WEBHOOK_SECRET_MISSING_OR_INVALID" in codes


def test_bound_preflight_passes_with_private_external_env_and_all_sale_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(bound, "run_preflight", lambda **_kwargs: _canonical_result())
    env_dir = tmp_path / "private-config"
    env_dir.mkdir(mode=0o700)
    env_file = env_dir / "webai.env"
    env_file.write_text("# values supplied through process env in this unit test\n", encoding="utf-8")
    os.chmod(env_file, 0o600)

    result = bound.run_bound_preflight(env={
        "WEB_AI_ROUTE_SURFACE": "commercial_bound:app",
        "WEB_AI_ENV_FILE": str(env_file),
        "WEB_AI_ENTITLEMENT_COOKIE_SECRET": "c" * 48,
        "WEB_AI_STRIPE_SECRET_KEY": "rk_test_buyer_only_bound",
        "WEB_AI_STRIPE_WEBHOOK_SECRET": "whsec_buyer_only_bound_test",
    })

    assert result["ok"] is True, result
    assert result["checkout_browser_binding"] is True
    assert result["commercial_env_file_safe"] is True
    assert result["live_sale_secrets_configured"] is True


def test_bound_preflight_does_not_require_sale_secrets_without_active_paid_packages(monkeypatch) -> None:
    monkeypatch.setattr(bound, "run_preflight", lambda **_kwargs: _canonical_result(active_paid_packages=0))
    result = bound.run_bound_preflight(env={"WEB_AI_ROUTE_SURFACE": "commercial_bound:app"})

    assert result["ok"] is True, result
    assert result["findings"] == []
