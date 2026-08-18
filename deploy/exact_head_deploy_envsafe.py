from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

CONTROL = Path("/opt/webai-bridge-control")
BASE_PATH = "deploy/exact_head_deploy.py"
HOSTSAFE_PATH = "deploy/exact_head_deploy_hostsafe.py"
READY_PATH = "deploy/exact_head_deploy_hostsafe_ready.py"
CONTROLLER_REVISION_ENV = "WEB_AI_CONTROLLER_REVISION"
BOOTSTRAP_CLEAN_ENV = "WEB_AI_BOOTSTRAP_CLEAN"
DEPLOY_CONTROL_STATE = Path("/var/lib/webai-bridge-deploy-control")

TARGET_SHA = "5fd4c791e636464f1a3b5195a3e1048b505d6de5"
TARGET_TREE = "155dc692264a8f7edcd74b0eaff8cba28b0f11ef"
ENV_AUTHORITY_ID = "SYSTEMD_FINAL_UNSET_EXEC_REBIND_GIT_SCOPED_V3"
PROCESS_ENV_AUTHORITY = "CLEAN_BOOTSTRAP_ALLOWLIST_V1"
PREPARE_TRUST_AUTHORITY = "ROOT_OWNED_BEFORE_DEPENDENCY_EXECUTION_V1"
EVIDENCE_AUTHORITY = "SEPARATE_ROOT_ONLY_DEPLOY_CONTROL_STATE_V1"
PREFLIGHT_TIMEOUT_SECONDS = 30
STRIPE_ACCEPTANCE_TIMEOUT_SECONDS = 60
STRIPE_HTTP_TIMEOUT_SECONDS = 5

EXECUTION_HAZARD_ENV_KEYS = (
    "LD_PRELOAD",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONUSERBASE",
    "PYTHONNOUSERSITE",
    "PATH",
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
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_0",
    "GIT_CONFIG_VALUE_0",
    "GIT_NO_REPLACE_OBJECTS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "SSLKEYLOGFILE",
    "OPENSSL_CONF",
    "OPENSSL_MODULES",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_LOG",
    "WEB_CONCURRENCY",
    "FORWARDED_ALLOW_IPS",
    "UVICORN_RELOAD",
    "UVICORN_WORKERS",
    "UVICORN_ENV_FILE",
    "UVICORN_APP_DIR",
    "UVICORN_FACTORY",
    "UVICORN_PROXY_HEADERS",
    "UVICORN_FORWARDED_ALLOW_IPS",
    "UVICORN_ACCESS_LOG",
    "UVICORN_SSL_KEYFILE",
    "UVICORN_SSL_CERTFILE",
    "UVICORN_SSL_CA_CERTS",
    "UVICORN_ROOT_PATH",
)

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

EXPECTED_RUNTIME_POLICY = {
    "requests_per_minute": 20,
    "byok_session_ttl_seconds": 900,
    "byok_session_max": 1000,
    "handoff_ttl_seconds": 600,
    "entitlement_cookie_max_age_seconds": 31536000,
}
EXPECTED_SERVER_AUTHORITY = "PROGRAMMATIC_SINGLE_WORKER_V1"


