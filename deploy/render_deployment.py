from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)
REVISION_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
UNIX_NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SAFE_ABSOLUTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
COMMERCIAL_ENV_FILE = "/etc/webai-bridge/webai-bridge.env"
TRUSTED_EXEC_PATH = "/usr/bin:/bin"

# EnvironmentFile= has higher precedence than Environment= in systemd.  These
# names therefore cannot be protected by placing Environment= assignments after
# EnvironmentFile=.  They are removed at systemd's final environment assembly
# step with UnsetEnvironment= and then canonical values are injected by the
# absolute /usr/bin/env command in ExecStartPre=/ExecStart=.
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
)


def _absolute(path_value: str, label: str) -> Path:
    raw = path_value.strip()
    if not SAFE_ABSOLUTE_PATH_RE.fullmatch(raw):
        raise ValueError(f"{label} contains unsupported characters")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"):
        raise ValueError(f"{label} must not be filesystem root")
    return resolved


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def validate_inputs(*, domain: str, runtime_dir: str, state_dir: str, revision: str, user: str, group: str) -> dict:
    domain = domain.strip().rstrip(".").lower()
    if not DOMAIN_RE.fullmatch(domain):
        raise ValueError("domain must be a valid public hostname")
    runtime = _absolute(runtime_dir, "runtime_dir")
    state = _absolute(state_dir, "state_dir")
    if _overlap(runtime, state):
        raise ValueError("runtime_dir and state_dir must not overlap in either direction")
    revision = revision.strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise ValueError("revision must be an exact 40- or 64-hex Git commit id")
    if not UNIX_NAME_RE.fullmatch(user):
        raise ValueError("user must be a simple Unix service account name")
    if not UNIX_NAME_RE.fullmatch(group):
        raise ValueError("group must be a simple Unix group name")
    return {
        "domain": domain,
        "runtime_dir": str(runtime),
        "state_dir": str(state),
        "revision": revision,
        "user": user,
        "group": group,
    }


def _deployment_profile(*, creator_studio: bool) -> dict:
    if creator_studio:
        return {
            "profile": "CREATOR_STUDIO_COMMERCIAL_V1",
            "route_surface": "commercial_handoff:app",
            "entrypoint": "commercial_handoff:app",
            "preflight": "deployment_preflight_handoff.py",
            "studio_enabled": True,
            "creator_auth_enabled": True,
            "package_authority": "STATE_DIR",
        }
    return {
        "profile": "BUYER_ONLY_COMMERCIAL_V1",
        "route_surface": "commercial_bound:app",
        "entrypoint": "commercial_bound:app",
        "preflight": "deployment_preflight_bound.py",
        "studio_enabled": False,
        "creator_auth_enabled": False,
        "package_authority": "RUNTIME_DIR",
    }


def _config_dir(values: dict, *, creator_studio: bool) -> str:
    if creator_studio:
        return f"{values['state_dir']}/apps"
    return f"{values['runtime_dir']}/apps"


def _fixed_runtime_environment(values: dict, *, creator_studio: bool) -> dict[str, str]:
    runtime = values["runtime_dir"]
    state = values["state_dir"]
    profile = _deployment_profile(creator_studio=creator_studio)
    fixed = {
        "WEB_AI_ENV_FILE": COMMERCIAL_ENV_FILE,
        "PYTHONUNBUFFERED": "1",
        "WEB_AI_SERVICE_UNIT": "webai-bridge.service",
        "WEB_AI_WORKING_DIRECTORY": runtime,
        "WEB_AI_ROUTE_SURFACE": profile["route_surface"],
        "WEB_AI_CONFIG_DIR": _config_dir(values, creator_studio=creator_studio),
        "WEB_AI_ENTITLEMENT_DB": f"{state}/entitlements.sqlite3",
        "WEB_AI_LEDGER_PATH": f"{state}/ledger.sqlite3",
        "WEB_AI_HANDOFF_DB": f"{state}/handoff.sqlite3",
        "WEB_AI_CHECKOUT_STATE_DB": f"{state}/checkout-state.sqlite3",
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "1" if profile["studio_enabled"] else "0",
        "WEB_AI_CREATOR_AUTH_ENABLED": "1" if profile["creator_auth_enabled"] else "0",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "DEPLOYED_REVISION": values["revision"],
    }
    if creator_studio:
        fixed.update(
            {
                "WEB_AI_CREATOR_PASSWORD_FILE": f"{state}/creator-password.secret",
                "WEB_AI_CREATOR_SESSION_SECRET_FILE": f"{state}/creator-session.secret",
                "WEB_AI_CREATOR_SESSION_TTL_SECONDS": "43200",
            }
        )
    return fixed


def _exec_environment_prefix(fixed: dict[str, str]) -> str:
    assignments = [
        f"PATH={TRUSTED_EXEC_PATH}",
        "PYTHONNOUSERSITE=1",
        *(f"{key}={value}" for key, value in fixed.items()),
    ]
    return "/usr/bin/env " + " ".join(assignments)


