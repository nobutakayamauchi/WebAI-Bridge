from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import types
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
INNER_PATH = "deploy/exact_head_deploy_hostsafe.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
READINESS_TIMEOUT_SECONDS = 15.0
READINESS_POLL_SECONDS = 0.25
READINESS_STABLE_SAMPLES = 2
HEALTH_POLL_SECONDS = 0.5
HEALTH_ATTEMPT_TIMEOUT_SECONDS = 5.0


def _run_git(*args: str) -> str:
    git_bin = Path("/usr/bin/git")
    if not git_bin.is_file() or git_bin.is_symlink():
        raise RuntimeError("trusted /usr/bin/git is unavailable")
    completed = subprocess.run(
        [str(git_bin), "-C", str(CONTROL), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"controller git command failed: {detail}")
    return completed.stdout.strip()


def _controller_revision_from_env() -> str:
    revision = (os.environ.get(CONTROLLER_REVISION_ENV) or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError(
            f"{CONTROLLER_REVISION_ENV} must pin the exact 40-hex controller revision"
        )
    actual = _run_git("rev-parse", "HEAD").lower()
    if actual != revision:
        raise RuntimeError(
            f"controller HEAD changed before readiness wrapper start: expected {revision}, got {actual}"
        )
    return revision


def _load_committed_inner(controller_revision: str):
    obj = f"{controller_revision}:{INNER_PATH}"
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "show", obj],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed host-safe deploy capsule: {detail}")
    module = types.ModuleType("exact_head_deploy_hostsafe_committed_inner")
    module.__file__ = f"git:{CONTROL}:{obj}"
    sys.modules[module.__name__] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _read_systemd_value(base, property_name: str) -> str:
    return base.run(
        "systemctl",
        "show",
        "webai-bridge.service",
        f"--property={property_name}",
        "--value",
    ).strip()


def _read_main_process_identity(base) -> dict:
    active = _read_systemd_value(base, "ActiveState")
    if active != "active":
        raise base.GateError(f"service ActiveState is not active: {active or '<empty>'}")

    invocation_before = _read_systemd_value(base, "InvocationID").lower()
    if not re.fullmatch(r"[0-9a-f]{32}", invocation_before):
        raise base.GateError(
            f"service has no exact systemd InvocationID: {invocation_before or '<empty>'}"
        )

    pid_before = _read_systemd_value(base, "MainPID")
    if not pid_before.isdigit() or int(pid_before) <= 0:
        raise base.GateError(f"service has no live MainPID: {pid_before or '<empty>'}")
    pid = int(pid_before)

    try:
        cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
        revision = base.process_revision(pid)
        raw_cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError) as exc:
        raise base.GateError(f"process {pid} identity is not readable yet: {exc}") from exc

    cmd = [x.decode(errors="replace") for x in raw_cmd.split(b"\0") if x]
    pid_after = _read_systemd_value(base, "MainPID")
    invocation_after = _read_systemd_value(base, "InvocationID").lower()
    if pid_after != pid_before:
        raise base.GateError(f"MainPID changed during identity observation: {pid_before}->{pid_after}")
    if invocation_after != invocation_before:
        raise base.GateError(
            f"systemd InvocationID changed during identity observation: "
            f"{invocation_before}->{invocation_after}"
        )

    return {
        "pid": pid,
        "invocation_id": invocation_before,
        "cwd": str(cwd),
        "revision": revision,
        "cmd": cmd,
    }


