from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True).stdout.strip()


def test_pinned_identity_constants():
    assert m.TARGET_SHA == "0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98"
    assert m.TARGET_TREE == "38be7d9d9145cfcf9bc3aba47eccb4f453da4439"
    assert m.DOMAIN == "webai.140-238-62-74.sslip.io"


def test_verify_source_allows_only_pinned_venv(monkeypatch, tmp_path: Path):
    release = tmp_path / "release"
    venv = tmp_path / "venv"
    release.mkdir()
    venv.mkdir()
    git(release, "init")
    git(release, "config", "user.email", "t@example.com")
    git(release, "config", "user.name", "T")
    (release / "runtime").mkdir()
    (release / "runtime/app.py").write_text("VALUE=1\n")
    git(release, "add", ".")
    git(release, "commit", "-m", "fixture")
    sha = git(release, "rev-parse", "HEAD")
    monkeypatch.setattr(m, "RELEASE", release)
    monkeypatch.setattr(m, "VENV", venv)
    monkeypatch.setattr(m, "TARGET_SHA", sha)
    (release / "runtime/.venv").symlink_to(venv, target_is_directory=True)
    m.verify_source()
    (release / "runtime/shadow.py").write_text("PWN=True\n")
    with pytest.raises(m.GateError, match="untracked file"):
        m.verify_source()


def test_verify_source_rejects_tracked_modification(monkeypatch, tmp_path: Path):
    release = tmp_path / "release"
    venv = tmp_path / "venv"
    release.mkdir()
    venv.mkdir()
    git(release, "init")
    git(release, "config", "user.email", "t@example.com")
    git(release, "config", "user.name", "T")
    (release / "runtime").mkdir()
    f = release / "runtime/app.py"
    f.write_text("VALUE=1\n")
    git(release, "add", ".")
    git(release, "commit", "-m", "fixture")
    monkeypatch.setattr(m, "RELEASE", release)
    monkeypatch.setattr(m, "VENV", venv)
    monkeypatch.setattr(m, "TARGET_SHA", git(release, "rev-parse", "HEAD"))
    (release / "runtime/.venv").symlink_to(venv, target_is_directory=True)
    f.write_text("VALUE=2\n")
    with pytest.raises(m.GateError, match="command failed"):
        m.verify_source()


def test_control_rejects_actual_live_working_directory_overlap(monkeypatch, tmp_path: Path):
    control = tmp_path / "control"
    control.mkdir()
    (control / ".git").mkdir()
    constraints = control / "deploy/runtime-tests-228.constraints.txt"
    constraints.parent.mkdir()
    constraints.write_text("x")
    monkeypatch.setattr(m, "CONTROL", control)
    monkeypatch.setattr(m, "CONSTRAINTS", constraints)
    monkeypatch.setattr(m, "CONSTRAINTS_SHA256", m.sha256(constraints))
    answers = {
        ("remote", "get-url", "origin"): m.ORIGIN,
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("rev-parse", "HEAD"): "abc",
        ("rev-parse", "origin/main"): "abc",
    }
    monkeypatch.setattr(m, "git", lambda repo, *args: answers[args])
    monkeypatch.setattr(m, "run", lambda *args, **kwargs: "")
    monkeypatch.setattr(m, "live_service_working_directory", lambda: control / "runtime")
    with pytest.raises(m.GateError, match="actual production"):
        m.verify_control()


def test_candidate_preflight_does_not_start_uvicorn(monkeypatch, tmp_path: Path):
    service = tmp_path / "service"
    service.write_text("\n".join([
        "[Service]",
        "Type=simple",
        "User=webai",
        "Group=webai",
        "WorkingDirectory=/x/runtime",
        "Environment=DEPLOYED_REVISION=" + m.TARGET_SHA,
        "ExecStartPre=/x/runtime/.venv/bin/python /x/runtime/deployment_preflight_handoff.py",
        "ExecStart=/x/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log",
        "ProtectSystem=strict",
        "ReadWritePaths=/state",
        "",
    ]))
    seen = {}
    monkeypatch.setattr(m, "transient", lambda name, body: seen.update(name=name, body=body))
    m.candidate_preflight(service)
    assert "deployment_preflight_handoff.py" in seen["body"]
    assert "uvicorn" not in seen["body"]
    assert "Type=oneshot" in seen["body"]


