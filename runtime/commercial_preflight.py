from __future__ import annotations

import stat
from pathlib import Path


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def commercial_env_file_findings(
    source: dict[str, str],
    *,
    active_paid_packages: int,
    runtime_dir: Path,
) -> list[dict]:
    if active_paid_packages <= 0:
        return []
    raw = (source.get("WEB_AI_ENV_FILE") or "").strip()
    if not raw:
        return [{
            "code": "COMMERCIAL_ENV_FILE_UNSET",
            "scope": "commercial-secrets",
            "message": "Active paid browser/webhook runtime must identify the secret environment file with WEB_AI_ENV_FILE",
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
    if _inside(path, runtime_dir):
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


def live_sale_secret_findings(source: dict[str, str], *, active_paid_packages: int) -> list[dict]:
    """Require secrets needed by automatic Stripe browser/webhook fulfillment."""
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
