from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
ENVSAFE_PATH = "deploy/exact_head_deploy_envsafe.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
BOOTSTRAP_CLEAN_ENV = "WEB_AI_BOOTSTRAP_CLEAN"

APPLY_AUTHORITY = "ROOT_ONLY_TRANSACTIONAL_APPLY_V2"
BACKUP_AUTHORITY = "SEPARATE_ROOT_ONLY_SERVICE_BACKUP_V2"
TRANSACTION_AUTHORITY = "DURABLE_SWITCH_ARMED_FAIL_CLOSED_V2"
LOCK_AUTHORITY = "ROOT_ONLY_EXCLUSIVE_FLOCK_V1"
PREVIOUS_GENERATION_AUTHORITY = "STABLE_INVOCATION_ID_MAINPID_SNAPSHOT_V1"
APPLY_CONTROL_DIR_NAME = "production-apply"
BACKUP_DIR_NAME = "deploy-backups"
TRANSACTION_DIR_NAME = "apply-transactions"
ACTIVE_TRANSACTION_NAME = "active-apply.json"
LOCK_NAME = "apply.lock"

BOOTSTRAP_ALLOWED_ENV_KEYS = frozenset(
    {
        CONTROLLER_REVISION_ENV,
        BOOTSTRAP_CLEAN_ENV,
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
    }
)