def _validate_bootstrap_environment(environ: dict[str, str]) -> str:
    revision = (environ.get(CONTROLLER_REVISION_ENV) or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError(
            f"{CONTROLLER_REVISION_ENV} must pin the exact 40-hex controller revision"
        )
    if environ.get(BOOTSTRAP_CLEAN_ENV) != "1":
        raise RuntimeError(
            f"{BOOTSTRAP_CLEAN_ENV}=1 is required from the clean bootstrap invocation"
        )
    unexpected = sorted(set(environ) - BOOTSTRAP_ALLOWED_ENV_KEYS)
    if unexpected:
        raise RuntimeError(
            "controller bootstrap environment is not clean; unexpected keys: "
            + ", ".join(unexpected)
        )
    if environ.get("PATH") not in (None, "/usr/bin:/bin"):
        raise RuntimeError("controller bootstrap PATH must be exactly /usr/bin:/bin")
    return revision


def _install_clean_process_environment(revision: str) -> None:
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


def _subprocess_env() -> dict[str, str]:
    return dict(os.environ)


def _run_git(*args: str) -> str:
    git_bin = Path("/usr/bin/git")
    if not git_bin.is_file() or git_bin.is_symlink():
        raise RuntimeError("trusted /usr/bin/git is unavailable")
    completed = subprocess.run(
        [str(git_bin), "-C", str(CONTROL), *args],
        check=False,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"controller git command failed: {detail}")
    return completed.stdout.strip()


def _controller_revision_from_env() -> str:
    revision = _validate_bootstrap_environment(dict(os.environ))
    _install_clean_process_environment(revision)
    actual = _run_git("rev-parse", "HEAD").lower()
    if actual != revision:
        raise RuntimeError(
            f"controller HEAD changed before env-safe wrapper start: expected {revision}, got {actual}"
        )
    return revision


def _load_committed(controller_revision: str, path: str, module_name: str):
    obj = f"{controller_revision}:{path}"
    completed = subprocess.run(
        ["/usr/bin/git", "-C", str(CONTROL), "show", obj],
        check=False,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or str(completed.returncode)).strip()
        raise RuntimeError(f"cannot load committed controller object {path}: {detail}")
    module = types.ModuleType(module_name)
    module.__file__ = f"git:{CONTROL}:{obj}"
    sys.modules[module_name] = module
    exec(compile(completed.stdout, module.__file__, "exec"), module.__dict__)
    return module


def _pin_target(base) -> None:
    base.TARGET_SHA = TARGET_SHA
    base.TARGET_TREE = TARGET_TREE
    base.RELEASE = Path("/opt/webai-bridge-releases") / TARGET_SHA
    base.VENV = Path("/opt/webai-bridge-venvs") / TARGET_SHA


def _fixed_runtime_environment(base) -> dict[str, str]:
    runtime = str(base.RELEASE / "runtime")
    state = str(base.STATE)
    return {
        "WEB_AI_ENV_FILE": str(base.ENV_FILE),
        "PYTHONUNBUFFERED": "1",
        "WEB_AI_SERVICE_UNIT": "webai-bridge.service",
        "WEB_AI_WORKING_DIRECTORY": runtime,
        "WEB_AI_ROUTE_SURFACE": "commercial_handoff:app",
        "WEB_AI_CONFIG_DIR": f"{state}/apps",
        "WEB_AI_PRICING_FILE": f"{runtime}/pricing.json",
        "WEB_AI_ENTITLEMENT_DB": f"{state}/entitlements.sqlite3",
        "WEB_AI_LEDGER_PATH": f"{state}/ledger.sqlite3",
        "WEB_AI_HANDOFF_DB": f"{state}/handoff.sqlite3",
        "WEB_AI_CHECKOUT_STATE_DB": f"{state}/checkout-state.sqlite3",
        "WEB_AI_REQUESTS_PER_MINUTE": "20",
        "WEB_AI_BYOK_SESSION_TTL_SECONDS": "900",
        "WEB_AI_BYOK_SESSION_MAX": "1000",
        "WEB_AI_HANDOFF_TTL_SECONDS": "600",
        "WEB_AI_ENTITLEMENT_COOKIE_MAX_AGE_SECONDS": "31536000",
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "1",
        "WEB_AI_CREATOR_AUTH_ENABLED": "1",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "DEPLOYED_REVISION": base.TARGET_SHA,
        "WEB_AI_CREATOR_PASSWORD_FILE": f"{state}/creator-password.secret",
        "WEB_AI_CREATOR_SESSION_SECRET_FILE": f"{state}/creator-session.secret",
        "WEB_AI_CREATOR_SESSION_TTL_SECONDS": "43200",
    }


def _protected_environment_names(base) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*EXECUTION_HAZARD_ENV_KEYS, *_fixed_runtime_environment(base).keys())))


def _exec_prefix(base) -> str:
    assignments = [
        "PATH=/usr/bin:/bin",
        "PYTHONNOUSERSITE=1",
        *(f"{key}={value}" for key, value in _fixed_runtime_environment(base).items()),
    ]
    return "/usr/bin/env " + " ".join(assignments)


def _expected_preflight(base) -> str:
    return (
        f"{_exec_prefix(base)} "
        f"{base.RELEASE}/runtime/.venv/bin/python "
        f"{base.RELEASE}/runtime/deployment_preflight_handoff.py"
    )