def test_apply_requires_exact_sha_before_mutation():
    with pytest.raises(m.GateError, match="exactly equal"):
        m.apply("deadbeef")


def test_restore_previous_service_requires_verified_hash_and_identity(monkeypatch, tmp_path: Path):
    service = tmp_path / "service"
    backup = tmp_path / "backup"
    service.write_text("new")
    backup.write_text("old")
    monkeypatch.setattr(m, "SERVICE", service)
    monkeypatch.setattr(m, "systemd_composition", lambda: None)
    monkeypatch.setattr(m, "atomic_install", lambda src, dst, mode: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(m.os, "readlink", lambda path: "/old/runtime")
    monkeypatch.setattr(m, "process_revision", lambda pid: "oldsha")
    monkeypatch.setattr(m, "run", lambda *args, **kwargs: "123" if "--property=MainPID" in args else "")
    previous = {"cwd": str(Path("/old/runtime").resolve()), "revision": "oldsha"}
    result = m.restore_previous_service(
        backup,
        expected_hash=m.sha256(backup),
        expected_mode=0o644,
        previous=previous,
    )
    assert result["verified"] is True
    assert result["service_sha256"] == m.sha256(backup)
    assert result["pid"] == 123
    assert result["revision"] == "oldsha"


def test_restore_previous_service_fails_if_hash_not_restored(monkeypatch, tmp_path: Path):
    service = tmp_path / "service"
    backup = tmp_path / "backup"
    service.write_text("new")
    backup.write_text("old")
    monkeypatch.setattr(m, "SERVICE", service)
    monkeypatch.setattr(m, "systemd_composition", lambda: None)
    monkeypatch.setattr(m, "atomic_install", lambda src, dst, mode: None)
    monkeypatch.setattr(m, "run", lambda *args, **kwargs: "")
    with pytest.raises(m.GateError, match="hash mismatch"):
        m.restore_previous_service(
            backup,
            expected_hash=m.sha256(backup),
            expected_mode=0o644,
            previous={"cwd": "/old/runtime", "revision": "oldsha"},
        )


def test_restore_previous_service_rejects_wrong_previous_identity(monkeypatch, tmp_path: Path):
    service = tmp_path / "service"
    backup = tmp_path / "backup"
    service.write_text("new")
    backup.write_text("old")
    monkeypatch.setattr(m, "SERVICE", service)
    monkeypatch.setattr(m, "systemd_composition", lambda: None)
    monkeypatch.setattr(m, "atomic_install", lambda src, dst, mode: dst.write_bytes(src.read_bytes()))
    monkeypatch.setattr(m.os, "readlink", lambda path: "/different/runtime")
    monkeypatch.setattr(m, "process_revision", lambda pid: "oldsha")
    monkeypatch.setattr(m, "run", lambda *args, **kwargs: "123" if "--property=MainPID" in args else "")
    with pytest.raises(m.GateError, match="rollback cwd mismatch"):
        m.restore_previous_service(
            backup,
            expected_hash=m.sha256(backup),
            expected_mode=0o644,
            previous={"cwd": "/old/runtime", "revision": "oldsha"},
        )


def test_evidence_paths_are_unique_and_read_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(m, "STATE", tmp_path)
    p1 = m.evidence({"a": 1})
    p2 = m.evidence({"a": 2})
    assert p1 != p2
    assert stat.S_IMODE(p1.stat().st_mode) == 0o400
    assert stat.S_IMODE(p2.stat().st_mode) == 0o400


class FakeHealthResponse:
    def __init__(self, *, url: str, status: int = 200, payload: bytes = b'{"status":"ok","app_count":2,"pricing_version":"v"}'):
        self._url = url
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self._url

    def read(self, limit):
        return self._payload


def test_https_health_rejects_redirect(monkeypatch):
    monkeypatch.setattr(
        m.urllib.request,
        "urlopen",
        lambda url, timeout: FakeHealthResponse(url="https://other.invalid/health"),
    )
    with pytest.raises(m.GateError, match="redirected"):
        m.https_health()


def test_https_health_requires_application_ready_body(monkeypatch):
    expected = f"https://{m.DOMAIN}/health"
    monkeypatch.setattr(
        m.urllib.request,
        "urlopen",
        lambda url, timeout: FakeHealthResponse(url=expected, payload=b'{"status":"bad"}'),
    )
    with pytest.raises(m.GateError, match="application readiness"):
        m.https_health()
