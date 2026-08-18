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
        json.dumps({"environment_authority": "SYSTEMD_UNSET_THEN_EXEC_REBIND_V1"}) + "\n",
        encoding="utf-8",
    )
    return service, manifest


def test_target_pin_is_exact_new_pr30_head_and_tree():
    assert m.TARGET_SHA == "89e80913a613cb98f9af685eb15ca7ed68505b7c"
    assert m.TARGET_TREE == "48ccfef494681f06bfe42e3686c9d083faeb087c"


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


def test_target_environment_authority_rejects_envfile_override_of_revision_shape(tmp_path):
    service, manifest = _write_candidate(tmp_path)
    text = service.read_text(encoding="utf-8")
    text = text.replace(
        "ExecStartPre=" + m._expected_preflight(FakeBase),
        "ExecStartPre=" + m._expected_preflight(FakeBase).replace(m.TARGET_SHA, "b" * 40),
    )
    service.write_text(text, encoding="utf-8")
    with pytest.raises(GateError, match="ExecStartPre authority mismatch"):
        m._validate_target_environment_authority(FakeBase, service, manifest)


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
    assert "ExecStart=/usr/bin/env PATH=/usr/bin:/bin PYTHONNOUSERSITE=1" in body
    assert "uvicorn" not in body


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


def test_stripe_acceptance_is_bounded_and_does_not_inherit_proxy_tls_or_loader_controls():
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
