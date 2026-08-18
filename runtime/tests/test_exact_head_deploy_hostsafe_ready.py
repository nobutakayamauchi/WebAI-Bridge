from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_hostsafe_ready.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_hostsafe_ready", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class FakeGateError(RuntimeError):
    pass


class FakeBase:
    GateError = FakeGateError


def test_wait_tolerates_exec_window_then_requires_two_stable_samples(monkeypatch):
    sequence = iter([
        FakeGateError("cwd mismatch: /"),
        FakeGateError("process has no DEPLOYED_REVISION identity"),
        {"pid": 42, "cwd": "/release/runtime", "revision": "abc", "cmd": ["uvicorn", "app", "--no-access-log"]},
        {"pid": 42, "cwd": "/release/runtime", "revision": "abc", "cmd": ["uvicorn", "app", "--no-access-log"]},
    ])

    def read(_base):
        item = next(sequence)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(m, "_read_main_process_identity", read)
    result = m._wait_for_stable_identity(
        FakeBase,
        expected_cwd="/release/runtime",
        expected_revision="abc",
        required_cmd_tokens=("app", "--no-access-log"),
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 42
    assert result["attempts"] == 4
    assert result["stable_samples"] == 2


def test_wait_resets_stability_when_mainpid_changes(monkeypatch):
    sequence = iter([
        {"pid": 10, "cwd": "/release/runtime", "revision": "abc", "cmd": []},
        {"pid": 11, "cwd": "/release/runtime", "revision": "abc", "cmd": []},
        {"pid": 11, "cwd": "/release/runtime", "revision": "abc", "cmd": []},
    ])
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: next(sequence))
    result = m._wait_for_stable_identity(
        FakeBase,
        expected_cwd="/release/runtime",
        expected_revision="abc",
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 11
    assert result["attempts"] == 3
    assert result["stable_samples"] == 2


def test_wait_times_out_with_last_observed_reason(monkeypatch):
    monkeypatch.setattr(
        m,
        "_read_main_process_identity",
        lambda _base: (_ for _ in ()).throw(FakeGateError("revision missing during exec")),
    )
    with pytest.raises(FakeGateError, match="did not stabilize.*revision missing during exec"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision="abc",
            timeout=0.01,
            poll=0.001,
            stable_samples=2,
        )


def test_wait_never_accepts_missing_required_command_surface(monkeypatch):
    monkeypatch.setattr(
        m,
        "_read_main_process_identity",
        lambda _base: {"pid": 42, "cwd": "/release/runtime", "revision": "abc", "cmd": ["uvicorn"]},
    )
    with pytest.raises(FakeGateError, match="missing tokens"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision="abc",
            required_cmd_tokens=("commercial_handoff:app", "--no-access-log"),
            timeout=0.01,
            poll=0.001,
            stable_samples=2,
        )


def test_read_identity_rejects_mainpid_change_during_observation(monkeypatch):
    answers = iter(["active", "41", "42"])

    class Base:
        GateError = FakeGateError

        @staticmethod
        def run(*args):
            return next(answers)

        @staticmethod
        def process_revision(pid):
            assert pid == 41
            return "abc"

    monkeypatch.setattr(m.os, "readlink", lambda _path: "/release/runtime")
    monkeypatch.setattr(Path, "read_bytes", lambda _self: b"uvicorn\0app\0")
    with pytest.raises(FakeGateError, match="MainPID changed"):
        m._read_main_process_identity(Base)


def test_policy_rejects_single_sample_configuration(monkeypatch):
    monkeypatch.setattr(
        m,
        "_read_main_process_identity",
        lambda _base: {"pid": 1, "cwd": "/release/runtime", "revision": "abc", "cmd": []},
    )
    with pytest.raises(FakeGateError, match="invalid readiness"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision="abc",
            timeout=1,
            poll=0.1,
            stable_samples=1,
        )
