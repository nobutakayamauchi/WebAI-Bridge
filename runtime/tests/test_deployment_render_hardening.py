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


def test_optional_environment_file_is_loaded_before_locked_security_values():
    unit = render.render_systemd(render.validate_inputs(**good()))
    env_file = unit.index("EnvironmentFile=-/etc/webai-bridge/webai-bridge.env")
    locked = unit.index("Environment=WEB_AI_STUDIO_ENABLED=0")
    revision = unit.index("Environment=DEPLOYED_REVISION=" + ("a" * 40))
    assert env_file < locked
    assert env_file < revision


def test_world_writable_renderer_output_directory_is_rejected(tmp_path):
    os.chmod(tmp_path, 0o777)
    with pytest.raises(ValueError, match="world-writable"):
        render.write_outputs(render.validate_inputs(**good()), tmp_path)
