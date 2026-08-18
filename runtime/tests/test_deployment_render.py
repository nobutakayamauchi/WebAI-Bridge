from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_DIR / "deploy" / "render_deployment.py"
spec = importlib.util.spec_from_file_location("render_deployment", MODULE_PATH)
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)


def values():
    return render.validate_inputs(
        domain="ai.example.com",
        runtime_dir="/opt/webai-bridge/runtime",
        state_dir="/var/lib/webai-bridge",
        revision="a" * 40,
        user="webai",
        group="webai",
    )


def test_renderer_pins_commercial_entrypoint_revision_and_fail_closed_settings(tmp_path):
    written = render.write_outputs(values(), tmp_path)
    unit = Path(written["webai-bridge.service"]).read_text(encoding="utf-8")
    assert "Environment=DEPLOYED_REVISION=" + ("a" * 40) in unit
    assert "Environment=WEB_AI_ROUTE_SURFACE=commercial:app" in unit
    assert "Environment=WEB_AI_STUDIO_ENABLED=0" in unit
    assert "Environment=WEB_AI_CREATOR_AUTH_ENABLED=0" in unit
    assert "Environment=WEB_AI_DIAGNOSTICS_ENABLED=0" in unit
    assert "Environment=WEB_AI_ALLOW_INSECURE_HTTP=0" in unit
    assert "Environment=WEB_AI_HANDOFF_DB=/var/lib/webai-bridge/handoff.sqlite3" in unit
    assert "Environment=WEB_AI_CHECKOUT_STATE_DB=/var/lib/webai-bridge/checkout-state.sqlite3" in unit
    assert "ExecStartPre=/opt/webai-bridge/runtime/.venv/bin/python /opt/webai-bridge/runtime/deployment_preflight.py" in unit
    assert "ExecStart=/opt/webai-bridge/runtime/.venv/bin/uvicorn commercial:app" in unit
    assert "--forwarded-allow-ips=127.0.0.1" in unit
    assert "UMask=0077" in unit


def test_creator_studio_renderer_uses_handoff_surface_and_locked_creator_auth(tmp_path):
    written = render.write_outputs(values(), tmp_path, creator_studio=True)
    unit = Path(written["webai-bridge.service"]).read_text(encoding="utf-8")
    assert "Environment=WEB_AI_ROUTE_SURFACE=commercial_handoff:app" in unit
    assert "Environment=WEB_AI_STUDIO_ENABLED=1" in unit
    assert "Environment=WEB_AI_CREATOR_AUTH_ENABLED=1" in unit
    assert "Environment=WEB_AI_CREATOR_PASSWORD_FILE=/var/lib/webai-bridge/creator-password.secret" in unit
    assert "Environment=WEB_AI_CREATOR_SESSION_SECRET_FILE=/var/lib/webai-bridge/creator-session.secret" in unit
    assert "Environment=WEB_AI_CREATOR_SESSION_TTL_SECONDS=43200" in unit
    assert "ExecStartPre=/opt/webai-bridge/runtime/.venv/bin/python /opt/webai-bridge/runtime/deployment_preflight_handoff.py" in unit
    assert "ExecStart=/opt/webai-bridge/runtime/.venv/bin/uvicorn commercial_handoff:app" in unit
    assert "WEB_AI_ALLOW_INSECURE_HTTP=0" in unit

    manifest = json.loads(Path(written["deployment-manifest.json"]).read_text(encoding="utf-8"))
    assert manifest["schema"] == "webai-deployment-v1"
    assert manifest["profile"] == "CREATOR_STUDIO_COMMERCIAL_V1"
    assert manifest["route_surface"] == "commercial_handoff:app"
    assert manifest["creator_studio_enabled"] is True
    assert manifest["creator_auth_required"] is True
    assert manifest["creator_auth_mode"] == "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1"
    assert manifest["creator_auth_files"] == {
        "password": "/var/lib/webai-bridge/creator-password.secret",
        "session_secret": "/var/lib/webai-bridge/creator-session.secret",
    }
    assert manifest["secret_values_in_manifest"] is False


def test_renderer_keeps_state_outside_runtime_and_outputs_no_secrets(tmp_path):
    written = render.write_outputs(values(), tmp_path)
    manifest = json.loads(Path(written["deployment-manifest.json"]).read_text(encoding="utf-8"))
    assert manifest["state_dir"] == "/var/lib/webai-bridge"
    assert manifest["runtime_dir"] == "/opt/webai-bridge/runtime"
    assert manifest["secret_values_in_manifest"] is False
    unit = Path(written["webai-bridge.service"]).read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in unit
    assert "X-WebAI-Entitlement" not in unit
    assert "sk-" not in unit
    assert "whsec_" not in unit


def test_caddy_output_uses_only_expected_domain_and_local_upstream(tmp_path):
    written = render.write_outputs(values(), tmp_path)
    caddy = Path(written["Caddyfile"]).read_text(encoding="utf-8")
    assert caddy.startswith("ai.example.com {")
    assert "reverse_proxy 127.0.0.1:8080" in caddy
    assert "http://" not in caddy


def test_renderer_outputs_are_owner_only(tmp_path):
    written = render.write_outputs(values(), tmp_path)
    for path in written.values():
        mode = stat.S_IMODE(Path(path).stat().st_mode)
        assert mode & 0o077 == 0


@pytest.mark.parametrize(
    "field,bad",
    [
        ("domain", "http://bad.example.com"),
        ("domain", "localhost"),
        ("runtime_dir", "relative/runtime"),
        ("state_dir", "relative/state"),
        ("revision", "deadbeef"),
        ("user", "Bad User"),
        ("group", "bad/group"),
    ],
)
def test_invalid_deployment_identifiers_are_rejected(field, bad):
    kwargs = {
        "domain": "ai.example.com",
        "runtime_dir": "/opt/webai-bridge/runtime",
        "state_dir": "/var/lib/webai-bridge",
        "revision": "a" * 40,
        "user": "webai",
        "group": "webai",
    }
    kwargs[field] = bad
    with pytest.raises(ValueError):
        render.validate_inputs(**kwargs)


def test_state_directory_inside_runtime_is_rejected():
    with pytest.raises(ValueError, match="must not overlap"):
        render.validate_inputs(
            domain="ai.example.com",
            runtime_dir="/opt/webai-bridge/runtime",
            state_dir="/opt/webai-bridge/runtime/state",
            revision="a" * 40,
            user="webai",
            group="webai",
        )


def test_output_symlink_is_not_replaced(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("do-not-touch", encoding="utf-8")
    target = tmp_path / "webai-bridge.service"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unsupported in test environment")
    with pytest.raises(ValueError, match="symlink"):
        render.write_outputs(values(), tmp_path)
    assert outside.read_text(encoding="utf-8") == "do-not-touch"