def _expected_start(base) -> str:
    return (
        f"{_exec_prefix(base)} "
        f"{base.RELEASE}/runtime/.venv/bin/python "
        f"{base.RELEASE}/runtime/production_server.py "
        "commercial_handoff:app --no-access-log"
    )


def _validate_target_environment_authority(base, service: Path, manifest: Path) -> None:
    if service.is_symlink() or not service.is_file():
        raise base.GateError("target-rendered service is not a regular file")
    lines = service.read_text(encoding="utf-8").splitlines()

    env_file = f"EnvironmentFile=-{base.ENV_FILE}"
    if lines.count(env_file) != 1:
        raise base.GateError("target-rendered service lost the canonical EnvironmentFile")

    unset_lines = [line for line in lines if line.startswith("UnsetEnvironment=")]
    expected_unset = "UnsetEnvironment=" + " ".join(_protected_environment_names(base))
    if unset_lines != [expected_unset]:
        raise base.GateError("target-rendered service lost exact final environment sanitization")

    pre_lines = [line for line in lines if line.startswith("ExecStartPre=")]
    start_lines = [line for line in lines if line.startswith("ExecStart=")]
    if pre_lines != ["ExecStartPre=" + _expected_preflight(base)]:
        raise base.GateError("target-rendered ExecStartPre authority mismatch")
    if start_lines != ["ExecStart=" + _expected_start(base)]:
        raise base.GateError("target-rendered ExecStart authority mismatch")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("environment_authority") != "SYSTEMD_UNSET_THEN_EXEC_REBIND_V1":
        raise base.GateError("deployment manifest lost effective environment authority identity")
    if data.get("server_authority") != EXPECTED_SERVER_AUTHORITY:
        raise base.GateError("deployment manifest server authority mismatch")
    if data.get("runtime_policy") != EXPECTED_RUNTIME_POLICY:
        raise base.GateError("deployment manifest runtime policy authority mismatch")


def _scope_preflight_git_trust(base, service: Path) -> str:
    _validate_target_environment_authority(
        base,
        service,
        service.parent / "deployment-manifest.json",
    )
    raw_hash = base.sha256(service)
    lines = service.read_text(encoding="utf-8").splitlines()
    expected = "ExecStartPre=" + _expected_preflight(base)
    index = lines.index(expected)
    scoped_git = " ".join(
        [
            "GIT_CONFIG_SYSTEM=/dev/null",
            "GIT_CONFIG_GLOBAL=/dev/null",
            "GIT_CONFIG_NOSYSTEM=1",
            "GIT_NO_REPLACE_OBJECTS=1",
            "GIT_CONFIG_COUNT=1",
            "GIT_CONFIG_KEY_0=safe.directory",
            f"GIT_CONFIG_VALUE_0={base.RELEASE}",
        ]
    )
    lines[index] = (
        "ExecStartPre="
        + _exec_prefix(base)
        + " "
        + scoped_git
        + f" {base.RELEASE}/runtime/.venv/bin/python"
        + f" {base.RELEASE}/runtime/deployment_preflight_handoff.py"
    )
    expected_text = "\n".join(lines) + "\n"
    service.write_text(expected_text, encoding="utf-8")
    if service.read_text(encoding="utf-8") != expected_text:
        raise base.GateError("scoped Git trust overlay did not preserve exact expected bytes")
    if base.sha256(service) == raw_hash:
        raise base.GateError("scoped Git trust overlay did not change candidate service identity")
    return raw_hash


def _candidate_preflight(base, service: Path) -> None:
    keep: list[str] = []
    pre: str | None = None
    inside = False
    prefixes = (
        "User=",
        "Group=",
        "UMask=",
        "WorkingDirectory=",
        "EnvironmentFile=",
        "Environment=",
        "UnsetEnvironment=",
        "NoNewPrivileges=",
        "PrivateTmp=",
        "ProtectSystem=",
        "ProtectHome=",
        "ReadWritePaths=",
    )
    for line in service.read_text(encoding="utf-8").splitlines():
        if line == "[Service]":
            inside = True
            continue
        if inside and line.startswith("["):
            inside = False
        if not inside:
            continue
        if line.startswith("ExecStartPre="):
            pre = "ExecStart=" + line.split("=", 1)[1]
        elif line.startswith(prefixes):
            keep.append(line)
    if not pre:
        raise base.GateError("rendered service has no preflight")
    unset = [line for line in keep if line.startswith("UnsetEnvironment=")]
    if len(unset) != 1:
        raise base.GateError("candidate preflight lost final environment sanitization")
    body = "\n".join(
        [
            "[Service]",
            "Type=oneshot",
            f"TimeoutStartSec={PREFLIGHT_TIMEOUT_SECONDS}",
            *keep,
            "Environment=PYTHONDONTWRITEBYTECODE=1",
            pre,
            "",
        ]
    )
    base.transient(f"webai-preflight-{base.TARGET_SHA[:12]}.service", body)


