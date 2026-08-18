from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_hostsafe_ready.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_hostsafe_ready", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

SHA = "a" * 40
INV = "b" * 32
INV2 = "c" * 32


class FakeGateError(RuntimeError):
    pass


class FakeBase:
    GateError = FakeGateError


def obs(pid: int, *, invocation_id: str = INV, cwd: str = "/release/runtime", revision: str = SHA, cmd=None):
    return {
        "pid": pid,
        "invocation_id": invocation_id,
        "cwd": cwd,
        "revision": revision,
        "cmd": list(cmd or []),
    }


def test_wait_tolerates_exec_window_then_requires_two_stable_samples(monkeypatch):
    sequence = iter([
        FakeGateError("cwd mismatch: /"),
        FakeGateError("process has no DEPLOYED_REVISION identity"),
        obs(42, cmd=["uvicorn", "app", "--no-access-log"]),
        obs(42, cmd=["uvicorn", "app", "--no-access-log"]),
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
        expected_revision=SHA,
        required_cmd_tokens=("app", "--no-access-log"),
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 42
    assert result["invocation_id"] == INV
    assert result["attempts"] == 4
    assert result["stable_samples"] == 2


def test_wait_resets_stability_when_mainpid_changes(monkeypatch):
    sequence = iter([
        obs(10),
        obs(11),
        obs(11),
    ])
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: next(sequence))
    result = m._wait_for_stable_identity(
        FakeBase,
        expected_cwd="/release/runtime",
        expected_revision=SHA,
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 11
    assert result["attempts"] == 3
    assert result["stable_samples"] == 2


def test_wait_resets_stability_when_invocation_changes_with_same_pid(monkeypatch):
    sequence = iter([
        obs(42, invocation_id=INV),
        obs(42, invocation_id=INV2),
        obs(42, invocation_id=INV2),
    ])
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: next(sequence))
    result = m._wait_for_stable_identity(
        FakeBase,
        expected_cwd="/release/runtime",
        expected_revision=SHA,
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 42
    assert result["invocation_id"] == INV2
    assert result["attempts"] == 3


def test_wait_enforces_pinned_mainpid_and_invocation_generation(monkeypatch):
    sequence = iter([
        obs(42, invocation_id=INV2),
        obs(42, invocation_id=INV),
        obs(42, invocation_id=INV),
    ])
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: next(sequence))
    result = m._wait_for_stable_identity(
        FakeBase,
        expected_cwd="/release/runtime",
        expected_revision=SHA,
        required_pid=42,
        required_invocation_id=INV,
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["pid"] == 42
    assert result["invocation_id"] == INV
    assert result["attempts"] == 3


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
            expected_revision=SHA,
            timeout=0.01,
            poll=0.001,
            stable_samples=2,
        )


def test_wait_never_accepts_missing_required_command_surface(monkeypatch):
    monkeypatch.setattr(
        m,
        "_read_main_process_identity",
        lambda _base: obs(42, cmd=["uvicorn"]),
    )
    with pytest.raises(FakeGateError, match="missing tokens"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision=SHA,
            required_cmd_tokens=("commercial_handoff:app", "--no-access-log"),
            timeout=0.01,
            poll=0.001,
            stable_samples=2,
        )


def test_wait_rejects_non_exact_expected_revision(monkeypatch):
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: obs(1))
    with pytest.raises(FakeGateError, match="40-hex"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision="abc",
        )


def test_wait_rejects_non_exact_required_invocation(monkeypatch):
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: obs(1))
    with pytest.raises(FakeGateError, match="InvocationID"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision=SHA,
            required_invocation_id="abc",
        )


def test_read_identity_rejects_mainpid_change_during_observation(monkeypatch):
    answers = iter(["active", INV, "41", "42", INV])

    class Base:
        GateError = FakeGateError

        @staticmethod
        def run(*args):
            return next(answers)

        @staticmethod
        def process_revision(pid):
            assert pid == 41
            return SHA

    monkeypatch.setattr(m.os, "readlink", lambda _path: "/release/runtime")
    monkeypatch.setattr(Path, "read_bytes", lambda _self: b"uvicorn\0app\0")
    with pytest.raises(FakeGateError, match="MainPID changed"):
        m._read_main_process_identity(Base)


def test_read_identity_rejects_invocation_change_during_observation(monkeypatch):
    answers = iter(["active", INV, "41", "41", INV2])

    class Base:
        GateError = FakeGateError

        @staticmethod
        def run(*args):
            return next(answers)

        @staticmethod
        def process_revision(pid):
            assert pid == 41
            return SHA

    monkeypatch.setattr(m.os, "readlink", lambda _path: "/release/runtime")
    monkeypatch.setattr(Path, "read_bytes", lambda _self: b"uvicorn\0app\0")
    with pytest.raises(FakeGateError, match="InvocationID changed"):
        m._read_main_process_identity(Base)


def test_policy_rejects_single_sample_configuration(monkeypatch):
    monkeypatch.setattr(m, "_read_main_process_identity", lambda _base: obs(1))
    with pytest.raises(FakeGateError, match="invalid readiness"):
        m._wait_for_stable_identity(
            FakeBase,
            expected_cwd="/release/runtime",
            expected_revision=SHA,
            timeout=1,
            poll=0.1,
            stable_samples=1,
        )


