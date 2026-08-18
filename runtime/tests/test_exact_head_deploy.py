from __future__ import annotations

import importlib.util
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
    release.mkdir(); venv.mkdir()
    git(release, "init"); git(release, "config", "user.email", "t@example.com"); git(release, "config", "user.name", "T")
    (release / "runtime").mkdir(); (release / "runtime/app.py").write_text("VALUE=1\n")
    git(release, "add", "."); git(release, "commit", "-m", "fixture")
    sha = git(release, "rev-parse", "HEAD")
    monkeypatch.setattr(m, "RELEASE", release); monkeypatch.setattr(m, "VENV", venv); monkeypatch.setattr(m, "TARGET_SHA", sha)
    (release / "runtime/.venv").symlink_to(venv, target_is_directory=True)
    m.verify_source()
    (release / "runtime/shadow.py").write_text("PWN=True\n")
    with pytest.raises(m.GateError, match="untracked file"):
        m.verify_source()


def test_verify_source_rejects_tracked_modification(monkeypatch, tmp_path: Path):
    release = tmp_path / "release"; venv = tmp_path / "venv"; release.mkdir(); venv.mkdir()
    git(release, "init"); git(release, "config", "user.email", "t@example.com"); git(release, "config", "user.name", "T")
    (release / "runtime").mkdir(); f = release / "runtime/app.py"; f.write_text("VALUE=1\n")
    git(release, "add", "."); git(release, "commit", "-m", "fixture")
    monkeypatch.setattr(m, "RELEASE", release); monkeypatch.setattr(m, "VENV", venv); monkeypatch.setattr(m, "TARGET_SHA", git(release, "rev-parse", "HEAD"))
    (release / "runtime/.venv").symlink_to(venv, target_is_directory=True); f.write_text("VALUE=2\n")
    with pytest.raises(m.GateError, match="command failed"):
        m.verify_source()


def test_control_rejects_live_working_directory_overlap(monkeypatch, tmp_path: Path):
    control = tmp_path / "control"; control.mkdir(); (control / ".git").mkdir()
    constraints = control / "deploy/runtime-tests-228.constraints.txt"; constraints.parent.mkdir(); constraints.write_text("x")
    service = tmp_path / "webai.service"; service.write_text(f"[Service]\nWorkingDirectory={control}/runtime\n")
    monkeypatch.setattr(m, "CONTROL", control); monkeypatch.setattr(m, "CONSTRAINTS", constraints); monkeypatch.setattr(m, "SERVICE", service)
    monkeypatch.setattr(m, "CONSTRAINTS_SHA256", m.sha256(constraints)); monkeypatch.setattr(m, "git", lambda *args: m.ORIGIN)
    with pytest.raises(m.GateError, match="overlaps"):
        m.verify_control()


def test_candidate_preflight_does_not_start_uvicorn(monkeypatch, tmp_path: Path):
    service = tmp_path / "service"; service.write_text("\n".join([
        "[Service]", "Type=simple", "User=webai", "Group=webai", "WorkingDirectory=/x/runtime",
        "Environment=DEPLOYED_REVISION=" + m.TARGET_SHA,
        "ExecStartPre=/x/runtime/.venv/bin/python /x/runtime/deployment_preflight_handoff.py",
        "ExecStart=/x/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log", "ProtectSystem=strict", "ReadWritePaths=/state", ""]))
    seen = {}
    monkeypatch.setattr(m, "transient", lambda name, body: seen.update(name=name, body=body))
    m.candidate_preflight(service)
    assert "deployment_preflight_handoff.py" in seen["body"]
    assert "uvicorn" not in seen["body"]
    assert "Type=oneshot" in seen["body"]


def test_apply_requires_exact_sha_before_mutation():
    with pytest.raises(m.GateError, match="exactly equal"):
        m.apply("deadbeef")