def _wait_for_stable_identity(
    base,
    *,
    expected_cwd: str,
    expected_revision: str,
    required_cmd_tokens: tuple[str, ...] = (),
    required_pid: int | None = None,
    required_invocation_id: str | None = None,
    timeout: float = READINESS_TIMEOUT_SECONDS,
    poll: float = READINESS_POLL_SECONDS,
    stable_samples: int = READINESS_STABLE_SAMPLES,
) -> dict:
    if timeout <= 0 or poll <= 0 or stable_samples < 2:
        raise base.GateError("invalid readiness stabilization policy")
    if not expected_cwd or not Path(expected_cwd).is_absolute():
        raise base.GateError("expected readiness cwd must be an absolute path")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_revision or ""):
        raise base.GateError("expected readiness revision must be an exact 40-hex SHA")
    if required_pid is not None and required_pid <= 0:
        raise base.GateError("required readiness MainPID must be positive")
    if required_invocation_id is not None:
        required_invocation_id = required_invocation_id.lower()
        if not re.fullmatch(r"[0-9a-f]{32}", required_invocation_id):
            raise base.GateError("required readiness InvocationID must be exact 32-hex")

    expected_cwd_resolved = str(Path(expected_cwd).resolve())
    deadline = time.monotonic() + timeout
    stable_generation: tuple[int, str] | None = None
    stable_count = 0
    attempts = 0
    last_reason = "no observation"

    while True:
        attempts += 1
        try:
            observed = _read_main_process_identity(base)
            if required_pid is not None and observed["pid"] != required_pid:
                raise base.GateError(
                    f"MainPID generation changed: {observed['pid']} != required {required_pid}"
                )
            if (
                required_invocation_id is not None
                and observed["invocation_id"] != required_invocation_id
            ):
                raise base.GateError(
                    "systemd invocation generation changed: "
                    f"{observed['invocation_id']} != required {required_invocation_id}"
                )
            if observed["cwd"] != expected_cwd_resolved:
                raise base.GateError(
                    f"cwd mismatch: {observed['cwd']} != {expected_cwd_resolved}"
                )
            if observed["revision"].lower() != expected_revision.lower():
                raise base.GateError(
                    f"revision mismatch: {observed['revision']} != {expected_revision}"
                )
            missing = [token for token in required_cmd_tokens if token not in observed["cmd"]]
            if missing:
                raise base.GateError(f"command surface missing tokens: {missing}")

            generation = (observed["pid"], observed["invocation_id"])
            if generation == stable_generation:
                stable_count += 1
            else:
                stable_generation = generation
                stable_count = 1

            if stable_count >= stable_samples:
                return {
                    **observed,
                    "stable_samples": stable_count,
                    "attempts": attempts,
                    "readiness_timeout_seconds": timeout,
                }
            last_reason = (
                "identity matched but is not stable yet for "
                f"pid {observed['pid']} invocation {observed['invocation_id']}"
            )
        except Exception as exc:
            stable_generation = None
            stable_count = 0
            last_reason = str(exc)

        now = time.monotonic()
        if now >= deadline:
            raise base.GateError(
                f"service identity did not stabilize within {timeout:.1f}s after {attempts} attempts; "
                f"last={last_reason}"
            )
        time.sleep(min(poll, max(0.0, deadline - now)))


