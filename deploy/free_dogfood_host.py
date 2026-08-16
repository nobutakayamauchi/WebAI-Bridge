from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

REVISION_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


def requirements_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_port(value: int) -> int:
    if value < 1024 or value > 65535:
        raise ValueError("dogfood port must be between 1024 and 65535")
    return value


def ensure_private_state_dir(path: Path, *, runtime_dir: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("state directory must be absolute")
    if path.is_symlink():
        raise ValueError("state directory must not be a symlink")
    resolved = path.resolve(strict=False)
    runtime = runtime_dir.resolve()
    if resolved == runtime or runtime in resolved.parents or resolved in runtime.parents:
        raise ValueError("state directory and runtime directory must not overlap")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ValueError("state directory must be a regular directory")
    os.chmod(resolved, 0o700)
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & 0o077:
        raise ValueError("state directory must be owner-only")
    return resolved


def build_locked_env(*, base: dict[str, str], runtime_dir: Path, state_dir: Path, revision: str) -> dict[str, str]:
    if not REVISION_RE.fullmatch(revision):
        raise ValueError("revision must be an exact Git commit SHA")
    env = dict(base)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "WEB_AI_SERVICE_UNIT": "manual-free-dogfood",
        "WEB_AI_WORKING_DIRECTORY": str(runtime_dir.resolve()),
        "WEB_AI_ROUTE_SURFACE": "commercial:app",
        "WEB_AI_CONFIG_DIR": str((runtime_dir / "apps").resolve()),
        "WEB_AI_ENTITLEMENT_DB": str((state_dir / "entitlements.sqlite3").resolve()),
        "WEB_AI_LEDGER_PATH": str((state_dir / "ledger.sqlite3").resolve()),
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "0",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "DEPLOYED_REVISION": revision.lower(),
    })
    return env


def exact_clean_revision(repo_dir: Path) -> str:
    if not (repo_dir / ".git").exists():
        raise RuntimeError("dogfood launcher requires a Git checkout so deployed revision can be verified")
    for args, label in [
        (["git", "-C", str(repo_dir), "diff", "--quiet"], "tracked working tree"),
        (["git", "-C", str(repo_dir), "diff", "--cached", "--quiet"], "staged index"),
    ]:
        result = subprocess.run(args, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"{label} is dirty; commit/revert changes before external dogfood")
    completed = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = completed.stdout.strip()
    if not REVISION_RE.fullmatch(revision):
        raise RuntimeError("Git HEAD is not an exact supported commit id")
    return revision.lower()


def port_is_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def ensure_venv(*, runtime_dir: Path, requirements: Path) -> tuple[Path, bool]:
    venv = runtime_dir / ".venv"
    python = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    created = False
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        created = True
    if not python.is_file() or not pip.is_file():
        raise RuntimeError("runtime virtual environment is incomplete")

    digest = requirements_digest(requirements)
    stamp = venv / ".webai-requirements.sha256"
    installed_digest = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    if installed_digest != digest:
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(pip), "install", "-r", str(requirements)], check=True)
        stamp.write_text(digest + "\n", encoding="utf-8")
        os.chmod(stamp, 0o600)
    return python, created


def run_preflight(*, python: Path, runtime_dir: Path, env: dict[str, str]) -> None:
    subprocess.run(
        [str(python), str(runtime_dir / "deployment_preflight.py")],
        cwd=runtime_dir,
        env=env,
        check=True,
    )


def cloudflared_hint(port: int) -> dict:
    binary = shutil.which("cloudflared")
    return {
        "installed": bool(binary),
        "binary": binary or "",
        "next_command": f"cloudflared tunnel --url http://127.0.0.1:{port}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and run the FREE WebAI Bridge external dogfood gateway on localhost"
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".local" / "state" / "webai-bridge-dogfood"),
        help="Private state directory outside the repository",
    )
    parser.add_argument("--check-only", action="store_true", help="Prepare dependencies and run preflight without starting uvicorn")
    args = parser.parse_args()

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        parser.error("do not run the manual dogfood launcher as root; use the normal unprivileged SSH user")

    try:
        port = validate_port(args.port)
        repo_dir = Path(__file__).resolve().parents[1]
        runtime_dir = repo_dir / "runtime"
        requirements = runtime_dir / "requirements.txt"
        revision = exact_clean_revision(repo_dir)
        state_dir = ensure_private_state_dir(Path(args.state_dir), runtime_dir=runtime_dir)
        python, venv_created = ensure_venv(runtime_dir=runtime_dir, requirements=requirements)
        env = build_locked_env(
            base=os.environ,
            runtime_dir=runtime_dir,
            state_dir=state_dir,
            revision=revision,
        )
        run_preflight(python=python, runtime_dir=runtime_dir, env=env)
        hint = cloudflared_hint(port)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    summary = {
        "status": "PREFLIGHT_PASS",
        "profile": "FREE_BYOK_DOGFOOD",
        "revision": revision,
        "runtime_dir": str(runtime_dir.resolve()),
        "state_dir": str(state_dir),
        "port": port,
        "venv_created": venv_created,
        "cloudflared": hint,
        "secrets_in_output": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.check_only:
        return 0
    if not port_is_available(port):
        print(json.dumps({
            "status": "FAIL",
            "error": f"127.0.0.1:{port} is already in use; choose another --port",
        }, ensure_ascii=False, indent=2))
        return 2

    print(
        f"\nIn a SECOND SSH terminal, run:\n  {hint['next_command']}\n"
        "Keep this terminal open while uvicorn runs. Stop with Ctrl-C.\n",
        flush=True,
    )
    command = [
        str(python),
        "-m",
        "uvicorn",
        "commercial:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--proxy-headers",
        "--forwarded-allow-ips=127.0.0.1",
    ]
    completed = subprocess.run(command, cwd=runtime_dir, env=env, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
