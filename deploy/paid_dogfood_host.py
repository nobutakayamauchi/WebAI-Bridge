from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import subprocess
from pathlib import Path

from free_dogfood_host import (
    cloudflared_hint,
    ensure_private_state_dir,
    ensure_venv,
    exact_clean_revision,
    port_is_available,
    validate_port,
)


def ensure_private_child_dir(path: Path, *, parent: Path) -> Path:
    parent = parent.resolve()
    if not path.is_absolute():
        raise ValueError("private child directory must be absolute")
    if path.is_symlink():
        raise ValueError("private child directory must not be a symlink")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise ValueError("private child directory must stay inside paid dogfood state directory") from exc
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ValueError("private child directory must be a regular directory")
    os.chmod(resolved, 0o700)
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError("private child directory must be owner-only")
    return resolved


def ensure_private_secret(path: Path, *, parent: Path) -> str:
    parent = parent.resolve()
    if not path.is_absolute():
        raise ValueError("private secret path must be absolute")
    if path.is_symlink():
        raise ValueError("private secret must not be a symlink")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise ValueError("private secret must stay inside paid dogfood state directory") from exc
    if not resolved.exists():
        value = secrets.token_urlsafe(48)
        fd = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, (value + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError("private secret must be a regular file")
    os.chmod(resolved, 0o600)
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError("private secret must be owner-only")
    value = resolved.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise ValueError("private secret is unexpectedly short")
    return value


def build_paid_env(
    *,
    base: dict[str, str],
    runtime_dir: Path,
    state_dir: Path,
    config_dir: Path,
    revision: str,
    cookie_secret: str | None = None,
) -> dict[str, str]:
    if len(revision) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in revision):
        raise ValueError("revision must be an exact 40-character Git commit SHA")
    env = dict(base)
    env.update({
        "PYTHONUNBUFFERED": "1",
        "WEB_AI_SERVICE_UNIT": "manual-paid-dogfood",
        "WEB_AI_WORKING_DIRECTORY": str(runtime_dir.resolve()),
        "WEB_AI_ROUTE_SURFACE": "commercial:app",
        "WEB_AI_CONFIG_DIR": str(config_dir.resolve()),
        "WEB_AI_ENTITLEMENT_DB": str((state_dir / "entitlements.sqlite3").resolve()),
        "WEB_AI_LEDGER_PATH": str((state_dir / "ledger.sqlite3").resolve()),
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "0",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "DEPLOYED_REVISION": revision.lower(),
    })
    if cookie_secret:
        env["WEB_AI_ENTITLEMENT_COOKIE_SECRET"] = cookie_secret
    stripe_key = (env.get("WEB_AI_STRIPE_SECRET_KEY") or "").strip()
    if stripe_key and not stripe_key.startswith(("sk_", "rk_")):
        raise ValueError("WEB_AI_STRIPE_SECRET_KEY must be a Stripe server or restricted key")
    return env


def prepare_package(
    *,
    python: Path,
    runtime_dir: Path,
    config_dir: Path,
    payment_link_url: str,
    price_jpy: int,
) -> dict:
    completed = subprocess.run(
        [
            str(python),
            str(runtime_dir / "paid_dogfood_prepare.py"),
            "--config-dir",
            str(config_dir),
            "--payment-link-url",
            payment_link_url,
            "--price-jpy",
            str(price_jpy),
        ],
        cwd=runtime_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("paid dogfood package preparer did not return valid JSON") from exc
    if completed.returncode != 0 or result.get("status") != "READY":
        raise RuntimeError(str(result.get("error") or "paid dogfood package preparation failed"))
    return result


def run_json_preflight(*, python: Path, runtime_dir: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [str(python), str(runtime_dir / "deployment_preflight.py"), "--json"],
        cwd=runtime_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("deployment preflight did not return valid JSON") from exc
    if completed.returncode != 0 or not result.get("ok"):
        findings = ", ".join(item.get("code", "UNKNOWN") for item in result.get("findings", []))
        raise RuntimeError(f"paid dogfood deployment preflight failed: {findings or 'UNKNOWN'}")
    if result.get("active_packages") != 1 or result.get("active_paid_packages") != 1:
        raise RuntimeError(
            "paid dogfood deployment requires exactly one active package and exactly one active paid package"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and run the paid WebAI Bridge external dogfood gateway on localhost"
    )
    parser.add_argument("--payment-link-url", required=True, help="Creator-owned Stripe Payment Link bound to the dogfood package")
    parser.add_argument("--price-jpy", type=int, default=100)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / ".local" / "state" / "webai-bridge-paid-dogfood"),
        help="Private state directory outside the repository",
    )
    parser.add_argument("--check-only", action="store_true", help="Prepare paid package and run preflight without starting uvicorn")
    args = parser.parse_args()

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        parser.error("do not run the manual paid dogfood launcher as root; use the normal unprivileged SSH user")

    try:
        port = validate_port(args.port)
        if args.price_jpy <= 0:
            raise ValueError("paid dogfood price must be positive")
        repo_dir = Path(__file__).resolve().parents[1]
        runtime_dir = repo_dir / "runtime"
        requirements = runtime_dir / "requirements.txt"
        revision_before = exact_clean_revision(repo_dir)
        state_dir = ensure_private_state_dir(Path(args.state_dir), runtime_dir=runtime_dir)
        config_dir = ensure_private_child_dir(state_dir / "apps", parent=state_dir)
        cookie_secret = ensure_private_secret(state_dir / "entitlement-cookie.secret", parent=state_dir)
        python, venv_created = ensure_venv(runtime_dir=runtime_dir, requirements=requirements)
        package = prepare_package(
            python=python,
            runtime_dir=runtime_dir,
            config_dir=config_dir,
            payment_link_url=args.payment_link_url,
            price_jpy=args.price_jpy,
        )
        revision_after = exact_clean_revision(repo_dir)
        if revision_after != revision_before:
            raise RuntimeError("paid package preparation changed deployed Git revision unexpectedly")
        env = build_paid_env(
            base=os.environ,
            runtime_dir=runtime_dir,
            state_dir=state_dir,
            config_dir=config_dir,
            revision=revision_after,
            cookie_secret=cookie_secret,
        )
        preflight = run_json_preflight(python=python, runtime_dir=runtime_dir, env=env)
        hint = cloudflared_hint(port)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_in_output": False}, ensure_ascii=False, indent=2))
        return 2

    summary = {
        "status": "PREFLIGHT_PASS",
        "profile": "PAID_BUY_ONCE_BYOK_DOGFOOD",
        "revision": revision_after,
        "runtime_dir": str(runtime_dir.resolve()),
        "config_dir": str(config_dir),
        "state_dir": str(state_dir),
        "package_id": package["package_id"],
        "package_reused": package["reused"],
        "active_packages": preflight["active_packages"],
        "active_paid_packages": preflight["active_paid_packages"],
        "entitlement_issuance_by_launcher": "NONE",
        "entitlement_cookie_secret_persisted": True,
        "stripe_checkout_verification_configured": bool(env.get("WEB_AI_STRIPE_SECRET_KEY")),
        "payment_link_configured": True,
        "port": port,
        "venv_created": venv_created,
        "cloudflared": hint,
        "repo_clean_after_package_prepare": True,
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
