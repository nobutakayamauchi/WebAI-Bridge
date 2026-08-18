from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import types
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
BASE_PATH = "deploy/exact_head_deploy.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
OVERLAY_ID = "EXECSTARTPRE_SCOPED_GIT_SAFE_DIRECTORY_V2"
RELEASE_ROOT = Path("/opt/webai-bridge-releases")
RUNTIME_ENV_LOCKS = (
    "LD_PRELOAD=",
    "LD_AUDIT=",
    "LD_LIBRARY_PATH=",
    "PYTHONPATH=",
    "PYTHONHOME=",
    "PYTHONNOUSERSITE=1",
)
TRUST_ENV_UNSET = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
)


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
            f"controller HEAD changed before wrapper start: expected {revision}, got {actual}"
        )
    return revision


def _load_committed_base(controller_revision: str):
    base_object = f"{controller_revision}:{BASE_PATH}"
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "show", base_object],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed deploy capsule: {detail}")
    module = types.ModuleType("exact_head_deploy_committed_base")
    module.__file__ = f"git:{CONTROL}:{base_object}"
    sys.modules[module.__name__] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _require_controller_revision(base, expected: str) -> None:
    actual = base.git(base.CONTROL, "rev-parse", "HEAD").strip().lower()
    if actual != expected:
        raise base.GateError(
            f"controller revision moved during deploy capsule execution: expected {expected}, got {actual}"
        )


def _check_root_owned_path(base, path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise base.GateError(f"{label} is missing: {path}") from exc
    if info.st_uid != 0:
        raise base.GateError(f"{label} must remain root-owned: {path}")
    if not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) & 0o022:
        raise base.GateError(f"{label} must not be group/world writable: {path}")


def _check_root_owned_tree(
    base,
    root: Path,
    *,
    label: str,
    skip: set[str] | None = None,
    reject_symlinks: bool = False,
) -> None:
    skip = set(skip or ())
    _check_root_owned_path(base, root, label=label)
    if reject_symlinks and root.is_symlink():
        raise base.GateError(f"{label} must not be a symlink: {root}")
    for current, child_dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_root = current_path.relative_to(root).as_posix()
        if rel_root == ".":
            rel_root = ""
        for name in list(child_dirs):
            path = current_path / name
            rel = f"{rel_root}/{name}".lstrip("/")
            if rel in skip:
                child_dirs.remove(name)
                continue
            _check_root_owned_path(base, path, label=label)
            if path.is_symlink():
                if reject_symlinks:
                    raise base.GateError(f"{label} must not contain symlinks: {path}")
                child_dirs.remove(name)
        for name in files:
            path = current_path / name
            rel = f"{rel_root}/{name}".lstrip("/")
            if rel in skip:
                continue
            _check_root_owned_path(base, path, label=label)
            if reject_symlinks and path.is_symlink():
                raise base.GateError(f"{label} must not contain symlinks: {path}")


def _verify_runtime_immutability(base) -> None:
    expected_release = RELEASE_ROOT / base.TARGET_SHA
    if base.RELEASE != expected_release:
        raise base.GateError(
            f"release path does not match pinned target: {base.RELEASE} != {expected_release}"
        )
    _check_root_owned_path(base, RELEASE_ROOT, label="release root")
    _check_root_owned_tree(
        base,
        base.RELEASE,
        label="exact release source",
        skip={"runtime/.venv"},
        reject_symlinks=True,
    )
    _check_root_owned_path(base, base.VENV.parent, label="venv root")
    _check_root_owned_tree(base, base.VENV, label="exact release venv")
    _check_root_owned_path(base, base.CONTROL, label="controller root")
    _check_root_owned_tree(base, base.CONTROL / ".git", label="controller Git metadata")