def test_health_wait_tolerates_startup_failure_then_requires_two_successes():
    sequence = iter([
        FakeGateError("connection refused"),
        {"status": 200, "body_status": "ok"},
        {"status": 200, "body_status": "ok"},
    ])

    def probe(_attempt_timeout):
        item = next(sequence)
        if isinstance(item, Exception):
            raise item
        return item

    result = m._wait_for_stable_health(
        FakeBase,
        probe,
        timeout=0.5,
        poll=0.001,
        stable_samples=2,
    )
    assert result["status"] == 200
    assert result["stable_samples"] == 2
    assert result["health_attempts"] == 3


def test_health_wait_times_out_with_last_reason():
    def probe(_attempt_timeout):
        raise FakeGateError("connection refused")

    with pytest.raises(FakeGateError, match="health did not stabilize.*connection refused"):
        m._wait_for_stable_health(
            FakeBase,
            probe,
            timeout=0.01,
            poll=0.001,
            stable_samples=2,
        )


def test_health_attempt_timeout_is_capped_by_overall_deadline():
    seen = []

    def probe(attempt_timeout):
        seen.append(attempt_timeout)
        return {"status": 200, "body_status": "ok"}

    result = m._wait_for_stable_health(
        FakeBase,
        probe,
        timeout=0.05,
        poll=0.001,
        stable_samples=2,
        attempt_timeout=5.0,
    )
    assert result["status"] == 200
    assert len(seen) == 2
    assert all(0 < value <= 0.05 for value in seen)


def test_overlay_rechecks_health_after_stripe_and_records_final_generation(monkeypatch):
    calls = {"identity": 0, "health": 0, "stripe": 0}

    def wait_identity(_base, **kwargs):
        calls["identity"] += 1
        if kwargs.get("required_pid") is not None:
            assert kwargs["required_pid"] == 77
            assert kwargs["required_invocation_id"] == INV
        return {
            **obs(77, cmd=["commercial_handoff:app", "--no-access-log"]),
            "stable_samples": 2,
            "attempts": 2,
            "readiness_timeout_seconds": 15.0,
        }

    def wait_health(_base, _probe, **_kwargs):
        calls["health"] += 1
        return {
            "url": "https://example.invalid/health",
            "status": 200,
            "body_status": "ok",
            "stable_samples": 2,
            "health_attempts": 2,
            "readiness_timeout_seconds": 15.0,
            "max_attempt_timeout_seconds": 5.0,
        }

    monkeypatch.setattr(m, "_wait_for_stable_identity", wait_identity)
    monkeypatch.setattr(m, "_wait_for_stable_health", wait_health)

    base = types.SimpleNamespace(
        GateError=FakeGateError,
        RELEASE=Path("/release"),
        TARGET_SHA=SHA,
        prepare=lambda: {"prepared": True},
        stripe_acceptance=lambda: calls.__setitem__("stripe", calls["stripe"] + 1),
        evidence=lambda payload: payload,
    )
    m._install_readiness_overlay(base)

    running = base.running_identity()
    assert running["pid"] == 77
    assert running["invocation_id"] == INV
    first_health = base.https_health()
    assert first_health["verified_invocation_id"] == INV
    base.stripe_acceptance()
    evidence = base.evidence({"status": "PASS"})

    assert calls["stripe"] == 1
    assert calls["health"] == 2
    assert calls["identity"] >= 5
    assert evidence["post_stripe_https_health"]["verified_main_pid"] == 77
    assert evidence["post_stripe_https_health"]["verified_invocation_id"] == INV


def test_rollback_requires_health_and_same_restored_generation(monkeypatch, tmp_path: Path):
    service = tmp_path / "webai-bridge.service"
    backup = tmp_path / "backup.service"
    service.write_text("new")
    backup.write_text("old")
    calls = {"identity": 0, "health": 0}

    def wait_identity(_base, **kwargs):
        calls["identity"] += 1
        if calls["identity"] == 1:
            assert kwargs.get("required_pid") is None
        else:
            assert kwargs["required_pid"] == 88
            assert kwargs["required_invocation_id"] == INV2
        return {
            **obs(88, invocation_id=INV2, cwd="/old/runtime"),
            "stable_samples": 2,
            "attempts": 2,
            "readiness_timeout_seconds": 15.0,
        }

    def wait_health(_base, _probe, **_kwargs):
        calls["health"] += 1
        return {
            "status": 200,
            "body_status": "ok",
            "stable_samples": 2,
            "health_attempts": 2,
        }

    monkeypatch.setattr(m, "_wait_for_stable_identity", wait_identity)
    monkeypatch.setattr(m, "_wait_for_stable_health", wait_health)

    base = types.SimpleNamespace(
        GateError=FakeGateError,
        RELEASE=Path("/release"),
        TARGET_SHA=SHA,
        SERVICE=service,
        prepare=lambda: {},
        stripe_acceptance=lambda: None,
        evidence=lambda payload: payload,
        atomic_install=lambda src, dst, mode: dst.write_bytes(src.read_bytes()),
        run=lambda *args, **kwargs: "",
        systemd_composition=lambda: None,
        sha256=lambda path: __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    )
    m._install_readiness_overlay(base)
    expected_hash = base.sha256(backup)
    result = base.restore_previous_service(
        backup,
        expected_hash=expected_hash,
        expected_mode=0o644,
        previous={"cwd": "/old/runtime", "revision": SHA},
    )

    assert result["verified"] is True
    assert result["pid"] == 88
    assert result["invocation_id"] == INV2
    assert result["https_health"]["status"] == 200
    assert calls["health"] == 1
    assert calls["identity"] == 2
