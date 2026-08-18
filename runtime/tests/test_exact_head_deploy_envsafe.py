from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_envsafe.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_envsafe", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GateError(RuntimeError):
    pass


class FakeBase:
    GateError = GateError
    TARGET_SHA = m.TARGET_SHA
    TARGET_TREE = m.TARGET_TREE
    DOMAIN = "webai.140-238-62-74.sslip.io"
    RELEASE = Path("/opt/webai-bridge-releases") / m.TARGET_SHA
    VENV = Path("/opt/webai-bridge-venvs") / m.TARGET_SHA
    STATE = Path("/var/lib/webai-bridge")
    ENV_FILE = Path("/etc/webai-bridge/webai-bridge.env")

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


def _service_text(base=FakeBase) -> str:
    fixed = m._fixed_runtime_environment(base)
    fixed_lines = "".join(f"Environment={key}={value}\n" for key, value in fixed.items())
    unset = "UnsetEnvironment=" + " ".join(m._protected_environment_names(base))
    return "".join(
        [
            "[Unit]\nDescription=test\n\n[Service]\nType=simple\n",
            "User=webai\nGroup=webai\nUMask=0077\n",
            f"WorkingDirectory={base.RELEASE}/runtime\n",
            f"EnvironmentFile=-{base.ENV_FILE}\n",
            fixed_lines,
            unset + "\n",
            "ExecStartPre=" + m._expected_preflight(base) + "\n",
            "ExecStart=" + m._expected_start(base) + "\n",
            "NoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\n",
            f"ReadWritePaths={base.STATE}\n",
        ]
    )


def _write_candidate(tmp_path: Path) -> tuple[Path, Path]:
    service = tmp_path / "webai-bridge.service"
    manifest = tmp_path / "deployment-manifest.json"
    service.write_text(_service_text(), encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "environment_authority": "SYSTEMD_UNSET_THEN_EXEC_REBIND_V1",
                "server_authority": m.EXPECTED_SERVER_AUTHORITY,
                "runtime_policy": m.EXPECTED_RUNTIME_POLICY,
            }
        ) + "\n",
        encoding="utf-8",
    )
    return service, manifest


def test_target_pin_is_exact_frozen_pr30_head_and_tree():
    assert m.TARGET_SHA == "5fd4c791e636464f1a3b5195a3e1048b505d6de5"
    assert m.TARGET_TREE == "155dc692264a8f7edcd74b0eaff8cba28b0f11ef"


