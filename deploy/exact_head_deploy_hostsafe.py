from __future__ import annotations

import re
import subprocess
import sys
import types
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
BASE_OBJECT = "HEAD:deploy/exact_head_deploy.py"
OVERLAY_ID = "EXECSTARTPRE_SCOPED_GIT_SAFE_DIRECTORY_V1"


def _load_committed_base():
    completed = subprocess.run(
        ["git", "-C", str(CONTROL), "show", BASE_OBJECT],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed deploy capsule: {detail}")
    module = types.ModuleType("exact_head_deploy_committed_base")
    module.__file__ = f"git:{CONTROL}:{BASE_OBJECT}"
    sys.modules[module.__name__] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _scope_preflight_git_trust(base, service: Path) -> str:
    release = str(base.RELEASE)
    if not Path(release).is_absolute() or not re.fullmatch(r"/[A-Za-z0-9._/-]+", release):
        raise base.GateError(f"unsafe release path for scoped Git trust: {release}")
    env_bin = Path("/usr/bin/env")
    if not env_bin.is_file() or env_bin.is_symlink():
        raise base.GateError("trusted /usr/bin/env is unavailable")

    raw_hash = base.sha256(service)
    lines = service.read_text(encoding="utf-8").splitlines()
    matches = [index for index, line in enumerate(lines) if line.startswith("ExecStartPre=")]
    if len(matches) != 1:
        raise base.GateError(f"expected exactly one ExecStartPre, got {len(matches)}")

    index = matches[0]
    command = lines[index].split("=", 1)[1].strip()
    if not command:
        raise base.GateError("rendered ExecStartPre is empty")
    if "GIT_CONFIG_" in command or "safe.directory" in command:
        raise base.GateError("rendered ExecStartPre already carries Git trust configuration")

    scoped = (
        "/usr/bin/env "
        "GIT_CONFIG_COUNT=1 "
        "GIT_CONFIG_KEY_0=safe.directory "
        f"GIT_CONFIG_VALUE_0={release} "
        f"{command}"
    )
    lines[index] = "ExecStartPre=" + scoped
    service.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return raw_hash


def _install_overlay(base) -> None:
    original_render = base.render
    original_prepare = base.prepare
    state: dict[str, str] = {}

    def render_with_scoped_git_trust():
        out, service, manifest = original_render()
        state["target_rendered_service_sha256"] = _scope_preflight_git_trust(base, service)
        return out, service, manifest

    def prepare_with_overlay_evidence():
        prepared = original_prepare()
        raw_hash = state.get("target_rendered_service_sha256")
        if not raw_hash:
            raise base.GateError("missing target-rendered service identity before overlay")
        return {
            **prepared,
            "target_rendered_service_sha256": raw_hash,
            "service_overlay": OVERLAY_ID,
            "git_safe_directory": str(base.RELEASE),
            "git_trust_scope": "ExecStartPre only",
        }

    base.render = render_with_scoped_git_trust
    base.prepare = prepare_with_overlay_evidence


def main() -> int:
    base = _load_committed_base()
    _install_overlay(base)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