def _probe_exact_health(base, attempt_timeout: float) -> dict:
    if attempt_timeout <= 0:
        raise base.GateError("HTTPS health attempt timeout must be positive")
    url = f"https://{base.DOMAIN}/health"
    with base.urllib.request.urlopen(url, timeout=attempt_timeout) as response:
        final_url = response.geturl()
        if final_url != url:
            raise base.GateError(f"HTTPS health redirected: {final_url}")
        if response.status != 200:
            raise base.GateError(f"HTTPS health={response.status}")
        raw = response.read(4096)
    try:
        payload = base.json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise base.GateError(f"HTTPS health returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise base.GateError("HTTPS health body does not prove application readiness")
    return {
        "url": url,
        "status": 200,
        "body_status": "ok",
        "app_count": payload.get("app_count"),
        "pricing_version": payload.get("pricing_version"),
    }


def _wait_for_stable_health(
    base,
    health_probe,
    *,
    timeout: float = READINESS_TIMEOUT_SECONDS,
    poll: float = HEALTH_POLL_SECONDS,
    stable_samples: int = READINESS_STABLE_SAMPLES,
    attempt_timeout: float = HEALTH_ATTEMPT_TIMEOUT_SECONDS,
) -> dict:
    if timeout <= 0 or poll <= 0 or stable_samples < 2 or attempt_timeout <= 0:
        raise base.GateError("invalid HTTPS readiness stabilization policy")
    deadline = time.monotonic() + timeout
    stable_count = 0
    attempts = 0
    last_reason = "no health observation"
    latest: dict | None = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise base.GateError(
                f"HTTPS application health did not stabilize within {timeout:.1f}s after {attempts} attempts; "
                f"last={last_reason}"
            )
        attempts += 1
        try:
            latest = health_probe(min(attempt_timeout, remaining))
            stable_count += 1
            if stable_count >= stable_samples:
                return {
                    **latest,
                    "stable_samples": stable_count,
                    "health_attempts": attempts,
                    "readiness_timeout_seconds": timeout,
                    "max_attempt_timeout_seconds": attempt_timeout,
                }
            last_reason = "application health matched but is not stable yet"
        except Exception as exc:
            stable_count = 0
            latest = None
            last_reason = str(exc)

        now = time.monotonic()
        if now >= deadline:
            raise base.GateError(
                f"HTTPS application health did not stabilize within {timeout:.1f}s after {attempts} attempts; "
                f"last={last_reason}"
            )
        time.sleep(min(poll, max(0.0, deadline - now)))


def _install_readiness_overlay(base) -> None:
    original_prepare = base.prepare
    original_stripe_acceptance = base.stripe_acceptance
    original_evidence = base.evidence
    state: dict[str, object] = {}

    def raw_health_probe(attempt_timeout: float) -> dict:
        return _probe_exact_health(base, attempt_timeout)

    def prepare_with_readiness_policy():
        prepared = original_prepare()
        return {
            **prepared,
            "runtime_identity_readiness": {
                "mode": "BOUNDED_STABLE_SYSTEMD_GENERATION_POLL_V3",
                "timeout_seconds": READINESS_TIMEOUT_SECONDS,
                "poll_seconds": READINESS_POLL_SECONDS,
                "stable_samples": READINESS_STABLE_SAMPLES,
                "pid_rechecked_during_sample": True,
                "invocation_id_rechecked_during_sample": True,
                "generation_identity": "InvocationID+MainPID",
                "same_generation_through_health_and_acceptance": True,
            },
            "https_readiness": {
                "mode": "STRICT_BOUNDED_APPLICATION_HEALTH_POLL_V2",
                "timeout_seconds": READINESS_TIMEOUT_SECONDS,
                "poll_seconds": HEALTH_POLL_SECONDS,
                "stable_samples": READINESS_STABLE_SAMPLES,
                "max_attempt_timeout_seconds": HEALTH_ATTEMPT_TIMEOUT_SECONDS,
                "rollback_health_required": True,
                "post_stripe_health_required": True,
            },
        }

    def target_generation() -> tuple[int, str]:
        target_pid = state.get("target_pid")
        target_invocation_id = state.get("target_invocation_id")
        if not isinstance(target_pid, int) or not isinstance(target_invocation_id, str):
            raise base.GateError("target systemd generation was not pinned")
        return target_pid, target_invocation_id

    def verify_target_generation() -> dict:
        target_pid, target_invocation_id = target_generation()
        return _wait_for_stable_identity(
            base,
            expected_cwd=str(base.RELEASE / "runtime"),
            expected_revision=base.TARGET_SHA,
            required_cmd_tokens=("commercial_handoff:app", "--no-access-log"),
            required_pid=target_pid,
            required_invocation_id=target_invocation_id,
        )

    def running_identity_stable() -> dict:
        observed = _wait_for_stable_identity(
            base,
            expected_cwd=str(base.RELEASE / "runtime"),
            expected_revision=base.TARGET_SHA,
            required_cmd_tokens=("commercial_handoff:app", "--no-access-log"),
        )
        state["target_pid"] = observed["pid"]
        state["target_invocation_id"] = observed["invocation_id"]
        return {
            "pid": observed["pid"],
            "invocation_id": observed["invocation_id"],
            "cwd": observed["cwd"],
            "revision": base.TARGET_SHA,
            "no_access_log": True,
            "stable_samples": observed["stable_samples"],
            "identity_attempts": observed["attempts"],
            "readiness_timeout_seconds": observed["readiness_timeout_seconds"],
        }

    def https_health_stable() -> dict:
        target_pid, target_invocation_id = target_generation()
        health = _wait_for_stable_health(base, raw_health_probe)
        verify_target_generation()
        return {
            **health,
            "verified_main_pid": target_pid,
            "verified_invocation_id": target_invocation_id,
        }

    def stripe_acceptance_same_generation() -> None:
        target_pid, target_invocation_id = target_generation()
        verify_target_generation()
        original_stripe_acceptance()
        verify_target_generation()
        final_health = _wait_for_stable_health(base, raw_health_probe)
        verify_target_generation()
        state["post_stripe_health"] = {
            **final_health,
            "verified_main_pid": target_pid,
            "verified_invocation_id": target_invocation_id,
        }

    def restore_previous_service_stable(
        backup: Path,
        *,
        expected_hash: str,
        expected_mode: int,
        previous: dict,
    ) -> dict:
        base.atomic_install(backup, base.SERVICE, expected_mode)
        base.run("systemctl", "daemon-reload")
        base.systemd_composition()
        restored_hash = base.sha256(base.SERVICE)
        if restored_hash != expected_hash:
            raise base.GateError("rollback service hash mismatch after restore")
        previous_cwd = str(previous.get("cwd") or "")
        previous_revision = str(previous.get("revision") or "")
        if not previous_cwd or not previous_revision:
            raise base.GateError("rollback previous identity evidence is incomplete")
        base.run("systemctl", "restart", "webai-bridge.service")
        observed = _wait_for_stable_identity(
            base,
            expected_cwd=previous_cwd,
            expected_revision=previous_revision,
        )
        rollback_health = _wait_for_stable_health(base, raw_health_probe)
        _wait_for_stable_identity(
            base,
            expected_cwd=previous_cwd,
            expected_revision=previous_revision,
            required_pid=observed["pid"],
            required_invocation_id=observed["invocation_id"],
        )
        return {
            "verified": True,
            "service_sha256": restored_hash,
            "pid": observed["pid"],
            "invocation_id": observed["invocation_id"],
            "cwd": observed["cwd"],
            "revision": observed["revision"],
            "stable_samples": observed["stable_samples"],
            "identity_attempts": observed["attempts"],
            "readiness_timeout_seconds": observed["readiness_timeout_seconds"],
            "https_health": rollback_health,
        }

    def evidence_with_readiness(payload: dict) -> Path:
        final_health = state.get("post_stripe_health")
        if isinstance(final_health, dict):
            payload = {**payload, "post_stripe_https_health": final_health}
        return original_evidence(payload)

    base.prepare = prepare_with_readiness_policy
    base.running_identity = running_identity_stable
    base.https_health = https_health_stable
    base.stripe_acceptance = stripe_acceptance_same_generation
    base.restore_previous_service = restore_previous_service_stable
    base.evidence = evidence_with_readiness


def main() -> int:
    controller_revision = _controller_revision_from_env()
    inner = _load_committed_inner(controller_revision)
    original_install = inner._install_overlay

    def install_with_readiness(base, expected_revision: str) -> None:
        original_install(base, expected_revision)
        _install_readiness_overlay(base)

    inner._install_overlay = install_with_readiness
    return inner.main()


if __name__ == "__main__":
    raise SystemExit(main())