def _stripe_acceptance(base) -> None:
    unset_line = "UnsetEnvironment=" + " ".join(_protected_environment_names(base))
    exec_start = " ".join(
        [
            "/usr/bin/env",
            "PATH=/usr/bin:/bin",
            "PYTHONNOUSERSITE=1",
            "PYTHONDONTWRITEBYTECODE=1",
            f"{base.RELEASE}/runtime/.venv/bin/python",
            f"{base.RELEASE}/runtime/stripe_external_acceptance.py",
            "--domain",
            base.DOMAIN,
            "--config-dir",
            f"{base.STATE}/apps",
            "--timeout",
            str(STRIPE_HTTP_TIMEOUT_SECONDS),
        ]
    )
    body = "\n".join(
        [
            "[Service]",
            "Type=oneshot",
            f"TimeoutStartSec={STRIPE_ACCEPTANCE_TIMEOUT_SECONDS}",
            "User=webai",
            "Group=webai",
            "UMask=0077",
            f"WorkingDirectory={base.RELEASE}/runtime",
            f"EnvironmentFile=-{base.ENV_FILE}",
            unset_line,
            "Environment=PYTHONDONTWRITEBYTECODE=1",
            f"ExecStart={exec_start}",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "",
        ]
    )
    base.transient(f"webai-stripe-{base.TARGET_SHA[:12]}.service", body)


def _secure_existing_root_owned_tree(base, host, path: Path, *, label: str, skip: set[str] | None = None, reject_symlinks: bool = False) -> None:
    if path.is_symlink():
        raise base.GateError(f"{label} must not be a symlink: {path}")
    host._check_root_owned_tree(
        base,
        path,
        label=label,
        skip=skip,
        reject_symlinks=reject_symlinks,
    )


def _ensure_secure_root(base, host, path: Path, *, label: str) -> None:
    if os.geteuid() != 0:
        raise base.GateError("env-safe prepare requires root")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise base.GateError(f"{label} must be a regular directory: {path}")
    else:
        path.mkdir(mode=0o755, parents=False)
    host._check_root_owned_path(base, path, label=label)


def _verify_prepare_roots(base, host, controller_revision: str) -> None:
    host._require_controller_revision(base, controller_revision)
    _secure_existing_root_owned_tree(
        base,
        host,
        base.CONTROL,
        label="controller clone before prepare",
    )
    _ensure_secure_root(base, host, base.RELEASE.parent, label="release root before prepare")
    _ensure_secure_root(base, host, base.VENV.parent, label="venv root before prepare")
    if base.RELEASE.exists() or base.RELEASE.is_symlink():
        _secure_existing_root_owned_tree(
            base,
            host,
            base.RELEASE,
            label="existing exact release before dependency execution",
            skip={"runtime/.venv"},
            reject_symlinks=True,
        )
    if base.VENV.exists() or base.VENV.is_symlink():
        _secure_existing_root_owned_tree(
            base,
            host,
            base.VENV,
            label="existing exact venv before dependency execution",
        )


def _secure_deploy_control_state(base) -> Path:
    if os.geteuid() != 0:
        raise base.GateError("deploy evidence requires root")
    path = DEPLOY_CONTROL_STATE
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise base.GateError(f"deploy control state must be a regular directory: {path}")
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise base.GateError("deploy control state must remain root-owned mode 0700")
    else:
        path.mkdir(mode=0o700, parents=False)
    os.chmod(path, 0o700)
    return path


