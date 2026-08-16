from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_DIR / "deploy" / "free_dogfood_host.py"
spec = importlib.util.spec_from_file_location("free_dogfood_host", MODULE_PATH)
launcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(launcher)


def test_locked_env_overrides_unsafe_parent_values(tmp_path):
    runtime = tmp_path / "repo" / "runtime"
    runtime.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    env = launcher.build_locked_env(
        base={
            "WEB_AI_STUDIO_ENABLED": "1",
            "WEB_AI_DIAGNOSTICS_ENABLED": "1",
            "WEB_AI_ALLOW_INSECURE_HTTP": "1",
            "WEB_AI_ROUTE_SURFACE": "app:app",
        },
        runtime_dir=runtime,
        state_dir=state,
        revision="a" * 40,
    )
    assert env["WEB_AI_STUDIO_ENABLED"] == "0"
    assert env["WEB_AI_DIAGNOSTICS_ENABLED"] == "0"
    assert env["WEB_AI_ALLOW_INSECURE_HTTP"] == "0"
    assert env["WEB_AI_ROUTE_SURFACE"] == "commercial:app"
    assert env["WEB_AI_CONFIG_DIR"] == str((runtime / "apps").resolve())
    assert env["DEPLOYED_REVISION"] == "a" * 40
    assert env["WEB_AI_ENTITLEMENT_DB"] != env["WEB_AI_LEDGER_PATH"]


def test_private_state_dir_is_owner_only_and_outside_runtime(tmp_path):
    runtime = tmp_path / "repo" / "runtime"
    runtime.mkdir(parents=True)
    state = launcher.ensure_private_state_dir(tmp_path / "state", runtime_dir=runtime)
    assert stat.S_IMODE(state.stat().st_mode) & 0o077 == 0

    with pytest.raises(ValueError, match="overlap"):
        launcher.ensure_private_state_dir(runtime / "state", runtime_dir=runtime)

    with pytest.raises(ValueError, match="overlap"):
        launcher.ensure_private_state_dir(runtime.parent, runtime_dir=runtime)


def test_state_symlink_is_rejected(tmp_path):
    runtime = tmp_path / "repo" / "runtime"
    runtime.mkdir(parents=True)
    real = tmp_path / "real-state"
    real.mkdir()
    link = tmp_path / "state-link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unsupported in test environment")
    with pytest.raises(ValueError, match="symlink"):
        launcher.ensure_private_state_dir(link, runtime_dir=runtime)


def test_dogfood_port_is_unprivileged_and_bounded():
    assert launcher.validate_port(8080) == 8080
    for bad in [0, 80, 1023, 65536, 99999]:
        with pytest.raises(ValueError):
            launcher.validate_port(bad)


def test_requirements_digest_changes_with_content(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("a==1\n", encoding="utf-8")
    first = launcher.requirements_digest(req)
    req.write_text("a==2\n", encoding="utf-8")
    second = launcher.requirements_digest(req)
    assert first != second
    assert len(first) == 64


def test_cloudflared_hint_never_embeds_secrets(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/cloudflared")
    hint = launcher.cloudflared_hint(8080)
    assert hint["installed"] is True
    assert hint["next_command"] == "cloudflared tunnel --url http://127.0.0.1:8080"
    assert "token" not in hint["next_command"].lower()


def test_invalid_revision_is_rejected_before_env_build(tmp_path):
    runtime = tmp_path / "runtime"
    state = tmp_path / "state"
    runtime.mkdir()
    state.mkdir()
    with pytest.raises(ValueError, match="revision"):
        launcher.build_locked_env(
            base={},
            runtime_dir=runtime,
            state_dir=state,
            revision="deadbeef",
        )
