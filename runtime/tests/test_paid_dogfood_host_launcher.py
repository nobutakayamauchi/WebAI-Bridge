from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_DIR / "deploy"
MODULE_PATH = DEPLOY_DIR / "paid_dogfood_host.py"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))
spec = importlib.util.spec_from_file_location("paid_dogfood_host", MODULE_PATH)
launcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(launcher)


def test_paid_env_uses_external_config_and_locks_public_controls(tmp_path):
    runtime = tmp_path / "repo" / "runtime"
    runtime.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    config = state / "apps"
    config.mkdir()
    env = launcher.build_paid_env(
        base={
            "WEB_AI_STUDIO_ENABLED": "1",
            "WEB_AI_DIAGNOSTICS_ENABLED": "1",
            "WEB_AI_ALLOW_INSECURE_HTTP": "1",
            "WEB_AI_CONFIG_DIR": str(runtime / "apps"),
        },
        runtime_dir=runtime,
        state_dir=state,
        config_dir=config,
        revision="a" * 40,
    )
    assert env["WEB_AI_SERVICE_UNIT"] == "manual-paid-dogfood"
    assert env["WEB_AI_ROUTE_SURFACE"] == "commercial:app"
    assert env["WEB_AI_CONFIG_DIR"] == str(config.resolve())
    assert env["WEB_AI_STUDIO_ENABLED"] == "0"
    assert env["WEB_AI_DIAGNOSTICS_ENABLED"] == "0"
    assert env["WEB_AI_ALLOW_INSECURE_HTTP"] == "0"
    assert env["WEB_AI_ENTITLEMENT_DB"] == str((state / "entitlements.sqlite3").resolve())
    assert env["WEB_AI_LEDGER_PATH"] == str((state / "ledger.sqlite3").resolve())
    assert env["WEB_AI_ENTITLEMENT_DB"] != env["WEB_AI_LEDGER_PATH"]


def test_private_child_dir_is_owner_only_and_cannot_escape_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    child = launcher.ensure_private_child_dir(state / "apps", parent=state)
    assert stat.S_IMODE(child.stat().st_mode) & 0o077 == 0

    with pytest.raises(ValueError, match="inside paid dogfood state"):
        launcher.ensure_private_child_dir(tmp_path / "other", parent=state)


def test_paid_env_requires_exact_full_revision(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    config = state / "apps"
    runtime.mkdir()
    config.mkdir(parents=True)
    with pytest.raises(ValueError, match="40-character"):
        launcher.build_paid_env(
            base={},
            runtime_dir=runtime,
            state_dir=state,
            config_dir=config,
            revision="deadbeef",
        )


def test_json_preflight_requires_exactly_one_active_paid_package(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    fake_python = tmp_path / "python"
    fake_python.write_text("", encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = '{"ok":true,"active_packages":1,"active_paid_packages":1,"findings":[]}'

    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: Completed())
    result = launcher.run_json_preflight(python=fake_python, runtime_dir=runtime, env={})
    assert result["active_paid_packages"] == 1

    class Wrong:
        returncode = 0
        stdout = '{"ok":true,"active_packages":1,"active_paid_packages":0,"findings":[]}'

    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: Wrong())
    with pytest.raises(RuntimeError, match="exactly one active package"):
        launcher.run_json_preflight(python=fake_python, runtime_dir=runtime, env={})
