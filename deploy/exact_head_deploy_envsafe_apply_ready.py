from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import types
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
INNER_PATH = "deploy/exact_head_deploy_envsafe_apply.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
BOOTSTRAP_CLEAN_ENV = "WEB_AI_BOOTSTRAP_CLEAN"
PRE_MUTATION_GENERATION_AUTHORITY = "PRE_MUTATION_GENERATION_REBOUND_V2"
BOOTSTRAP_CONTROLLER_TRUST_AUTHORITY = "ROOT_OWNED_GIT_BEFORE_FIRST_GIT_V1"
EXPECTED_PREVIOUS_SHA = "9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1"
ROLLBACK_STATE_COMPATIBILITY_AUTHORITY = "EXACT_SHARED_STATE_SCHEMA_BLOB_EQUIVALENCE_V1"
SHARED_STATE_SCHEMA_BLOBS = {
    "runtime/entitlements.py": "dec40737f60cee22170e0996e856de98cb369a93",
    "runtime/checkout_state.py": "e40312626d77f5322108ce97d6d6878385e3f46b",
    "runtime/handoff_tickets.py": "9c71b08605ab1ab02a309cba52fea249313f8114",
}

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


def _assert_root_owned_nonwritable(path: Path, *, label: str, directory: bool | None = None) -> None:
    if path.is_symlink():
        raise RuntimeError(f"{label} must not be a symlink: {path}")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} is missing: {path}") from exc
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"{label} must be a directory: {path}")
    if directory is False and not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"{label} must be a regular file: {path}")
    if info.st_uid != 0:
        raise RuntimeError(f"{label} must be root-owned: {path}")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise RuntimeError(f"{label} must not be group/world writable: {path}")


def _validate_controller_root_trust() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("apply-ready bootstrap requires root")
    _assert_root_owned_nonwritable(CONTROL, label="controller root", directory=True)
    git_dir = CONTROL / ".git"
    _assert_root_owned_nonwritable(git_dir, label="controller Git directory", directory=True)
    for root, dirs, files in os.walk(git_dir, topdown=True, followlinks=False):
        root_path = Path(root)
        _assert_root_owned_nonwritable(root_path, label="controller Git directory", directory=True)
        for name in list(dirs):
            child = root_path / name
            _assert_root_owned_nonwritable(child, label="controller Git directory", directory=True)
        for name in files:
            child = root_path / name
            _assert_root_owned_nonwritable(child, label="controller Git file", directory=False)


def _validated_bootstrap() -> tuple[str, dict[str, str]]:
    _validate_controller_root_trust()
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
            "apply-ready bootstrap environment is not clean; unexpected keys: "
            + ", ".join(unexpected)
        )
    if env.get("PATH") not in (None, "/usr/bin:/bin"):
        raise RuntimeError("apply-ready bootstrap PATH must be exactly /usr/bin:/bin")

    git_env = {
        **env,
        "PATH": "/usr/bin:/bin",
        "HOME": "/root",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        env=git_env,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"controller Git identity check failed: {detail}")
    actual = completed.stdout.strip().lower()
    if actual != revision:
        raise RuntimeError(
            f"controller HEAD changed before apply-ready wrapper start: expected {revision}, got {actual}"
        )
    return revision, git_env


def _load_committed(revision: str, git_env: dict[str, str]):
    obj = f"{revision}:{INNER_PATH}"
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "show", obj],
        check=False,
        capture_output=True,
        text=True,
        env=git_env,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed transactional apply capsule: {detail}")
    module = types.ModuleType("exact_head_deploy_envsafe_apply_committed_inner")
    module.__file__ = f"git:{CONTROL}:{obj}"
    sys.modules[module.__name__] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _same_previous_generation(left: dict, right: dict) -> bool:
    fields = ("pid", "invocation_id", "cwd", "revision", "service_sha256")
    return all(left.get(field) == right.get(field) for field in fields)


def _verify_shared_state_compatibility(base) -> dict[str, str]:
    base.run(
        "/usr/bin/git",
        "-C",
        str(CONTROL),
        "fetch",
        "--no-tags",
        "origin",
        EXPECTED_PREVIOUS_SHA,
    )
    if base.git(CONTROL, "rev-parse", f"{EXPECTED_PREVIOUS_SHA}^{{commit}}").lower() != EXPECTED_PREVIOUS_SHA:
        raise base.GateError("supported previous production commit identity mismatch")

    observed: dict[str, str] = {}
    for path, expected_blob in SHARED_STATE_SCHEMA_BLOBS.items():
        previous_blob = base.git(CONTROL, "rev-parse", f"{EXPECTED_PREVIOUS_SHA}:{path}").lower()
        target_blob = base.git(CONTROL, "rev-parse", f"{base.TARGET_SHA}:{path}").lower()
        if previous_blob != expected_blob or target_blob != expected_blob:
            raise base.GateError(
                f"shared-state rollback compatibility drifted for {path}: "
                f"previous={previous_blob}, target={target_blob}, expected={expected_blob}"
            )
        observed[path] = expected_blob
    return observed


