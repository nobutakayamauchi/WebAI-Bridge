from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/render_deployment.py"
spec = importlib.util.spec_from_file_location("render_deployment_runtime_policy", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _values():
    return m.validate_inputs(
        domain="ai.example.com",
        runtime_dir="/opt/webai-bridge/runtime",
        state_dir="/var/lib/webai-bridge",
        revision="a" * 40,
        user="webai",
        group="webai",
    )


def test_runtime_security_policy_is_fixed_not_secret_env_authority():
    fixed = m._fixed_runtime_environment(_values(), creator_studio=True)
    assert fixed["WEB_AI_PRICING_FILE"] == "/opt/webai-bridge/runtime/pricing.json"
    assert fixed["WEB_AI_REQUESTS_PER_MINUTE"] == "20"
    assert fixed["WEB_AI_BYOK_SESSION_TTL_SECONDS"] == "900"
    assert fixed["WEB_AI_BYOK_SESSION_MAX"] == "1000"
    assert fixed["WEB_AI_HANDOFF_TTL_SECONDS"] == "600"
    assert fixed["WEB_AI_ENTITLEMENT_COOKIE_MAX_AGE_SECONDS"] == "31536000"

    unit = m.render_systemd(_values(), creator_studio=True)
    unset = next(line for line in unit.splitlines() if line.startswith("UnsetEnvironment="))
    unset_names = set(unset.split("=", 1)[1].split())
    for name, value in fixed.items():
        assert name in unset_names
        assert f"{name}={value}" in next(
            line for line in unit.splitlines() if line.startswith("ExecStart=")
        )


def test_manifest_records_runtime_policy_without_secret_values():
    manifest = json.loads(m.render_manifest(_values(), creator_studio=True))
    assert manifest["runtime_policy"] == {
        "requests_per_minute": 20,
        "byok_session_ttl_seconds": 900,
        "byok_session_max": 1000,
        "handoff_ttl_seconds": 600,
        "entitlement_cookie_max_age_seconds": 31536000,
    }
    assert manifest["secret_values_in_manifest"] is False
