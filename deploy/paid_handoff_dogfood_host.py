from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from free_dogfood_host import cloudflared_hint, ensure_private_state_dir, ensure_venv, exact_clean_revision, port_is_available, validate_port
from paid_dogfood_host import ensure_private_child_dir, ensure_private_secret, build_paid_env, prepare_package


def run_handoff_json_preflight(*, python: Path, runtime_dir: Path, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [str(python), str(runtime_dir / "deployment_preflight_handoff.py"), "--json"],
        cwd=runtime_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("browser-handoff deployment preflight did not return valid JSON") from exc
    if completed.returncode != 0 or not result.get("ok"):
        findings = ", ".join(item.get("code", "UNKNOWN") for item in result.get("findings", []))
        raise RuntimeError(f"browser-handoff deployment preflight failed: {findings or 'UNKNOWN'}")
    if result.get("validated_route_surface") != "commercial_handoff:app":
        raise RuntimeError("browser-handoff deployment preflight did not validate the actual route surface")
    if result.get("active_packages") != 1 or result.get("active_paid_packages") != 1:
        raise RuntimeError("browser-handoff dogfood requires exactly one active package and one active paid package")
    if env.get("WEB_AI_STUDIO_ENABLED") == "1" and not result.get("creator_auth_protected"):
        raise RuntimeError("Creator Studio was requested but creator-only authentication did not pass preflight")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paid WebAI Bridge dogfood with cross-browser checkout handoff")
    parser.add_argument("--payment-link-url", required=True)
    parser.add_argument("--price-jpy", type=int, default=100)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument(
        "--creator-studio",
        action="store_true",
        help="Expose /studio on the public HTTPS surface behind creator-only authentication",
    )
    parser.add_argument(
        "--creator-session-hours",
        type=int,
        default=12,
        help="Authenticated Creator Studio session lifetime; 1-168 hours",
    )
    args = parser.parse_args()

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        parser.error("do not run as root")

    try:
        port = validate_port(args.port)
        if args.price_jpy <= 0:
            raise ValueError("paid dogfood price must be positive")
        if args.creator_session_hours < 1 or args.creator_session_hours > 168:
            raise ValueError("--creator-session-hours must be between 1 and 168")
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
        env["WEB_AI_ROUTE_SURFACE"] = "commercial_handoff:app"
        env["WEB_AI_HANDOFF_DB"] = str((state_dir / "handoff.sqlite3").resolve())

        creator_password_path: Path | None = None
        creator_session_path: Path | None = None
        if args.creator_studio:
            creator_password_path = state_dir / "creator-password.secret"
            creator_session_path = state_dir / "creator-session.secret"
            # Generated once and then reused. Values are intentionally never
            # printed by the launcher; the operator can read the password file
            # directly in their private SSH session when they need to log in.
            ensure_private_secret(creator_password_path, parent=state_dir)
            ensure_private_secret(creator_session_path, parent=state_dir)
            env.update({
                "WEB_AI_STUDIO_ENABLED": "1",
                "WEB_AI_CREATOR_AUTH_ENABLED": "1",
                "WEB_AI_CREATOR_PASSWORD_FILE": str(creator_password_path.resolve()),
                "WEB_AI_CREATOR_SESSION_SECRET_FILE": str(creator_session_path.resolve()),
                "WEB_AI_CREATOR_SESSION_TTL_SECONDS": str(args.creator_session_hours * 3600),
            })
        else:
            env["WEB_AI_STUDIO_ENABLED"] = "0"
            env["WEB_AI_CREATOR_AUTH_ENABLED"] = "0"

        preflight = run_handoff_json_preflight(python=python, runtime_dir=runtime_dir, env=env)
        hint = cloudflared_hint(port)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_in_output": False}, ensure_ascii=False, indent=2))
        return 2

    summary = {
        "status": "PREFLIGHT_PASS",
        "profile": "PAID_BUY_ONCE_BROWSER_HANDOFF_DOGFOOD",
        "revision": revision_after,
        "state_dir": str(state_dir),
        "package_id": package["package_id"],
        "package_reused": package["reused"],
        "active_packages": preflight["active_packages"],
        "active_paid_packages": preflight["active_paid_packages"],
        "validated_route_surface": preflight["validated_route_surface"],
        "stripe_checkout_verification_configured": bool(env.get("WEB_AI_STRIPE_SECRET_KEY")),
        "handoff_ttl_seconds": 600,
        "creator_studio_enabled": bool(args.creator_studio),
        "creator_auth_protected": bool(preflight.get("creator_auth_protected")),
        "creator_login_path": "/creator/login" if args.creator_studio else None,
        "creator_studio_path": "/studio" if args.creator_studio else None,
        "creator_password_file": str(creator_password_path) if creator_password_path else None,
        "creator_session_ttl_seconds": args.creator_session_hours * 3600 if args.creator_studio else None,
        "port": port,
        "venv_created": venv_created,
        "cloudflared": hint,
        "secrets_in_output": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.creator_studio and creator_password_path:
        print(
            "\nCreator Studio is authentication-gated. "
            f"Read the access key only in your private SSH session: cat {creator_password_path}\n",
            flush=True,
        )

    if not port_is_available(port):
        print(json.dumps({"status": "FAIL", "error": f"127.0.0.1:{port} is already in use"}, ensure_ascii=False, indent=2))
        return 2

    print(f"\nIn a SECOND SSH terminal, run:\n  {hint['next_command']}\nKeep this terminal open while uvicorn runs. Stop with Ctrl-C.\n", flush=True)
    completed = subprocess.run([
        str(python), "-m", "uvicorn", "commercial_handoff:app",
        "--host", "127.0.0.1", "--port", str(port), "--proxy-headers",
        "--forwarded-allow-ips", "127.0.0.1",
    ], cwd=runtime_dir, env=env, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