def _install_human_gate_overlay(inner) -> None:
    original_install = inner._install_apply_overlay

    def install_with_human_gate(base, envsafe, host, ready, controller_revision: str) -> None:
        original_install(base, envsafe, host, ready, controller_revision)
        original_prepare = base.prepare
        original_apply = base.apply
        original_evidence = base.evidence
        original_stable_previous = inner._stable_previous_snapshot
        state: dict[str, object] = {}

        def prepare_with_previous_generation():
            prepared = original_prepare()
            base.systemd_composition()
            previous = original_stable_previous(base, ready)
            shared_state_blobs = _verify_shared_state_compatibility(base)
            previous_revision = str(previous.get("revision") or "").lower()
            return {
                **prepared,
                "previous_production_snapshot": previous,
                "target_already_active": previous_revision == base.TARGET_SHA.lower(),
                "previous_production_supported": previous_revision == EXPECTED_PREVIOUS_SHA,
                "expected_previous_revision": EXPECTED_PREVIOUS_SHA,
                "pre_mutation_generation_authority": PRE_MUTATION_GENERATION_AUTHORITY,
                "bootstrap_controller_trust_authority": BOOTSTRAP_CONTROLLER_TRUST_AUTHORITY,
                "rollback_state_compatibility_authority": ROLLBACK_STATE_COMPATIBILITY_AUTHORITY,
                "rollback_shared_state_schema_blobs": shared_state_blobs,
            }

        def stable_previous_rebound(base_arg, ready_arg):
            observed = original_stable_previous(base_arg, ready_arg)
            pinned = state.get("pre_mutation_previous")
            if isinstance(pinned, dict):
                if not _same_previous_generation(pinned, observed):
                    raise base.GateError(
                        "previous production generation changed between apply entry and mutation"
                    )
                state["generation_revalidated"] = True
            return observed

        def apply_with_human_gate_rebind(approval: str):
            if approval.lower() != base.TARGET_SHA:
                raise base.GateError("approval must exactly equal pinned target SHA")
            previous = original_stable_previous(base, ready)
            previous_revision = str(previous.get("revision") or "").lower()
            if previous_revision == base.TARGET_SHA.lower():
                raise base.GateError(
                    "target revision is already active; refusing redundant production mutation"
                )
            if previous_revision != EXPECTED_PREVIOUS_SHA:
                raise base.GateError(
                    "current production revision is not the reviewed rollback baseline; "
                    f"expected {EXPECTED_PREVIOUS_SHA}, got {previous_revision or '<missing>'}"
                )
            _verify_shared_state_compatibility(base)
            state["pre_mutation_previous"] = previous
            state["generation_revalidated"] = False
            inner._stable_previous_snapshot = stable_previous_rebound
            try:
                return original_apply(approval)
            finally:
                inner._stable_previous_snapshot = original_stable_previous

        def evidence_with_human_gate(payload: dict) -> Path:
            previous = state.get("pre_mutation_previous")
            if isinstance(previous, dict):
                payload = {
                    **payload,
                    "pre_mutation_previous_production_snapshot": previous,
                    "pre_mutation_generation_revalidated": bool(
                        state.get("generation_revalidated")
                    ),
                    "pre_mutation_generation_authority": PRE_MUTATION_GENERATION_AUTHORITY,
                    "bootstrap_controller_trust_authority": BOOTSTRAP_CONTROLLER_TRUST_AUTHORITY,
                    "expected_previous_revision": EXPECTED_PREVIOUS_SHA,
                    "rollback_state_compatibility_authority": ROLLBACK_STATE_COMPATIBILITY_AUTHORITY,
                    "rollback_shared_state_schema_blobs": dict(SHARED_STATE_SCHEMA_BLOBS),
                }
            return original_evidence(payload)

        base.prepare = prepare_with_previous_generation
        base.apply = apply_with_human_gate_rebind
        base.evidence = evidence_with_human_gate

    inner._install_apply_overlay = install_with_human_gate


def main() -> int:
    revision, git_env = _validated_bootstrap()
    inner = _load_committed(revision, git_env)
    if BOOTSTRAP_ALLOWED_ENV_KEYS != inner.BOOTSTRAP_ALLOWED_ENV_KEYS:
        raise RuntimeError("apply-ready bootstrap allowlist drifted from inner apply capsule")
    _install_human_gate_overlay(inner)
    return inner.main()


if __name__ == "__main__":
    raise SystemExit(main())