def render_systemd(values: dict, *, creator_studio: bool = False) -> str:
    runtime = values["runtime_dir"]
    state = values["state_dir"]
    profile = _deployment_profile(creator_studio=creator_studio)
    fixed = _fixed_runtime_environment(values, creator_studio=creator_studio)
    fixed_lines = "".join(f"Environment={key}={value}\n" for key, value in fixed.items())
    protected_names = (*EXECUTION_HAZARD_ENV_KEYS, *fixed.keys())
    unset_line = "UnsetEnvironment=" + " ".join(dict.fromkeys(protected_names))
    exec_env = _exec_environment_prefix(fixed)

    return f"""[Unit]\nDescription=WebAI Bridge Commercial Gateway\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nUser={values['user']}\nGroup={values['group']}\nUMask=0077\nWorkingDirectory={runtime}\n# Operator-supplied Stripe/provider secrets are loaded from this file.\nEnvironmentFile=-{COMMERCIAL_ENV_FILE}\n# EnvironmentFile= overrides Environment= in systemd.  Keep the canonical\n# assignments visible for inspection, but remove every protected name at the\n# final systemd environment-assembly step and rebind it in /usr/bin/env below.\n{fixed_lines}{unset_line}\nExecStartPre={exec_env} {runtime}/.venv/bin/python {runtime}/{profile['preflight']}\n# Browser authority is never transported in a query string. Stripe completion\n# still carries a non-authoritative Checkout Session locator in its success URL,\n# and production does not need raw request-target retention. Keep Uvicorn access\n# logging disabled until a structured redacted request log exists.\nExecStart={exec_env} {runtime}/.venv/bin/uvicorn {profile['entrypoint']} --host 127.0.0.1 --port 8080 --proxy-headers --forwarded-allow-ips=127.0.0.1 --no-access-log\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths={state}\n\n[Install]\nWantedBy=multi-user.target\n"""


def render_caddy(values: dict) -> str:
    return f"""{values['domain']} {{\n    encode zstd gzip\n    reverse_proxy 127.0.0.1:8080\n}}\n"""


def render_manifest(values: dict, *, creator_studio: bool = False) -> str:
    profile = _deployment_profile(creator_studio=creator_studio)
    manifest = {
        "schema": "webai-deployment-v1",
        "profile": profile["profile"],
        "domain": values["domain"],
        "runtime_dir": values["runtime_dir"],
        "state_dir": values["state_dir"],
        "config_dir": _config_dir(values, creator_studio=creator_studio),
        "package_authority": profile["package_authority"],
        "commercial_env_file": COMMERCIAL_ENV_FILE,
        "revision": values["revision"],
        "service_unit": "webai-bridge.service",
        "route_surface": profile["route_surface"],
        "creator_studio_enabled": profile["studio_enabled"],
        "creator_auth_required": profile["creator_auth_enabled"],
        "creator_auth_mode": "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1" if creator_studio else "DISABLED",
        "diagnostics_public": False,
        "insecure_http_allowed": False,
        "checkout_browser_binding": "STRIPE_CLIENT_REFERENCE_PLUS_HTTPONLY_COOKIE_V1",
        "uvicorn_access_log_enabled": False,
        "query_authority_retention": False,
        "environment_authority": "SYSTEMD_UNSET_THEN_EXEC_REBIND_V1",
        "state_databases": {
            "entitlements": f"{values['state_dir']}/entitlements.sqlite3",
            "ledger": f"{values['state_dir']}/ledger.sqlite3",
            "handoff": f"{values['state_dir']}/handoff.sqlite3",
            "checkout_state": f"{values['state_dir']}/checkout-state.sqlite3",
        },
        "secret_values_in_manifest": False,
    }
    if creator_studio:
        manifest["creator_auth_files"] = {
            "password": f"{values['state_dir']}/creator-password.secret",
            "session_secret": f"{values['state_dir']}/creator-session.secret",
        }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_outputs(values: dict, output_dir: Path, *, creator_studio: bool = False) -> dict:
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output_dir must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise ValueError("output_dir is not a directory")
    if output_dir.stat().st_mode & 0o002:
        raise ValueError("output_dir must not be world-writable")

    files = {
        "webai-bridge.service": render_systemd(values, creator_studio=creator_studio),
        "Caddyfile": render_caddy(values),
        "deployment-manifest.json": render_manifest(values, creator_studio=creator_studio),
    }
    destinations = {name: output_dir / name for name in files}
    for destination in destinations.values():
        if destination.is_symlink():
            raise ValueError(f"refusing to replace symlink output: {destination}")

    written = {}
    for name, content in files.items():
        destination = destinations[name]
        temporary = output_dir / f".{name}.tmp"
        if temporary.exists():
            if temporary.is_symlink() or not temporary.is_file():
                raise ValueError(f"unsafe stale temporary output: {temporary}")
            temporary.unlink()
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        written[name] = str(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Render deterministic WebAI Bridge deployment files")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--runtime-dir", default="/opt/webai-bridge/runtime")
    parser.add_argument("--state-dir", default="/var/lib/webai-bridge")
    parser.add_argument("--revision", required=True, help="Exact deployed Git commit SHA")
    parser.add_argument("--user", default="webai")
    parser.add_argument("--group", default="webai")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--creator-studio",
        action="store_true",
        help="Expose the creator-authenticated Knowledge Studio/direct-publish surface on the production host",
    )
    args = parser.parse_args()

    try:
        values = validate_inputs(
            domain=args.domain,
            runtime_dir=args.runtime_dir,
            state_dir=args.state_dir,
            revision=args.revision,
            user=args.user,
            group=args.group,
        )
        written = write_outputs(values, Path(args.output_dir), creator_studio=args.creator_studio)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps({
        "rendered": True,
        "values": values,
        "profile": _deployment_profile(creator_studio=args.creator_studio)["profile"],
        "files": written,
        "secrets_in_output": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