def test_target_environment_authority_accepts_exact_final_unset_and_exec_rebind(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    m._validate_target_environment_authority(FakeBase, service, manifest)


def test_target_environment_authority_rejects_missing_proxy_or_tls_sanitizer(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    text = service.read_text(encoding="utf-8")
    text = text.replace(" HTTPS_PROXY", "", 1)
    service.write_text(text, encoding="utf-8")
    with pytest.raises(GateError, match="final environment sanitization"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


def test_target_environment_authority_rejects_provider_or_server_hazard_omission(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    text = service.read_text(encoding="utf-8")
    text = text.replace(" OPENAI_BASE_URL", "", 1).replace(" WEB_CONCURRENCY", "", 1)
    service.write_text(text, encoding="utf-8")
    with pytest.raises(GateError, match="final environment sanitization"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


def test_target_environment_authority_rejects_revision_exec_drift(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    text = service.read_text(encoding="utf-8")
    text = text.replace(
        "ExecStartPre=" + m._expected_preflight(FakeBase),
        "ExecStartPre=" + m._expected_preflight(FakeBase).replace(m.TARGET_SHA, "b" * 40),
    )
    service.write_text(text, encoding="utf-8")
    with pytest.raises(GateError, match="ExecStartPre authority mismatch"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


def test_target_environment_authority_rejects_runtime_policy_manifest_drift(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["runtime_policy"]["handoff_ttl_seconds"] = 9999
    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(GateError, match="runtime policy authority mismatch"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


def test_target_environment_authority_rejects_server_authority_drift(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["server_authority"] = "CLI_MULTIWORKER"
    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(GateError, match="server authority mismatch"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


def test_fixed_runtime_policy_is_removed_from_envfile_authority_and_rebound():
    fixed = m._fixed_runtime_environment(FakeBase)
    assert fixed["WEB_AI_PRICING_FILE"] == f"{FakeBase.RELEASE}/runtime/pricing.json"
    assert fixed["WEB_AI_REQUESTS_PER_MINUTE"] == "20"
    assert fixed["WEB_AI_BYOK_SESSION_TTL_SECONDS"] == "900"
    assert fixed["WEB_AI_BYOK_SESSION_MAX"] == "1000"
    assert fixed["WEB_AI_HANDOFF_TTL_SECONDS"] == "600"
    assert fixed["WEB_AI_ENTITLEMENT_COOKIE_MAX_AGE_SECONDS"] == "31536000"
    protected = set(m._protected_environment_names(FakeBase))
    assert set(fixed).issubset(protected)
    pre = m._expected_preflight(FakeBase)
    start = m._expected_start(FakeBase)
    for key, value in fixed.items():
        assert f"{key}={value}" in pre
        assert f"{key}={value}" in start


def test_expected_start_uses_pinned_programmatic_single_worker_launcher_surface():
    start = m._expected_start(FakeBase)
    assert f"{FakeBase.RELEASE}/runtime/.venv/bin/python" in start
    assert f"{FakeBase.RELEASE}/runtime/production_server.py" in start
    assert "commercial_handoff:app" in start
    assert "--no-access-log" in start
    assert "/bin/uvicorn" not in start


def test_scoped_git_trust_is_preflight_only_and_target_start_stays_exact(tmp_path):
    service, _manifest = _write_candidate(tmp_path)
    raw_hash = FakeBase.sha256(service)
    returned = m._scope_preflight_git_trust(FakeBase, service)
    assert returned == raw_hash
    lines = service.read_text(encoding="utf-8").splitlines()
    pre = next(line for line in lines if line.startswith("ExecStartPre="))
    start = next(line for line in lines if line.startswith("ExecStart="))
    assert "GIT_CONFIG_KEY_0=safe.directory" in pre
    assert f"GIT_CONFIG_VALUE_0={FakeBase.RELEASE}" in pre
    assert "GIT_CONFIG_KEY_0=safe.directory" not in start
    assert start == "ExecStart=" + m._expected_start(FakeBase)


def test_candidate_preflight_preserves_final_unset_and_has_total_timeout(tmp_path):
    service, _manifest = _write_candidate(tmp_path)
    captured: dict[str, str] = {}

    class Base(FakeBase):
        @staticmethod
        def transient(name: str, body: str) -> None:
            captured["name"] = name
            captured["body"] = body

    m._candidate_preflight(Base, service)
    body = captured["body"]
    assert f"TimeoutStartSec={m.PREFLIGHT_TIMEOUT_SECONDS}" in body
    assert "UnsetEnvironment=" in body
    assert "HTTPS_PROXY" in body
    assert "SSL_CERT_FILE" in body
    assert "GIT_DIR" in body
    assert "OPENAI_BASE_URL" in body
    assert "WEB_CONCURRENCY" in body
    assert "WEB_AI_REQUESTS_PER_MINUTE" in body
    assert "ExecStart=/usr/bin/env PATH=/usr/bin:/bin PYTHONNOUSERSITE=1" in body
    assert "production_server.py" not in body


def test_candidate_preflight_fails_closed_if_unset_is_missing(tmp_path):
    service, _manifest = _write_candidate(tmp_path)
    text = "\n".join(
        line for line in service.read_text(encoding="utf-8").splitlines()
        if not line.startswith("UnsetEnvironment=")
    ) + "\n"
    service.write_text(text, encoding="utf-8")

    class Base(FakeBase):
        @staticmethod
        def transient(name: str, body: str) -> None:
            raise AssertionError("must not start transient unit")

    with pytest.raises(GateError, match="lost final environment sanitization"):
        m._candidate_preflight(Base, service)


def test_stripe_acceptance_is_bounded_and_does_not_inherit_execution_or_network_trust_controls():
    captured: dict[str, str] = {}

    class Base(FakeBase):
        @staticmethod
        def transient(name: str, body: str) -> None:
            captured["name"] = name
            captured["body"] = body

    m._stripe_acceptance(Base)
    body = captured["body"]
    assert f"TimeoutStartSec={m.STRIPE_ACCEPTANCE_TIMEOUT_SECONDS}" in body
    assert f"--timeout {m.STRIPE_HTTP_TIMEOUT_SECONDS}" in body
    unset = next(line for line in body.splitlines() if line.startswith("UnsetEnvironment="))
    for name in (
        "LD_PRELOAD",
        "PYTHONPATH",
        "GIT_DIR",
        "HTTPS_PROXY",
        "https_proxy",
        "SSL_CERT_FILE",
        "OPENSSL_CONF",
        "SSLKEYLOGFILE",
        "OPENAI_BASE_URL",
        "OPENAI_CUSTOM_HEADERS",
        "WEB_CONCURRENCY",
        "UVICORN_WORKERS",
        "WEB_AI_REQUESTS_PER_MINUTE",
        "WEB_AI_BYOK_SESSION_TTL_SECONDS",
    ):
        assert name in unset.split("=", 1)[1].split()
    assert "WEB_AI_STRIPE_SECRET_KEY" not in unset
    exec_start = next(line for line in body.splitlines() if line.startswith("ExecStart="))
    assert exec_start.startswith("ExecStart=/usr/bin/env PATH=/usr/bin:/bin PYTHONNOUSERSITE=1")
    assert "stripe_external_acceptance.py" in exec_start


def test_pin_target_updates_release_and_venv_paths():
    class Base:
        TARGET_SHA = "0" * 40
        TARGET_TREE = "1" * 40
        RELEASE = Path("/old-release")
        VENV = Path("/old-venv")

    m._pin_target(Base)
    assert Base.TARGET_SHA == m.TARGET_SHA
    assert Base.TARGET_TREE == m.TARGET_TREE
    assert Base.RELEASE == Path("/opt/webai-bridge-releases") / m.TARGET_SHA
    assert Base.VENV == Path("/opt/webai-bridge-venvs") / m.TARGET_SHA