def _validate_and_clean_bootstrap_environment() -> str:
    env = dict(os.environ)
    revision = (env.get(CONTROLLER_REVISION_ENV) or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError(
            f"{CONTROLLER_REVISION_ENV} must pin the exact 40-hex controller revision"
        )
    if env.get(BOOTSTRAP_CLEAN_ENV) != "1":
        raise RuntimeError(
            f"{BOOTSTRAP_CLEAN_ENV}=1 is required from the clean bootstrap invocation"
        )
    unexpected = sorted(set(env) - BOOTSTRAP_ALLOWED_ENV_KEYS)
    if unexpected:
        raise RuntimeError(
            "apply controller bootstrap environment is not clean; unexpected keys: "
            + ", ".join(unexpected)
        )
    if env.get("PATH") not in (None, "/usr/bin:/bin"):
        raise RuntimeError("apply controller bootstrap PATH must be exactly /usr/bin:/bin")

    os.environ.clear()
    os.environ.update(
        {
            CONTROLLER_REVISION_ENV: revision,
            BOOTSTRAP_CLEAN_ENV: "1",
            "PATH": "/usr/bin:/bin",
            "HOME": "/root",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": "/dev/null",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )

    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"controller Git identity check failed: {detail}")
    actual = completed.stdout.strip().lower()
    if actual != revision:
        raise RuntimeError(
            f"controller HEAD changed before apply wrapper start: expected {revision}, got {actual}"
        )
    return revision


def _load_committed(controller_revision: str, path: str, module_name: str):
    obj = f"{controller_revision}:{path}"
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "show", obj],
        check=False,
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed controller object {path}: {detail}")
    module = types.ModuleType(module_name)
    module.__file__ = f"git:{CONTROL}:{obj}"
    sys.modules[module_name] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _private_dir(base, path: Path, *, label: str) -> Path:
    if os.geteuid() != 0:
        raise base.GateError(f"{label} requires root")
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise base.GateError(f"{label} must be a regular directory: {path}")
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise base.GateError(f"{label} must remain root-owned mode 0700")
    else:
        path.mkdir(mode=0o700, parents=False)
    os.chmod(path, 0o700)
    return path


def _apply_root(base, envsafe) -> Path:
    root = envsafe._secure_deploy_control_state(base)
    return _private_dir(base, root / APPLY_CONTROL_DIR_NAME, label="production apply control state")


def _backup_root(base, envsafe) -> Path:
    return _private_dir(
        base,
        envsafe._secure_deploy_control_state(base) / BACKUP_DIR_NAME,
        label="production rollback backup root",
    )


def _transaction_root(base, envsafe) -> Path:
    return _private_dir(
        base,
        envsafe._secure_deploy_control_state(base) / TRANSACTION_DIR_NAME,
        label="production apply transaction archive",
    )


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_atomic(base, path: Path, payload: dict, *, mode: int = 0o400) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise base.GateError(f"unsafe transaction parent: {path.parent}")
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temp, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _active_transaction_path(base, envsafe) -> Path:
    return _apply_root(base, envsafe) / ACTIVE_TRANSACTION_NAME


def _assert_no_pending_transaction(base, envsafe) -> None:
    active = _active_transaction_path(base, envsafe)
    if active.exists() or active.is_symlink():
        raise base.GateError(
            f"unresolved production apply transaction exists: {active}; "
            "inspect/recover it before any new production apply"
        )


@contextmanager
def _exclusive_apply_lock(base, envsafe):
    root = _apply_root(base, envsafe)
    lock = root / LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise base.GateError("production apply lock file is unsafe")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise base.GateError("another production apply is already in progress") from exc
        yield lock
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _stable_previous_snapshot(base, ready) -> dict:
    if base.SERVICE.is_symlink() or not base.SERVICE.is_file():
        raise base.GateError("production service file is unsafe")
    before_hash = base.sha256(base.SERVICE)
    first = ready._read_main_process_identity(base)
    observed = ready._wait_for_stable_identity(
        base,
        expected_cwd=first["cwd"],
        expected_revision=first["revision"],
        required_pid=first["pid"],
        required_invocation_id=first["invocation_id"],
    )
    after_hash = base.sha256(base.SERVICE)
    if before_hash != after_hash:
        raise base.GateError("production service unit changed during stable previous-generation snapshot")
    return {
        "active": True,
        "pid": observed["pid"],
        "invocation_id": observed["invocation_id"],
        "cwd": observed["cwd"],
        "revision": observed["revision"],
        "service_sha256": after_hash,
        "stable_samples": observed["stable_samples"],
        "identity_attempts": observed["attempts"],
        "previous_generation_authority": PREVIOUS_GENERATION_AUTHORITY,
    }


def _verify_previous_generation(base, ready, previous: dict) -> dict:
    return ready._wait_for_stable_identity(
        base,
        expected_cwd=str(previous["cwd"]),
        expected_revision=str(previous["revision"]),
        required_pid=int(previous["pid"]),
        required_invocation_id=str(previous["invocation_id"]),
    )


def _service_backup(base, envsafe, expected_hash: str) -> tuple[Path, int, str]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""):
        raise base.GateError("previous service snapshot has no exact SHA-256")
    service = base.SERVICE
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    src_fd = os.open(service, flags)
    backup: Path | None = None
    try:
        info = os.fstat(src_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise base.GateError("production service must be a root-owned regular file")
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o022:
            raise base.GateError("production service must not be group/world writable")

        root = _backup_root(base, envsafe)
        backup = root / (
            f"webai-bridge.service.before-{base.TARGET_SHA[:12]}-"
            f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        )
        dst_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            dst_flags |= os.O_NOFOLLOW
        dst_fd = os.open(backup, dst_flags, 0o600)
        digest = hashlib.sha256()
        try:
            while True:
                chunk = os.read(src_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(dst_fd, view)
                    view = view[written:]
            os.fsync(dst_fd)
        finally:
            os.close(dst_fd)

        snapshot_hash = digest.hexdigest()
        if snapshot_hash != expected_hash:
            raise base.GateError(
                "production service changed between identity snapshot and root-only backup"
            )
        os.chmod(backup, 0o400)
        _fsync_dir(root)
        if base.sha256(service) != expected_hash:
            raise base.GateError("production service changed after root-only backup")
        if base.sha256(backup) != expected_hash:
            raise base.GateError("root-only rollback backup hash mismatch")
        return backup, mode, snapshot_hash
    except Exception:
        if backup is not None:
            backup.unlink(missing_ok=True)
        raise
    finally:
        os.close(src_fd)


def _transaction_payload(
    *,
    transaction_id: str,
    phase: str,
    controller_revision: str,
    base,
    prepared: dict,
    previous: dict,
    backup: Path,
    old_hash: str,
    candidate_hash: str,
    production_mutation: bool,
    production_mutation_possible: bool,
) -> dict:
    return {
        "transaction_id": transaction_id,
        "phase": phase,
        "controller_revision": controller_revision,
        "target_sha": base.TARGET_SHA,
        "target_tree": base.TARGET_TREE,
        "prepared_service_sha256": prepared.get("candidate_service_sha256"),
        "candidate_service_sha256": candidate_hash,
        "previous_service": previous,
        "old_service_sha256": old_hash,
        "backup_service": str(backup),
        "production_mutation": production_mutation,
        "production_mutation_possible": production_mutation_possible,
        "apply_authority": APPLY_AUTHORITY,
        "backup_authority": BACKUP_AUTHORITY,
        "transaction_authority": TRANSACTION_AUTHORITY,
        "lock_authority": LOCK_AUTHORITY,
        "previous_generation_authority": PREVIOUS_GENERATION_AUTHORITY,
        "live_payment_performed": False,
        "secrets_recorded": False,
    }


def _archive_transaction(base, envsafe, active: Path, payload: dict) -> Path:
    archive_root = _transaction_root(base, envsafe)
    final = archive_root / f"{payload['transaction_id']}.json"
    if final.exists() or final.is_symlink():
        raise base.GateError(f"transaction archive already exists: {final}")
    _write_json_atomic(base, final, payload, mode=0o400)
    active.unlink()
    _fsync_dir(active.parent)
    return final


def _install_apply_overlay(base, envsafe, host, ready, controller_revision: str) -> None:
    original_prepare = base.prepare
    original_restore = base.restore_previous_service

    def prepare_apply():
        _assert_no_pending_transaction(base, envsafe)
        prepared = original_prepare()
        host._require_controller_revision(base, controller_revision)
        return {
            **prepared,
            "production_apply_enabled": True,
            "apply_authority": APPLY_AUTHORITY,
            "backup_authority": BACKUP_AUTHORITY,
            "transaction_authority": TRANSACTION_AUTHORITY,
            "lock_authority": LOCK_AUTHORITY,
            "previous_generation_authority": PREVIOUS_GENERATION_AUTHORITY,
        }

    def restore_checked(backup: Path, *, expected_hash: str, expected_mode: int, previous: dict) -> dict:
        if backup.is_symlink() or not backup.is_file():
            raise base.GateError("rollback backup is not a regular file")
        if base.sha256(backup) != expected_hash:
            raise base.GateError("rollback backup hash mismatch before restore; refusing mutation")
        return original_restore(
            backup,
            expected_hash=expected_hash,
            expected_mode=expected_mode,
            previous=previous,
        )

    def apply_transactional(approval: str) -> Path:
        if approval.lower() != base.TARGET_SHA:
            raise base.GateError("approval must exactly equal pinned target SHA")
        if os.geteuid() != 0:
            raise base.GateError("production apply requires root")

        with _exclusive_apply_lock(base, envsafe):
            _assert_no_pending_transaction(base, envsafe)
            prepared = prepare_apply()
            host._require_controller_revision(base, controller_revision)
            base.systemd_composition()

            rendered = Path(prepared["render"]) / "webai-bridge.service"
            if rendered.is_symlink() or not rendered.is_file():
                raise base.GateError("rendered production service is unsafe")
            host._check_root_owned_tree(
                base,
                Path(prepared["render"]),
                label="rendered apply candidate",
                reject_symlinks=True,
            )
            candidate_hash = base.sha256(rendered)
            expected_candidate = str(prepared.get("candidate_service_sha256") or "")
            if candidate_hash != expected_candidate:
                raise base.GateError("rendered candidate changed after fresh prepare")

            previous = _stable_previous_snapshot(base, ready)
            old_hash = str(previous.get("service_sha256") or "")
            backup, old_mode, backup_hash = _service_backup(base, envsafe, old_hash)
            if backup_hash != old_hash:
                raise base.GateError("rollback backup does not match previous service")

            transaction_id = (
                f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-"
                f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            )
            active = _active_transaction_path(base, envsafe)
            transaction = _transaction_payload(
                transaction_id=transaction_id,
                phase="PREPARED_FOR_SWITCH",
                controller_revision=controller_revision,
                base=base,
                prepared=prepared,
                previous=previous,
                backup=backup,
                old_hash=old_hash,
                candidate_hash=candidate_hash,
                production_mutation=False,
                production_mutation_possible=False,
            )
            _write_json_atomic(base, active, transaction, mode=0o400)

            switched = False
            evidence_path: Path | None = None
            try:
                host._require_controller_revision(base, controller_revision)
                base.verify_source()
                if base.sha256(rendered) != candidate_hash:
                    raise base.GateError("rendered candidate changed immediately before switch")
                if base.sha256(base.SERVICE) != old_hash:
                    raise base.GateError("production service changed immediately before switch")
                _verify_previous_generation(base, ready, previous)

                transaction = {
                    **transaction,
                    "phase": "SWITCH_ARMED",
                    "production_mutation_possible": True,
                }
                _write_json_atomic(base, active, transaction, mode=0o400)

                base.atomic_install(rendered, base.SERVICE, 0o644)
                switched = True
                transaction = {
                    **transaction,
                    "phase": "SERVICE_REPLACED",
                    "production_mutation": True,
                }
                _write_json_atomic(base, active, transaction, mode=0o400)

                base.run("systemctl", "daemon-reload")
                base.systemd_composition()
                host._require_controller_revision(base, controller_revision)
                base.run("systemctl", "restart", "webai-bridge.service")
                transaction = {**transaction, "phase": "RESTART_ISSUED"}
                _write_json_atomic(base, active, transaction, mode=0o400)

                running = base.running_identity()
                health = base.https_health()
                base.stripe_acceptance()
                host._require_controller_revision(base, controller_revision)
                base.verify_source()
                if base.sha256(base.SERVICE) != candidate_hash:
                    raise base.GateError("installed production service hash drifted after acceptance")

                transaction = {**transaction, "phase": "ACCEPTANCE_PASS_PENDING_EVIDENCE"}
                _write_json_atomic(base, active, transaction, mode=0o400)
                success_payload = {
                    **prepared,
                    "status": "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS",
                    "production_mutation": True,
                    "production_apply_enabled": True,
                    "previous_service": previous,
                    "running_identity": running,
                    "https_health": health,
                    "stripe_external_acceptance": "PASS",
                    "old_service_sha256": old_hash,
                    "new_service_sha256": candidate_hash,
                    "backup_service": str(backup),
                    "transaction_id": transaction_id,
                    "apply_authority": APPLY_AUTHORITY,
                    "backup_authority": BACKUP_AUTHORITY,
                    "transaction_authority": TRANSACTION_AUTHORITY,
                    "lock_authority": LOCK_AUTHORITY,
                    "previous_generation_authority": PREVIOUS_GENERATION_AUTHORITY,
                    "live_payment_performed": False,
                    "secrets_recorded": False,
                }
                evidence_path = base.evidence(success_payload)
            except Exception as exc:
                rollback: dict = {"attempted": switched, "verified": False}
                rollback_error: str | None = None
                if switched:
                    try:
                        rollback = {
                            "attempted": True,
                            **restore_checked(
                                backup,
                                expected_hash=old_hash,
                                expected_mode=old_mode,
                                previous=previous,
                            ),
                        }
                    except Exception as rb_exc:
                        rollback_error = str(rb_exc)
                        rollback = {
                            "attempted": True,
                            "verified": False,
                            "error": rollback_error,
                        }

                status = (
                    "ROLLBACK_VERIFIED_AFTER_FAILURE"
                    if rollback.get("verified")
                    else ("ROLLBACK_FAILED" if switched else "PRE_SWITCH_FAILURE")
                )
                failure_payload = {
                    **prepared,
                    "status": status,
                    "error": str(exc),
                    "old_service_sha256": old_hash,
                    "candidate_service_sha256": candidate_hash,
                    "previous_service": previous,
                    "rollback": rollback,
                    "production_mutation": switched,
                    "production_apply_enabled": True,
                    "backup_service": str(backup),
                    "transaction_id": transaction_id,
                    "apply_authority": APPLY_AUTHORITY,
                    "backup_authority": BACKUP_AUTHORITY,
                    "transaction_authority": TRANSACTION_AUTHORITY,
                    "lock_authority": LOCK_AUTHORITY,
                    "previous_generation_authority": PREVIOUS_GENERATION_AUTHORITY,
                    "live_payment_performed": False,
                    "secrets_recorded": False,
                }
                failure_evidence: Path | None = None
                try:
                    failure_evidence = base.evidence(failure_payload)
                except Exception as evidence_exc:
                    if rollback_error:
                        rollback_error = f"{rollback_error}; evidence_write={evidence_exc}"
                    else:
                        rollback_error = f"evidence_write={evidence_exc}"

                terminal_transaction = {
                    **transaction,
                    "phase": status,
                    "error": str(exc),
                    "rollback": rollback,
                    **({"evidence": str(failure_evidence)} if failure_evidence else {}),
                }
                if status in {"ROLLBACK_VERIFIED_AFTER_FAILURE", "PRE_SWITCH_FAILURE"}:
                    try:
                        _archive_transaction(base, envsafe, active, terminal_transaction)
                    except Exception as archive_exc:
                        raise base.GateError(
                            "deploy failed and transaction finalization failed; "
                            f"deploy_cause={exc}; archive_cause={archive_exc}; "
                            f"evidence={failure_evidence or '<unavailable>'}"
                        ) from exc
                else:
                    _write_json_atomic(base, active, terminal_transaction, mode=0o400)

                if rollback_error:
                    raise base.GateError(
                        "deploy failed and rollback/evidence verification failed; "
                        f"evidence={failure_evidence or '<unavailable>'}; "
                        f"deploy_cause={exc}; rollback_cause={rollback_error}"
                    ) from exc
                raise base.GateError(
                    f"deploy failed; evidence={failure_evidence or '<unavailable>'}; cause={exc}"
                ) from exc

            if evidence_path is None:
                raise base.GateError("production acceptance completed without durable evidence")
            committed = {
                **transaction,
                "phase": "COMMITTED",
                "evidence": str(evidence_path),
            }
            try:
                _archive_transaction(base, envsafe, active, committed)
            except Exception as archive_exc:
                _write_json_atomic(
                    base,
                    active,
                    {
                        **committed,
                        "phase": "COMMITTED_EVIDENCE_WRITTEN_ARCHIVE_FAILED",
                        "transaction_finalize_error": str(archive_exc),
                    },
                    mode=0o400,
                )
                raise base.GateError(
                    "production is accepted and evidence is durable, but transaction archive "
                    f"finalization failed; evidence={evidence_path}; cause={archive_exc}"
                ) from archive_exc
            return evidence_path

    base.prepare = prepare_apply
    base.apply = apply_transactional
    base.restore_previous_service = restore_checked


def main() -> int:
    controller_revision = _validate_and_clean_bootstrap_environment()
    envsafe = _load_committed(
        controller_revision,
        ENVSAFE_PATH,
        "exact_head_deploy_apply_envsafe",
    )
    if BOOTSTRAP_ALLOWED_ENV_KEYS != envsafe.BOOTSTRAP_ALLOWED_ENV_KEYS:
        raise RuntimeError("apply bootstrap allowlist drifted from canonical env-safe controller")
    base = _load_committed(
        controller_revision,
        envsafe.BASE_PATH,
        "exact_head_deploy_apply_base",
    )
    host = _load_committed(
        controller_revision,
        envsafe.HOSTSAFE_PATH,
        "exact_head_deploy_apply_host",
    )
    ready = _load_committed(
        controller_revision,
        envsafe.READY_PATH,
        "exact_head_deploy_apply_ready",
    )

    envsafe._pin_target(base)
    envsafe._install_envsafe_overlay(base, host, controller_revision)
    ready._install_readiness_overlay(base)
    _install_apply_overlay(base, envsafe, host, ready, controller_revision)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
