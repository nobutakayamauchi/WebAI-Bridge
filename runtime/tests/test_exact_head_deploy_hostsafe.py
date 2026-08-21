from __future__ import annotations

import importlib.util
import stat
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

    target = release.name if len(release.name) == 40 and all(c in "0123456789abcdef" for c in release.name) else "a" * 40
    return SimpleNamespace(
        RELEASE=release,
        TARGET_SHA=target,
        GateError=GateError,
        sha256=sha256,
        ENV_FILE=Path("/etc/webai-bridge/webai-bridge.env"),
    )


def service_text(release: Path) -> str:
    return "\n".join([
        "[Unit]",
        "Description=test",
        "[Service]",
        "User=webai",
        f"WorkingDirectory={release}/runtime",
        "EnvironmentFile=-/etc/webai-bridge/webai-bridge.env",
        f"ExecStartPre={release}/runtime/.venv/bin/python {release}/runtime/deployment_preflight_handoff.py",
        f"ExecStart={release}/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log",
        "ProtectSystem=strict",
        "",
    ])


def test_scoped_git_trust_wraps_only_exact_execstartpre_and_sanitizes_env(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(service_text(release), encoding="utf-8")
    base = fake_base(release)
    raw_hash = base.sha256(service)
    original_execstart = f"ExecStart={release}/runtime/.venv/bin/uvicorn commercial_handoff:app --no-access-log"

    returned = m._scope_preflight_git_trust(base, service)
    text = service.read_text(encoding="utf-8")

    assert returned == raw_hash
    assert "ExecStartPre=/usr/bin/env " in text
    for name in m.TRUST_ENV_UNSET:
        assert f"-u {name} " in text
    assert "PATH=/usr/bin:/bin " in text
    assert "PYTHONPATH= " in text
    assert "PYTHONHOME= " in text
    assert "GIT_CONFIG_SYSTEM=/dev/null " in text
    assert "GIT_CONFIG_GLOBAL=/dev/null " in text
    assert "GIT_CONFIG_NOSYSTEM=1 " in text
    assert "GIT_CONFIG_COUNT=1 " in text
    assert "GIT_CONFIG_KEY_0=safe.directory " in text
    assert f"GIT_CONFIG_VALUE_0={release} " in text
    assert (
        f"{release}/runtime/.venv/bin/python "
        f"{release}/runtime/deployment_preflight_handoff.py"
    ) in text
    assert original_execstart in text
    assert "Environment=GIT_CONFIG" not in text
    for lock in m.RUNTIME_ENV_LOCKS:
        assert f"Environment={lock}" in text
    assert base.sha256(service) != raw_hash


def test_scoped_git_trust_rejects_wrong_preflight_command(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(
        service_text(release).replace(
            "deployment_preflight_handoff.py",
            "unexpected_preflight.py",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="unexpected rendered ExecStartPre"):
        m._scope_preflight_git_trust(fake_base(release), service)


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
    with pytest.raises(GateError, match="unexpected rendered ExecStartPre"):
        m._scope_preflight_git_trust(fake_base(release), service)


def test_scoped_git_trust_rejects_unsafe_release_path(tmp_path: Path):
    release = Path("/opt/webai bridge/releases/unsafe")
    service = tmp_path / "webai-bridge.service"
    service.write_text(service_text(release), encoding="utf-8")
    with pytest.raises(GateError, match="unsafe release path"):
        m._scope_preflight_git_trust(fake_base(release), service)


def test_scoped_git_trust_rejects_release_not_matching_target(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("b" * 40)
    service = tmp_path / "webai-bridge.service"
    service.write_text(service_text(release), encoding="utf-8")
    base = fake_base(release)
    base.TARGET_SHA = "a" * 40
    with pytest.raises(GateError, match="does not match pinned target"):
        m._scope_preflight_git_trust(base, service)


def test_scoped_git_trust_rejects_preexisting_runtime_env_lock(tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    text = service_text(release).replace(
        "EnvironmentFile=-/etc/webai-bridge/webai-bridge.env",
        "EnvironmentFile=-/etc/webai-bridge/webai-bridge.env\nEnvironment=LD_PRELOAD=",
        1,
    )
    service.write_text(text, encoding="utf-8")
    with pytest.raises(GateError, match="already carries runtime env lock"):
        m._scope_preflight_git_trust(fake_base(release), service)


def test_controller_revision_requires_exact_env_and_same_head(monkeypatch):
    monkeypatch.delenv(m.CONTROLLER_REVISION_ENV, raising=False)
    with pytest.raises(RuntimeError, match="must pin"):
        m._controller_revision_from_env()

    revision = "a" * 40
    monkeypatch.setenv(m.CONTROLLER_REVISION_ENV, revision)
    monkeypatch.setattr(m, "_run_git", lambda *args: revision)
    assert m._controller_revision_from_env() == revision

    monkeypatch.setattr(m, "_run_git", lambda *args: "b" * 40)
    with pytest.raises(RuntimeError, match="changed before wrapper start"):
        m._controller_revision_from_env()


def test_load_committed_base_uses_pinned_revision(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return SimpleNamespace(
            returncode=0,
            stdout="VALUE = 7\n",
            stderr="",
        )

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    revision = "a" * 40
    module = m._load_committed_base(revision)

    assert seen["argv"][-1] == f"{revision}:{m.BASE_PATH}"
    assert module.VALUE == 7


def test_root_owned_path_rejects_group_world_write(monkeypatch, tmp_path: Path):
    path = tmp_path / "x"
    path.write_text("x", encoding="utf-8")
    fake_stat = SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o664)
    monkeypatch.setattr(Path, "lstat", lambda self: fake_stat)
    with pytest.raises(GateError, match="group/world writable"):
        m._check_root_owned_path(SimpleNamespace(GateError=GateError), path, label="fixture")


def test_root_owned_path_rejects_non_root_owner(monkeypatch, tmp_path: Path):
    path = tmp_path / "x"
    path.write_text("x", encoding="utf-8")
    fake_stat = SimpleNamespace(st_uid=1000, st_mode=stat.S_IFREG | 0o644)
    monkeypatch.setattr(Path, "lstat", lambda self: fake_stat)
    with pytest.raises(GateError, match="root-owned"):
        m._check_root_owned_path(SimpleNamespace(GateError=GateError), path, label="fixture")


def test_root_owned_tree_rejects_symlink_when_required(monkeypatch, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_text("x", encoding="utf-8")
    link = root / "link"
    link.symlink_to(target)

    original_lstat = Path.lstat

    def fake_lstat(self):
        info = original_lstat(self)
        return SimpleNamespace(
            st_uid=0,
            st_mode=info.st_mode & ~0o022,
        )

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(GateError, match="must not contain symlinks"):
        m._check_root_owned_tree(
            SimpleNamespace(GateError=GateError),
            root,
            label="fixture",
            reject_symlinks=True,
        )


def test_prepare_overlay_requires_controller_and_hash_consistency(monkeypatch, tmp_path: Path):
    release = Path("/opt/webai-bridge-releases") / ("a" * 40)
    service = tmp_path / "webai-bridge.service"
    manifest = tmp_path / "deployment-manifest.json"
    service.write_text(service_text(release), encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    controller_revision = "c" * 40

    import hashlib

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    base = SimpleNamespace(
        RELEASE=release,
        TARGET_SHA="a" * 40,
        VENV=tmp_path / "venv",
        CONTROL=tmp_path / "control",
        GateError=GateError,
        sha256=sha256,
        ENV_FILE=Path("/etc/webai-bridge/webai-bridge.env"),
    )
    base.VENV.mkdir()
    base.CONTROL.mkdir()
    (base.CONTROL / ".git").mkdir()
    current = {"revision": controller_revision}
    base.git = lambda repo, *args: current["revision"]

    def original_render():
        return tmp_path, service, manifest

    def original_prepare():
        out, rendered, _ = base.render()
        return {
            "controller_revision": controller_revision,
            "service_sha256": sha256(rendered),
        }

    base.render = original_render
    base.prepare = original_prepare
    monkeypatch.setattr(m, "_verify_runtime_immutability", lambda base: None)

    m._install_overlay(base, controller_revision)
    prepared = base.prepare()

    assert prepared["controller_revision_pinned"] == controller_revision
    assert prepared["service_overlay_delta"] == "EXECSTARTPRE_PLUS_RUNTIME_ENV_LOCKS"
    assert prepared["git_environment_sanitized"] is True
    assert prepared["runtime_environment_locks"] == list(m.RUNTIME_ENV_LOCKS)
    assert prepared["target_rendered_service_sha256"] != prepared["candidate_service_sha256"]
    assert prepared["service_sha256"] == prepared["candidate_service_sha256"]

    current["revision"] = "d" * 40
    with pytest.raises(GateError, match="moved during"):
        base.prepare()
