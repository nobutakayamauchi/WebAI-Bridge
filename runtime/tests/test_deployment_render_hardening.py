from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_DIR / "deploy" / "render_deployment.py"
spec = importlib.util.spec_from_file_location("render_deployment_hardening", MODULE_PATH)
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)


def good(**overrides):
    values = {
        "domain": "ai.example.com",
        "runtime_dir": "/opt/webai-bridge/runtime",
        "state_dir": "/var/lib/webai-bridge",
        "revision": "a" * 40,
        "user": "webai",
        "group": "webai",
    }
    values.update(overrides)
    return values


def _unset_names(unit: str) -> set[str]:
    line = next(line for line in unit.splitlines() if line.startswith("UnsetEnvironment="))
    return set(line.split("=", 1)[1].split())


def test_systemd_path_injection_characters_are_rejected():
    for bad in [
        "/opt/webai bridge/runtime",
        "/opt/webai\nEnvironment=WEB_AI_STUDIO_ENABLED=1",
        "/opt/webai\truntime",
        "/opt/webai;runtime",
    ]:
        with pytest.raises(ValueError, match="unsupported characters"):
            render.validate_inputs(**good(runtime_dir=bad))


def test_runtime_and_state_must_not_overlap_either_direction():
    with pytest.raises(ValueError, match="must not overlap"):
        render.validate_inputs(**good(state_dir="/opt/webai-bridge/runtime/state"))
    with pytest.raises(ValueError, match="must not overlap"):
        render.validate_inputs(**good(state_dir="/opt/webai-bridge", runtime_dir="/opt/webai-bridge/runtime"))


def test_environment_file_cannot_override_locked_runtime_authority():
    unit = render.render_systemd(render.validate_inputs(**good()), creator_studio=True)
    names = _unset_names(unit)

    # systemd EnvironmentFile= overrides Environment=.  Therefore every
    # security/control value that must be immutable is removed in the final
    # systemd assembly step and rebound by the absolute /usr/bin/env command.
    for name in {
        "LD_PRELOAD",
        "LD_AUDIT",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONNOUSERSITE",
        "PATH",
        "WEB_AI_ENV_FILE",
        "WEB_AI_WORKING_DIRECTORY",
        "WEB_AI_ROUTE_SURFACE",
        "WEB_AI_CONFIG_DIR",
        "WEB_AI_DIAGNOSTICS_ENABLED",
        "WEB_AI_STUDIO_ENABLED",
        "WEB_AI_CREATOR_AUTH_ENABLED",
        "WEB_AI_CREATOR_PASSWORD_FILE",
        "WEB_AI_CREATOR_SESSION_SECRET_FILE",
        "WEB_AI_CREATOR_SESSION_TTL_SECONDS",
        "WEB_AI_ALLOW_INSECURE_HTTP",
        "DEPLOYED_REVISION",
    }:
        assert name in names

    pre = next(line for line in unit.splitlines() if line.startswith("ExecStartPre="))
    start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    for line in (pre, start):
        assert line.startswith("ExecStart")
        assert "/usr/bin/env PATH=/usr/bin:/bin PYTHONNOUSERSITE=1" in line
        assert "WEB_AI_ROUTE_SURFACE=commercial_handoff:app" in line
        assert "WEB_AI_CONFIG_DIR=/var/lib/webai-bridge/apps" in line
        assert "WEB_AI_STUDIO_ENABLED=1" in line
        assert "WEB_AI_CREATOR_AUTH_ENABLED=1" in line
        assert "WEB_AI_ALLOW_INSECURE_HTTP=0" in line
        assert "DEPLOYED_REVISION=" + ("a" * 40) in line


def test_no_execution_hazard_is_rebound_from_environment_file():
    unit = render.render_systemd(render.validate_inputs(**good()))
    names = _unset_names(unit)
    assert set(render.EXECUTION_HAZARD_ENV_KEYS).issubset(names)
    for line in unit.splitlines():
        if line.startswith(("ExecStartPre=", "ExecStart=")):
            assert "LD_PRELOAD=" not in line
            assert "LD_AUDIT=" not in line
            assert "LD_LIBRARY_PATH=" not in line
            assert "PYTHONPATH=" not in line
            assert "PYTHONHOME=" not in line
            assert "PYTHONUSERBASE=" not in line
            assert "PATH=/usr/bin:/bin" in line
            assert "PYTHONNOUSERSITE=1" in line


def test_world_writable_renderer_output_directory_is_rejected(tmp_path):
    os.chmod(tmp_path, 0o777)
    with pytest.raises(ValueError, match="world-writable"):
        render.write_outputs(render.validate_inputs(**good()), tmp_path)
