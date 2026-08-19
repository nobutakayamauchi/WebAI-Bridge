from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_envsafe_apply.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_envsafe_apply", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GateError(RuntimeError):
    pass


class FakeEnvSafe:
    BOOTSTRAP_ALLOWED_ENV_KEYS = m.BOOTSTRAP_ALLOWED_ENV_KEYS


class FakeHost:
    def __init__(self):
        self.revision_checks = 0
        self.render_checks = 0

    def _require_controller_revision(self, base, revision: str) -> None:
        assert revision == "c" * 40
        self.revision_checks += 1

    def _check_root_owned_tree(self, base, path: Path, **kwargs) -> None:
        assert path.is_dir()
        self.render_checks += 1


class FakeReady:
    def __init__(self):
        self.identity_reads = 0
        self.stable_reads = 0

    def _read_main_process_identity(self, base) -> dict:
        self.identity_reads += 1
        return {
            "pid": 101,
            "invocation_id": "d" * 32,
            "cwd": "/old/runtime",
            "revision": "9" * 40,
            "cmd": ["old-server"],
        }

    def _wait_for_stable_identity(self, base, **kwargs) -> dict:
        self.stable_reads += 1
        return {
            "pid": kwargs.get("required_pid", 101),
            "invocation_id": kwargs.get("required_invocation_id", "d" * 32),
            "cwd": kwargs["expected_cwd"],
            "revision": kwargs["expected_revision"],
            "cmd": ["old-server"],
            "stable_samples": 2,
            "attempts": 2,
            "readiness_timeout_seconds": 15.0,
        }


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_test_boundaries(monkeypatch, tmp_path: Path, *, archive_failure: bool = False):
    apply_root = tmp_path / "control" / "production-apply"
    backup_root = tmp_path / "control" / "deploy-backups"
    tx_root = tmp_path / "control" / "apply-transactions"
    for path in (apply_root, backup_root, tx_root):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(m, "_apply_root", lambda base, envsafe: apply_root)
    monkeypatch.setattr(m, "_backup_root", lambda base, envsafe: backup_root)
    monkeypatch.setattr(m, "_transaction_root", lambda base, envsafe: tx_root)

    @contextmanager
    def fake_lock(base, envsafe):
        yield apply_root / "apply.lock"

    monkeypatch.setattr(m, "_exclusive_apply_lock", fake_lock)
    monkeypatch.setattr(m.os, "geteuid", lambda: 0)

    def fake_backup(base, envsafe, expected_hash: str):
        backup = backup_root / "previous.service"
        shutil.copyfile(base.SERVICE, backup)
        base.test_backup = backup
        return backup, 0o644, expected_hash

    monkeypatch.setattr(m, "_service_backup", fake_backup)

    phases: list[str] = []
    real_write = m._write_json_atomic

    def recording_write(base, path: Path, payload: dict, *, mode: int = 0o400):
        phase = payload.get("phase")
        if isinstance(phase, str):
            phases.append(phase)
        return real_write(base, path, payload, mode=mode)

    monkeypatch.setattr(m, "_write_json_atomic", recording_write)

    if archive_failure:
        monkeypatch.setattr(
            m,
            "_archive_transaction",
            lambda *args, **kwargs: (_ for _ in ()).throw(GateError("archive boom")),
        )

    return apply_root, backup_root, tx_root, phases


