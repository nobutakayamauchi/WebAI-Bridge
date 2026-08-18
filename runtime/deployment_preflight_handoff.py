from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from creator_auth import creator_auth_findings
from deployment_preflight import run_preflight
from package_knowledge import PACKAGE_TEXT_BACKEND, validate_package_text_binding

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_SURFACE = "commercial_handoff:app"
CANONICAL_SURFACE = "commercial:app"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _package_text_findings(source: dict[str, str]) -> tuple[set[str], list[dict]]:
    config_dir = Path(source.get("WEB_AI_CONFIG_DIR") or (BASE_DIR / "apps")).resolve()
    local_scopes: set[str] = set()
    findings: list[dict] = []
    if not config_dir.exists() or not config_dir.is_dir():
        return local_scopes, findings
    for path in sorted(config_dir.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        knowledge = data.get("knowledge") or {}
        if data.get("status") != "active" or not knowledge.get("enabled"):
            continue
        if knowledge.get("backend") != PACKAGE_TEXT_BACKEND:
            continue
        scope = f"package:{path.name}"
        local_scopes.add(scope)
        for error in validate_package_text_binding(config_dir=config_dir, app_config=data):
            findings.append({
                "code": "ACTIVE_PACKAGE_TEXT_KNOWLEDGE_INVALID",
                "scope": scope,
                "message": error,
            })
    return local_scopes, findings


def _commercial_env_file_findings(source: dict[str, str], *, active_paid_packages: int) -> list[dict]:
    if active_paid_packages <= 0:
        return []
    raw = (source.get("WEB_AI_ENV_FILE") or "").strip()
    if not raw:
        return [{
            "code": "COMMERCIAL_ENV_FILE_UNSET",
            "scope": "commercial-secrets",
            "message": "Active paid handoff must identify the secret environment file with WEB_AI_ENV_FILE",
        }]

    path = Path(raw)
    findings: list[dict] = []
    if not path.is_absolute():
        findings.append({
            "code": "COMMERCIAL_ENV_FILE_NOT_ABSOLUTE",
            "scope": "commercial-secrets",
            "message": "WEB_AI_ENV_FILE must be an absolute path",
        })
        return findings
    if _inside(path, BASE_DIR):
        findings.append({
            "code": "COMMERCIAL_ENV_FILE_INSIDE_RUNTIME",
            "scope": "commercial-secrets",
            "message": "Commercial secret environment file must live outside the Git/runtime tree",
        })
    if path.is_symlink() or not path.exists() or not path.is_file():
        findings.append({
            "code": "COMMERCIAL_ENV_FILE_UNSAFE",
            "scope": "commercial-secrets",
            "message": "Commercial secret environment file must be an existing regular non-symlink file",
        })
        return findings

    mode = stat.S_IMODE(path.stat().st_mode)
    # 0600 and root:webai-style 0640 are both acceptable. World access and
    # group write are not: this file carries Stripe/cookie authority.
    if mode & 0o007 or mode & 0o020:
        findings.append({
            "code": "COMMERCIAL_ENV_FILE_PERMISSIONS_TOO_OPEN",
            "scope": "commercial-secrets",
            "message": "Commercial secret environment file must not grant world access or group write permission",
        })
    parent = path.parent
    if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o022:
        findings.append({
            "code": "COMMERCIAL_ENV_FILE_PARENT_PERMISSIONS_TOO_OPEN",
            "scope": "commercial-secrets",
            "message": "Parent directory for commercial secret environment file must not be group/world writable",
        })
    return findings


def _live_sale_secret_findings(source: dict[str, str], *, active_paid_packages: int) -> list[dict]:
    """Require the secrets needed by the canonical paid browser/webhook path."""
    if active_paid_packages <= 0:
        return []

    findings: list[dict] = []
    cookie_secret = (source.get("WEB_AI_ENTITLEMENT_COOKIE_SECRET") or "").strip()
    if len(cookie_secret) < 32:
        findings.append({
            "code": "ENTITLEMENT_COOKIE_SECRET_MISSING",
            "scope": "commercial-secrets",
            "message": "Active paid handoff requires WEB_AI_ENTITLEMENT_COOKIE_SECRET with at least 32 characters",
        })

    stripe_key = (source.get("WEB_AI_STRIPE_SECRET_KEY") or "").strip()
    if not stripe_key.startswith(("sk_", "rk_")) or len(stripe_key) < 10:
        findings.append({
            "code": "STRIPE_SECRET_KEY_MISSING_OR_INVALID",
            "scope": "commercial-secrets",
            "message": "Active paid handoff requires a Stripe server/restricted key in WEB_AI_STRIPE_SECRET_KEY",
        })

    webhook_secret = (source.get("WEB_AI_STRIPE_WEBHOOK_SECRET") or "").strip()
    if not webhook_secret.startswith("whsec_") or len(webhook_secret) < 12:
        findings.append({
            "code": "STRIPE_WEBHOOK_SECRET_MISSING_OR_INVALID",
            "scope": "commercial-secrets",
            "message": "Active paid handoff requires a Stripe webhook signing secret in WEB_AI_STRIPE_WEBHOOK_SECRET",
        })
    return findings


def run_handoff_preflight(*, env: dict[str, str] | None = None) -> dict:
    source = dict(os.environ if env is None else env)
    findings: list[dict] = []

    actual_surface = (source.get("WEB_AI_ROUTE_SURFACE") or "").strip()
    if actual_surface != EXPECTED_SURFACE:
        findings.append({
            "code": "HANDOFF_ROUTE_SURFACE_INVALID",
            "scope": "deployment",
            "message": f"WEB_AI_ROUTE_SURFACE must be {EXPECTED_SURFACE} for browser-handoff/Creator Studio runtime",
        })

    if not (BASE_DIR / "commercial_handoff.py").is_file():
        findings.append({
            "code": "HANDOFF_ENTRYPOINT_MISSING",
            "scope": "deployment",
            "message": "commercial_handoff.py is missing from the runtime directory",
        })

    creator_findings = creator_auth_findings(env=source, runtime_dir=BASE_DIR)
    studio_enabled = _truthy(source.get("WEB_AI_STUDIO_ENABLED"))
    creator_auth_protected = studio_enabled and not creator_findings

    canonical_env = dict(source)
    canonical_env["WEB_AI_ROUTE_SURFACE"] = CANONICAL_SURFACE
    result = run_preflight(env=canonical_env)

    local_scopes, knowledge_findings = _package_text_findings(source)
    base_findings = []
    for item in result.get("findings") or []:
        if (
            item.get("code") == "ACTIVE_KNOWLEDGE_BINDING_MISSING"
            and item.get("scope") in local_scopes
        ):
            continue
        if item.get("code") == "PUBLIC_STUDIO_ENABLED" and creator_auth_protected:
            continue
        base_findings.append(item)

    active_paid_packages = int(result.get("active_paid_packages") or 0)
    env_file_findings = _commercial_env_file_findings(source, active_paid_packages=active_paid_packages)
    live_sale_findings = _live_sale_secret_findings(source, active_paid_packages=active_paid_packages)
    combined = (
        base_findings
        + findings
        + knowledge_findings
        + creator_findings
        + env_file_findings
        + live_sale_findings
    )
    result["findings"] = combined
    result["ok"] = not combined
    result["status"] = "PASS" if not combined else "FAIL"
    result["validated_route_surface"] = actual_surface
    result["canonical_paid_preflight_surface"] = CANONICAL_SURFACE
    result["package_text_knowledge_packages"] = len(local_scopes)
    result["creator_studio_enabled"] = studio_enabled
    result["creator_auth_protected"] = creator_auth_protected and not combined
    result["commercial_env_file_safe"] = not env_file_findings
    result["live_sale_secrets_configured"] = not live_sale_findings
    if studio_enabled:
        result["creator_auth_mode"] = "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1" if creator_auth_protected else "INVALID"
    else:
        result["creator_auth_mode"] = "STUDIO_DISABLED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paid browser-handoff / Creator Studio deployment preflight")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_handoff_preflight()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("WebAI Bridge browser-handoff deployment preflight: " + ("PASS" if result.get("ok") else "FAIL"))
        for item in result.get("findings") or []:
            print(f"FAIL {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
        for item in result.get("warnings") or []:
            print(f"WARN {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
