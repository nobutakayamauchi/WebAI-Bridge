from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_hostsafe.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_hostsafe", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GateError(RuntimeError):
    pass


def fake_base(release: Path):
    import hashlib

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return SimpleNamespace(RELEASE=release, GateError=GateError, sha256=sha256)


def service_text(release: Path) -> str:
    return "\n".join([
        "[Unit]",
        "Description=test",
        "[Service]",
        "User=webai",
        f"WorkingDirectory={release}/runtime",
        f"ExecStartPre={release}/runtime/.venv/bin/python {release}/runtime/deployment_preflight_handoff.py",
        f"ExecStart={release}/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log",
        "ProtectSystem=strict",
        "",
    ])


def test_scoped_git_trust_wraps_only_execstartpre(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(service_text(release), encoding="utf-8")
    base = fake_base(release)
    raw_hash = base.sha256(service)

    returned = m._scope_preflight_git_trust(base, service)
    text = service.read_text(encoding="utf-8")

    assert returned == raw_hash
    assert (
        "ExecStartPre=/usr/bin/env GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        f"GIT_CONFIG_VALUE_0={release} "
        f"{release}/runtime/.venv/bin/python {release}/runtime/deployment_preflight_handoff.py"
    ) in text
    assert f"ExecStart={release}/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log" in text
    assert "Environment=GIT_CONFIG" not in text


def test_scoped_git_trust_rejects_multiple_preflights(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(
        service_text(release) + f"ExecStartPre={release}/runtime/second-check\n",
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="exactly one"):
        m._scope_preflight_git_trust(fake_base(release), service)


def test_scoped_git_trust_rejects_double_configuration(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(
        service_text(release).replace(
            "ExecStartPre=",
            "ExecStartPre=/usr/bin/env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory ",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="already carries"):
        m._scope_preflight_git_trust(fake_base(release), service)


def test_scoped_git_trust_rejects_unsafe_release_path(tmp_path: Path):
    release = Path("/opt/webai bridge/releases/unsafe")
    service = tmp_path / "webai-bridge.service"
    service.write_text(service_text(release), encoding="utf-8")
    with pytest.raises(GateError, match="unsafe release path"):
        m._scope_preflight_git_trust(fake_base(release), service)
