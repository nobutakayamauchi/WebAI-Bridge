from __future__ import annotations

import os
import re
import subprocess
import sys
import types
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
INNER_PATH = "deploy/exact_head_deploy_envsafe_apply.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
BOOTSTRAP_CLEAN_ENV = "WEB_AI_BOOTSTRAP_CLEAN"
HUMAN_GATE_AUTHORITY = "PRE_APPLY_GENERATION_REBOUND_BEFORE_MUTATION_V1"

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


def _validated_bootstrap() -> tuple[str, dict[str, str]]:
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
            return {
                **prepared,
                "previous_production_snapshot": previous,
                "target_already_active": (
                    str(previous.get("revision") or "").lower() == base.TARGET_SHA.lower()
                ),
                "human_gate_authority": HUMAN_GATE_AUTHORITY,
            }

        def stable_previous_rebound(base_arg, ready_arg):
            observed = original_stable_previous(base_arg, ready_arg)
            pinned = state.get("human_gate_previous")
            if isinstance(pinned, dict):
                if not _same_previous_generation(pinned, observed):
                    raise base.GateError(
                        "previous production generation changed after Human Gate and before mutation"
                    )
                state["generation_revalidated"] = True
            return observed

        def apply_with_human_gate_rebind(approval: str):
            if approval.lower() != base.TARGET_SHA:
                raise base.GateError("approval must exactly equal pinned target SHA")
            previous = original_stable_previous(base, ready)
            if str(previous.get("revision") or "").lower() == base.TARGET_SHA.lower():
                raise base.GateError(
                    "target revision is already active; refusing redundant production mutation"
                )
            state["human_gate_previous"] = previous
            state["generation_revalidated"] = False
            inner._stable_previous_snapshot = stable_previous_rebound
            try:
                return original_apply(approval)
            finally:
                inner._stable_previous_snapshot = original_stable_previous

        def evidence_with_human_gate(payload: dict) -> Path:
            previous = state.get("human_gate_previous")
            if isinstance(previous, dict):
                payload = {
                    **payload,
                    "human_gate_previous_production_snapshot": previous,
                    "human_gate_generation_revalidated": bool(
                        state.get("generation_revalidated")
                    ),
                    "human_gate_authority": HUMAN_GATE_AUTHORITY,
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