def _fake_base(
    tmp_path: Path,
    *,
    fail_stripe: bool = False,
    tamper_backup_on_stripe: bool = False,
):
    render = tmp_path / "render"
    render.mkdir()
    candidate = render / "webai-bridge.service"
    candidate.write_text("candidate-service\n", encoding="utf-8")
    service = tmp_path / "webai-bridge.service"
    service.write_text("old-service\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    class Base:
        GateError = GateError
        TARGET_SHA = "5" * 40
        TARGET_TREE = "6" * 40
        SERVICE = service
        RELEASE = tmp_path / "release"
        STATE = tmp_path / "state"
        evidence_payloads: list[dict] = []
        calls: list[str] = []
        rollback_calls = 0
        test_backup: Path | None = None

        @staticmethod
        def sha256(path: Path) -> str:
            return _hash(path)

        @staticmethod
        def prepare():
            Base.calls.append("prepare")
            return {
                "target_sha": Base.TARGET_SHA,
                "tree": Base.TARGET_TREE,
                "render": str(render),
                "candidate_service_sha256": _hash(candidate),
                "production_mutation": False,
                "production_apply_enabled": False,
            }

        @staticmethod
        def systemd_composition():
            Base.calls.append("systemd_composition")

        @staticmethod
        def verify_source():
            Base.calls.append("verify_source")

        @staticmethod
        def atomic_install(source: Path, destination: Path, mode: int):
            Base.calls.append("atomic_install")
            shutil.copyfile(source, destination)

        @staticmethod
        def run(*args: str):
            Base.calls.append("run:" + " ".join(args))
            return ""

        @staticmethod
        def running_identity():
            Base.calls.append("running_identity")
            return {
                "pid": 202,
                "invocation_id": "a" * 32,
                "cwd": str(Base.RELEASE / "runtime"),
                "revision": Base.TARGET_SHA,
            }

        @staticmethod
        def https_health():
            Base.calls.append("https_health")
            return {"status": 200, "body_status": "ok"}

        @staticmethod
        def stripe_acceptance():
            Base.calls.append("stripe_acceptance")
            if tamper_backup_on_stripe:
                assert Base.test_backup is not None
                Base.test_backup.write_text("tampered-backup\n", encoding="utf-8")
            if fail_stripe:
                raise GateError("stripe acceptance failed")

        @staticmethod
        def restore_previous_service(backup: Path, **kwargs):
            Base.rollback_calls += 1
            shutil.copyfile(backup, Base.SERVICE)
            return {
                "verified": True,
                "service_sha256": kwargs["expected_hash"],
                "pid": 303,
                "invocation_id": "b" * 32,
                "cwd": kwargs["previous"]["cwd"],
                "revision": kwargs["previous"]["revision"],
                "https_health": {"status": 200, "body_status": "ok"},
            }

        @staticmethod
        def evidence(payload: dict) -> Path:
            Base.evidence_payloads.append(payload)
            path = evidence_dir / f"evidence-{len(Base.evidence_payloads)}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return path

    Base.RELEASE.mkdir()
    Base.STATE.mkdir()
    return Base, candidate, service


def test_authority_ids_are_explicit_and_root_separated():
    assert m.APPLY_AUTHORITY == "ROOT_ONLY_TRANSACTIONAL_APPLY_V2"
    assert m.BACKUP_AUTHORITY == "SEPARATE_ROOT_ONLY_SERVICE_BACKUP_V2"
    assert m.TRANSACTION_AUTHORITY == "DURABLE_SWITCH_ARMED_FAIL_CLOSED_V2"
    assert m.LOCK_AUTHORITY == "ROOT_ONLY_EXCLUSIVE_FLOCK_V1"
    assert m.PREVIOUS_GENERATION_AUTHORITY == "STABLE_INVOCATION_ID_MAINPID_SNAPSHOT_V1"


def test_transaction_payload_marks_mutation_possibility_explicitly(tmp_path):
    class Base:
        TARGET_SHA = "5" * 40
        TARGET_TREE = "6" * 40

    payload = m._transaction_payload(
        transaction_id="tx",
        phase="SWITCH_ARMED",
        controller_revision="c" * 40,
        base=Base,
        prepared={"candidate_service_sha256": "a" * 64},
        previous={"service_sha256": "b" * 64},
        backup=tmp_path / "backup",
        old_hash="b" * 64,
        candidate_hash="a" * 64,
        production_mutation=False,
        production_mutation_possible=True,
    )
    raw = json.dumps(payload)
    assert payload["production_mutation"] is False
    assert payload["production_mutation_possible"] is True
    assert payload["live_payment_performed"] is False
    assert payload["secrets_recorded"] is False
    assert "STRIPE_SECRET" not in raw
    assert "OPENAI_API_KEY" not in raw


def test_pending_transaction_fails_closed(monkeypatch, tmp_path):
    active = tmp_path / "active-apply.json"
    active.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(m, "_active_transaction_path", lambda base, envsafe: active)

    class Base:
        GateError = GateError

    with pytest.raises(GateError, match="unresolved production apply transaction"):
        m._assert_no_pending_transaction(Base, FakeEnvSafe())


def test_stable_previous_snapshot_binds_invocation_pid_and_unit_hash(tmp_path):
    Base, _candidate, _service = _fake_base(tmp_path)
    ready = FakeReady()
    snapshot = m._stable_previous_snapshot(Base, ready)
    assert snapshot["pid"] == 101
    assert snapshot["invocation_id"] == "d" * 32
    assert snapshot["revision"] == "9" * 40
    assert snapshot["service_sha256"] == _hash(Base.SERVICE)
    assert snapshot["stable_samples"] == 2
    assert ready.identity_reads == 1
    assert ready.stable_reads == 1


def test_wrong_approval_fails_before_prepare(monkeypatch, tmp_path):
    Base, _candidate, _service = _fake_base(tmp_path)
    host = FakeHost()
    ready = FakeReady()
    _install_test_boundaries(monkeypatch, tmp_path)
    m._install_apply_overlay(Base, FakeEnvSafe(), host, ready, "c" * 40)

    with pytest.raises(GateError, match="approval must exactly equal pinned target SHA"):
        Base.apply("0" * 40)
    assert Base.calls == []


def test_success_arms_journal_before_service_replace(monkeypatch, tmp_path):
    Base, candidate, service = _fake_base(tmp_path)
    host = FakeHost()
    ready = FakeReady()
    apply_root, _backup_root, tx_root, phases = _install_test_boundaries(monkeypatch, tmp_path)
    m._install_apply_overlay(Base, FakeEnvSafe(), host, ready, "c" * 40)

    evidence = Base.apply(Base.TARGET_SHA)

    assert evidence.is_file()
    assert service.read_bytes() == candidate.read_bytes()
    assert Base.rollback_calls == 0
    assert Base.calls.count("prepare") == 1
    assert "running_identity" in Base.calls
    assert "https_health" in Base.calls
    assert "stripe_acceptance" in Base.calls
    assert host.revision_checks >= 3
    assert host.render_checks == 1
    assert ready.stable_reads >= 2
    assert phases.index("SWITCH_ARMED") < phases.index("SERVICE_REPLACED")
    assert not (apply_root / m.ACTIVE_TRANSACTION_NAME).exists()
    archived = list(tx_root.glob("*.json"))
    assert len(archived) == 1
    archive_data = json.loads(archived[0].read_text(encoding="utf-8"))
    assert archive_data["phase"] == "COMMITTED"
    assert archive_data["production_mutation_possible"] is True
    assert Base.evidence_payloads[-1]["status"] == "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS"
    assert Base.evidence_payloads[-1]["live_payment_performed"] is False


def test_post_switch_failure_requires_verified_rollback(monkeypatch, tmp_path):
    Base, _candidate, service = _fake_base(tmp_path, fail_stripe=True)
    old_bytes = service.read_bytes()
    host = FakeHost()
    ready = FakeReady()
    apply_root, _backup_root, tx_root, _phases = _install_test_boundaries(monkeypatch, tmp_path)
    m._install_apply_overlay(Base, FakeEnvSafe(), host, ready, "c" * 40)

    with pytest.raises(GateError, match="deploy failed"):
        Base.apply(Base.TARGET_SHA)

    assert Base.rollback_calls == 1
    assert service.read_bytes() == old_bytes
    assert Base.evidence_payloads[-1]["status"] == "ROLLBACK_VERIFIED_AFTER_FAILURE"
    assert Base.evidence_payloads[-1]["rollback"]["verified"] is True
    assert not (apply_root / m.ACTIVE_TRANSACTION_NAME).exists()
    archived = list(tx_root.glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["phase"] == "ROLLBACK_VERIFIED_AFTER_FAILURE"


def test_tampered_backup_is_rejected_before_rollback_mutation(monkeypatch, tmp_path):
    Base, candidate, service = _fake_base(
        tmp_path,
        fail_stripe=True,
        tamper_backup_on_stripe=True,
    )
    host = FakeHost()
    ready = FakeReady()
    apply_root, _backup_root, _tx_root, _phases = _install_test_boundaries(monkeypatch, tmp_path)
    m._install_apply_overlay(Base, FakeEnvSafe(), host, ready, "c" * 40)

    with pytest.raises(GateError, match="rollback/evidence verification failed"):
        Base.apply(Base.TARGET_SHA)

    assert Base.rollback_calls == 0
    assert service.read_bytes() == candidate.read_bytes()
    assert Base.evidence_payloads[-1]["status"] == "ROLLBACK_FAILED"
    active = apply_root / m.ACTIVE_TRANSACTION_NAME
    assert active.is_file()
    assert json.loads(active.read_text(encoding="utf-8"))["phase"] == "ROLLBACK_FAILED"


def test_archive_failure_after_durable_success_does_not_rollback(monkeypatch, tmp_path):
    Base, candidate, service = _fake_base(tmp_path)
    host = FakeHost()
    ready = FakeReady()
    apply_root, _backup_root, _tx_root, _phases = _install_test_boundaries(
        monkeypatch,
        tmp_path,
        archive_failure=True,
    )
    m._install_apply_overlay(Base, FakeEnvSafe(), host, ready, "c" * 40)

    with pytest.raises(GateError, match="production is accepted and evidence is durable"):
        Base.apply(Base.TARGET_SHA)

    assert Base.rollback_calls == 0
    assert service.read_bytes() == candidate.read_bytes()
    active = apply_root / m.ACTIVE_TRANSACTION_NAME
    assert active.is_file()
    data = json.loads(active.read_text(encoding="utf-8"))
    assert data["phase"] == "COMMITTED_EVIDENCE_WRITTEN_ARCHIVE_FAILED"
    assert Base.evidence_payloads[-1]["status"] == "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS"
