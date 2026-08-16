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


def _absolute(path_value: str, label: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return path


def validate_inputs(*, domain: str, runtime_dir: str, state_dir: str, revision: str, user: str, group: str) -> dict:
    domain = domain.strip().rstrip(".").lower()
    if not DOMAIN_RE.fullmatch(domain):
        raise ValueError("domain must be a valid public hostname")
    runtime = _absolute(runtime_dir, "runtime_dir")
    state = _absolute(state_dir, "state_dir")
    if runtime == Path("/") or state == Path("/"):
        raise ValueError("runtime_dir/state_dir must not be filesystem root")
    try:
        state.relative_to(runtime)
    except ValueError:
        pass
    else:
        raise ValueError("state_dir must live outside runtime_dir")
    if not REVISION_RE.fullmatch(revision.strip()):
        raise ValueError("revision must be an exact 40- or 64-hex Git commit id")
    if not UNIX_NAME_RE.fullmatch(user):
        raise ValueError("user must be a simple Unix service account name")
    if not UNIX_NAME_RE.fullmatch(group):
        raise ValueError("group must be a simple Unix group name")
    return {
        "domain": domain,
        "runtime_dir": str(runtime),
        "state_dir": str(state),
        "revision": revision.lower(),
        "user": user,
        "group": group,
    }


def render_systemd(values: dict) -> str:
    runtime = values["runtime_dir"]
    state = values["state_dir"]
    return f"""[Unit]\nDescription=WebAI Bridge Commercial Gateway\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nUser={values['user']}\nGroup={values['group']}\nUMask=0077\nWorkingDirectory={runtime}\nEnvironment=PYTHONUNBUFFERED=1\nEnvironment=WEB_AI_SERVICE_UNIT=webai-bridge.service\nEnvironment=WEB_AI_WORKING_DIRECTORY={runtime}\nEnvironment=WEB_AI_ROUTE_SURFACE=commercial:app\nEnvironment=WEB_AI_CONFIG_DIR={runtime}/apps\nEnvironment=WEB_AI_ENTITLEMENT_DB={state}/entitlements.sqlite3\nEnvironment=WEB_AI_LEDGER_PATH={state}/ledger.sqlite3\nEnvironment=WEB_AI_DIAGNOSTICS_ENABLED=0\nEnvironment=WEB_AI_STUDIO_ENABLED=0\nEnvironment=WEB_AI_ALLOW_INSECURE_HTTP=0\nEnvironment=DEPLOYED_REVISION={values['revision']}\nEnvironmentFile=-/etc/webai-bridge/webai-bridge.env\nExecStartPre={runtime}/.venv/bin/python {runtime}/deployment_preflight.py\nExecStart={runtime}/.venv/bin/uvicorn commercial:app --host 127.0.0.1 --port 8080 --proxy-headers --forwarded-allow-ips=127.0.0.1\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths={state}\n\n[Install]\nWantedBy=multi-user.target\n"""


def render_caddy(values: dict) -> str:
    return f"""{values['domain']} {{\n    encode zstd gzip\n    reverse_proxy 127.0.0.1:8080\n}}\n"""


def render_manifest(values: dict) -> str:
    manifest = {
        "schema": "webai-deployment-v0",
        "domain": values["domain"],
        "runtime_dir": values["runtime_dir"],
        "state_dir": values["state_dir"],
        "revision": values["revision"],
        "service_unit": "webai-bridge.service",
        "route_surface": "commercial:app",
        "studio_public": False,
        "diagnostics_public": False,
        "insecure_http_allowed": False,
        "secret_values_in_manifest": False,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_outputs(values: dict, output_dir: Path) -> dict:
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output_dir must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise ValueError("output_dir is not a directory")

    files = {
        "webai-bridge.service": render_systemd(values),
        "Caddyfile": render_caddy(values),
        "deployment-manifest.json": render_manifest(values),
    }
    written = {}
    for name, content in files.items():
        destination = output_dir / name
        if destination.is_symlink():
            raise ValueError(f"refusing to replace symlink output: {destination}")
        temporary = output_dir / f".{name}.tmp"
        if temporary.exists():
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
        written = write_outputs(values, Path(args.output_dir))
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps({"rendered": True, "values": values, "files": written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