def _scope_preflight_git_trust(base, service: Path) -> str:
    release = str(base.RELEASE)
    if not Path(release).is_absolute() or not re.fullmatch(r"/[A-Za-z0-9._/-]+", release):
        raise base.GateError(f"unsafe release path for scoped Git trust: {release}")
    expected_release = RELEASE_ROOT / base.TARGET_SHA
    if base.RELEASE != expected_release:
        raise base.GateError(
            f"release path does not match pinned target: {base.RELEASE} != {expected_release}"
        )
    env_bin = Path("/usr/bin/env")
    if not env_bin.is_file() or env_bin.is_symlink():
        raise base.GateError("trusted /usr/bin/env is unavailable")
    if service.is_symlink() or not service.is_file():
        raise base.GateError("rendered service must be a regular non-symlink file")

    raw_hash = base.sha256(service)
    raw_text = service.read_text(encoding="utf-8")
    lines = raw_text.splitlines()
    matches = [index for index, line in enumerate(lines) if line.startswith("ExecStartPre=")]
    if len(matches) != 1:
        raise base.GateError(f"expected exactly one ExecStartPre, got {len(matches)}")
    env_file_line = f"EnvironmentFile=-{base.ENV_FILE}"
    env_matches = [index for index, line in enumerate(lines) if line == env_file_line]
    if len(env_matches) != 1:
        raise base.GateError(f"expected exactly one canonical EnvironmentFile, got {len(env_matches)}")
    for lock in RUNTIME_ENV_LOCKS:
        if f"Environment={lock}" in lines:
            raise base.GateError(f"target-rendered service already carries runtime env lock: {lock}")

    index = matches[0]
    command = lines[index].split("=", 1)[1].strip()
    expected_command = (
        f"{release}/runtime/.venv/bin/python "
        f"{release}/runtime/deployment_preflight_handoff.py"
    )
    if command != expected_command:
        raise base.GateError(
            f"unexpected rendered ExecStartPre for scoped Git trust: {command}"
        )
    if "GIT_CONFIG_" in command or "safe.directory" in command:
        raise base.GateError("rendered ExecStartPre already carries Git trust configuration")

    unset = " ".join(f"-u {name}" for name in TRUST_ENV_UNSET)
    scoped = (
        f"/usr/bin/env {unset} "
        "PATH=/usr/bin:/bin "
        "PYTHONPATH= "
        "PYTHONHOME= "
        "GIT_CONFIG_SYSTEM=/dev/null "
        "GIT_CONFIG_GLOBAL=/dev/null "
        "GIT_CONFIG_NOSYSTEM=1 "
        "GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        f"GIT_CONFIG_VALUE_0={release} "
        f"{command}"
    )
    expected_lines = list(lines)
    expected_lines[index] = "ExecStartPre=" + scoped
    env_insert = env_matches[0] + 1
    for offset, lock in enumerate(RUNTIME_ENV_LOCKS):
        expected_lines.insert(env_insert + offset, f"Environment={lock}")
    expected_text = "\n".join(expected_lines) + "\n"
    service.write_text(expected_text, encoding="utf-8")
    if service.read_text(encoding="utf-8") != expected_text:
        raise base.GateError("service overlay write did not preserve exact expected bytes")
    if base.sha256(service) == raw_hash:
        raise base.GateError("service overlay did not change candidate service identity")
    return raw_hash


def _install_overlay(base, controller_revision: str) -> None:
    original_render = base.render
    original_prepare = base.prepare
    state: dict[str, str] = {}

    def render_with_scoped_git_trust():
        _require_controller_revision(base, controller_revision)
        _verify_runtime_immutability(base)
        out, service, manifest = original_render()
        state["target_rendered_service_sha256"] = _scope_preflight_git_trust(base, service)
        state["candidate_service_sha256"] = base.sha256(service)
        return out, service, manifest

    def prepare_with_overlay_evidence():
        _require_controller_revision(base, controller_revision)
        prepared = original_prepare()
        _require_controller_revision(base, controller_revision)
        raw_hash = state.get("target_rendered_service_sha256")
        candidate_hash = state.get("candidate_service_sha256")
        if not raw_hash or not candidate_hash:
            raise base.GateError("missing service identity before overlay evidence")
        if prepared.get("controller_revision", "").lower() != controller_revision:
            raise base.GateError("base deploy capsule reported a different controller revision")
        if prepared.get("service_sha256") != candidate_hash:
            raise base.GateError("base deploy capsule service hash does not match overlay candidate")
        return {
            **prepared,
            "target_rendered_service_sha256": raw_hash,
            "candidate_service_sha256": candidate_hash,
            "service_overlay": OVERLAY_ID,
            "service_overlay_delta": "EXECSTARTPRE_PLUS_RUNTIME_ENV_LOCKS",
            "git_safe_directory": str(base.RELEASE),
            "git_trust_scope": "ExecStartPre only",
            "git_environment_sanitized": True,
            "runtime_environment_locks": list(RUNTIME_ENV_LOCKS),
            "runtime_immutability": "ROOT_OWNED_NON_WRITABLE",
            "controller_revision_pinned": controller_revision,
        }

    base.render = render_with_scoped_git_trust
    base.prepare = prepare_with_overlay_evidence


def main() -> int:
    controller_revision = _controller_revision_from_env()
    base = _load_committed_base(controller_revision)
    _install_overlay(base, controller_revision)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