def _write_prepare_evidence(base, payload: dict) -> Path:
    root = _secure_deploy_control_state(base)
    d = root / "deploy-evidence"
    if d.exists() or d.is_symlink():
        info = d.lstat()
        if d.is_symlink() or not stat.S_ISDIR(info.st_mode):
            raise base.GateError("deploy evidence directory is unsafe")
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
            raise base.GateError("deploy evidence directory must remain root-owned mode 0700")
    else:
        d.mkdir(mode=0o700)
    os.chmod(d, 0o700)

    unique = (
        f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-"
        f"{time.time_ns()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    p = d / f"{unique}-{base.TARGET_SHA[:12]}.json"
    t = d / f".{p.name}.tmp"
    with t.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(t, 0o600)
    os.replace(t, p)
    os.chmod(p, 0o400)
    dfd = os.open(d, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return p


def _install_envsafe_overlay(base, host, controller_revision: str) -> None:
    original_render = base.render
    original_prepare = base.prepare
    state: dict[str, str] = {}

    def render_envsafe():
        host._require_controller_revision(base, controller_revision)
        host._verify_runtime_immutability(base)
        out, service, manifest = original_render()
        raw_hash = _scope_preflight_git_trust(base, service)
        state["target_rendered_service_sha256"] = raw_hash
        state["candidate_service_sha256"] = base.sha256(service)
        return out, service, manifest

    def prepare_envsafe():
        host._require_controller_revision(base, controller_revision)
        _verify_prepare_roots(base, host, controller_revision)
        prepared = original_prepare()
        host._require_controller_revision(base, controller_revision)
        raw_hash = state.get("target_rendered_service_sha256")
        candidate_hash = state.get("candidate_service_sha256")
        if not raw_hash or not candidate_hash:
            raise base.GateError("missing effective environment service identity")
        if prepared.get("controller_revision", "").lower() != controller_revision:
            raise base.GateError("base deploy capsule reported a different controller revision")
        if prepared.get("service_sha256") != candidate_hash:
            raise base.GateError("base deploy capsule service hash does not match env-safe candidate")
        return {
            **prepared,
            "target_rendered_service_sha256": raw_hash,
            "candidate_service_sha256": candidate_hash,
            "service_overlay": ENV_AUTHORITY_ID,
            "environment_authority": "SYSTEMD_FINAL_UNSET_THEN_EXEC_REBIND_V1",
            "process_environment_authority": PROCESS_ENV_AUTHORITY,
            "prepare_trust_authority": PREPARE_TRUST_AUTHORITY,
            "evidence_authority": EVIDENCE_AUTHORITY,
            "server_authority": EXPECTED_SERVER_AUTHORITY,
            "runtime_policy": dict(EXPECTED_RUNTIME_POLICY),
            "git_trust_scope": "ExecStartPre only",
            "git_safe_directory": str(base.RELEASE),
            "execution_hazard_unset": list(EXECUTION_HAZARD_ENV_KEYS),
            "preflight_timeout_seconds": PREFLIGHT_TIMEOUT_SECONDS,
            "stripe_acceptance_timeout_seconds": STRIPE_ACCEPTANCE_TIMEOUT_SECONDS,
            "stripe_http_timeout_seconds": STRIPE_HTTP_TIMEOUT_SECONDS,
            "runtime_immutability": "ROOT_OWNED_NON_WRITABLE",
            "controller_revision_pinned": controller_revision,
            "production_apply_enabled": False,
        }

    def apply_blocked(_approval: str):
        raise base.GateError(
            "production apply is intentionally disabled in this canonical prepare controller; "
            "it requires a separate post-prepare Human Gate and hardened apply capsule"
        )

    base.render = render_envsafe
    base.prepare = prepare_envsafe
    base.candidate_preflight = lambda service: _candidate_preflight(base, service)
    base.stripe_acceptance = lambda: _stripe_acceptance(base)
    base.evidence = lambda payload: _write_prepare_evidence(base, payload)
    base.apply = apply_blocked


def main() -> int:
    controller_revision = _controller_revision_from_env()
    base = _load_committed(controller_revision, BASE_PATH, "exact_head_deploy_envsafe_base")
    host = _load_committed(controller_revision, HOSTSAFE_PATH, "exact_head_deploy_envsafe_host")
    ready = _load_committed(controller_revision, READY_PATH, "exact_head_deploy_envsafe_ready")
    _pin_target(base)
    _install_envsafe_overlay(base, host, controller_revision)
    ready._install_readiness_overlay(base)
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
