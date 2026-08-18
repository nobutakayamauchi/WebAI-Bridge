from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_envsafe.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_envsafe_bootstrap", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GateError(RuntimeError):
    pass


def _clean_bootstrap_env() -> dict[str, str]:
    return {
        m.CONTROLLER_REVISION_ENV: "a" * 40,
        m.BOOTSTRAP_CLEAN_ENV: "1",
        "PATH": "/usr/bin:/bin",
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def test_bootstrap_accepts_only_explicit_clean_allowlist():
    assert m._validate_bootstrap_environment(_clean_bootstrap_env()) == "a" * 40


@pytest.mark.parametrize(
    "name,value",
    [
        ("GIT_DIR", "/tmp/evil-git"),
        ("LD_PRELOAD", "/tmp/evil.so"),
        ("PYTHONPATH", "/tmp/evil-python"),
        ("PIP_INDEX_URL", "https://evil.example/simple"),
        ("HTTPS_PROXY", "http://evil.example:8080"),
        ("OPENAI_BASE_URL", "https://evil.example/v1"),
    ],
)
def test_bootstrap_rejects_inherited_authority_before_controller_git(name, value):
    env = _clean_bootstrap_env()
    env[name] = value
    with pytest.raises(RuntimeError, match="bootstrap environment is not clean"):
        m._validate_bootstrap_environment(env)


def test_bootstrap_requires_clean_marker_and_exact_path():
    env = _clean_bootstrap_env()
    env.pop(m.BOOTSTRAP_CLEAN_ENV)
    with pytest.raises(RuntimeError, match=m.BOOTSTRAP_CLEAN_ENV):
        m._validate_bootstrap_environment(env)

    env = _clean_bootstrap_env()
    env["PATH"] = "/tmp/bin:/usr/bin"
    with pytest.raises(RuntimeError, match="PATH must be exactly"):
        m._validate_bootstrap_environment(env)


def test_clean_process_environment_drops_parent_authority(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "/tmp/evil")
    monkeypatch.setenv("PIP_INDEX_URL", "https://evil.example/simple")
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.example")
    m._install_clean_process_environment("b" * 40)
    assert os.environ[m.CONTROLLER_REVISION_ENV] == "b" * 40
    assert os.environ[m.BOOTSTRAP_CLEAN_ENV] == "1"
    assert os.environ["PATH"] == "/usr/bin:/bin"
    assert os.environ["PIP_CONFIG_FILE"] == "/dev/null"
    assert os.environ["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert os.environ["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert os.environ["GIT_NO_REPLACE_OBJECTS"] == "1"
    for name in ("GIT_DIR", "PIP_INDEX_URL", "HTTPS_PROXY"):
        assert name not in os.environ


def test_prepare_root_gate_rejects_existing_release_symlink_before_dependency_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)
    controller = tmp_path / "control"
    controller.mkdir()
    release_root = tmp_path / "releases"
    release_root.mkdir()
    venv_root = tmp_path / "venvs"
    venv_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    release = release_root / ("c" * 40)
    release.symlink_to(outside, target_is_directory=True)

    calls: list[str] = []

    class Host:
        @staticmethod
        def _require_controller_revision(base, revision):
            calls.append("revision")

        @staticmethod
        def _check_root_owned_tree(base, path, **kwargs):
            calls.append(f"tree:{path.name}")

        @staticmethod
        def _check_root_owned_path(base, path, **kwargs):
            calls.append(f"path:{path.name}")

    base = SimpleNamespace(
        GateError=GateError,
        CONTROL=controller,
        RELEASE=release,
        VENV=venv_root / ("c" * 40),
    )
    with pytest.raises(GateError, match="must not be a symlink"):
        m._verify_prepare_roots(base, Host, "d" * 40)
    assert calls[0] == "revision"
    assert "tree:control" in calls


def test_canonical_envsafe_overlay_blocks_production_apply():
    class Base:
        GateError = GateError
        render = staticmethod(lambda: None)
        prepare = staticmethod(lambda: {})
        apply = staticmethod(lambda approval: approval)
        candidate_preflight = staticmethod(lambda service: None)
        stripe_acceptance = staticmethod(lambda: None)
        evidence = staticmethod(lambda payload: Path("/tmp/old-evidence"))

    class Host:
        pass

    m._install_envsafe_overlay(Base, Host, "e" * 40)
    with pytest.raises(GateError, match="production apply is intentionally disabled"):
        Base.apply(m.TARGET_SHA)


def test_prepare_evidence_declares_apply_disabled_in_overlay_contract():
    assert m.PROCESS_ENV_AUTHORITY == "CLEAN_BOOTSTRAP_ALLOWLIST_V1"
    assert m.PREPARE_TRUST_AUTHORITY == "ROOT_OWNED_BEFORE_DEPENDENCY_EXECUTION_V1"
    assert m.EVIDENCE_AUTHORITY == "SEPARATE_ROOT_ONLY_DEPLOY_CONTROL_STATE_V1"
