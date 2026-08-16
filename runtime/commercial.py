from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

import app as core
from commercial_studio import adapt_manual_hosted_entitlement
from entitlements import EntitlementStore

BASE_DIR = Path(__file__).resolve().parent
ENTITLEMENT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))
PAID_PAGE = BASE_DIR / "static" / "paid.html"
entitlements = EntitlementStore(ENTITLEMENT_DB)
SUPPORTED_MANUAL_ACCESS = {"BUY_ONCE", "SUBSCRIPTION"}


def insecure_http_allowed() -> bool:
    return os.getenv("WEB_AI_ALLOW_INSECURE_HTTP", "0").strip().lower() in {"1", "true", "yes", "on"}


def require_secure_transport(request: Request) -> None:
    if insecure_http_allowed():
        return
    if request.url.scheme.lower() != "https":
        raise HTTPException(status_code=426, detail="HTTPS is required for buyer credentials and BYOK")


def paid_page_response() -> FileResponse:
    response = FileResponse(PAID_PAGE)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    return response


def ensure_commercial_hosted_runnable(app_config: dict) -> None:
    """Structural runtime gate used by the commercial gateway.

    Free packages keep the existing behavior. Paid hosted v0 is deliberately narrow:
    buy-once or subscription, explicit entitlement enforcement, and BYOK only.
    """
    status = app_config.get("status")
    if status not in core.RUNNABLE_STATUSES:
        raise HTTPException(status_code=409, detail="AI Package is not activated for runtime use")

    delivery = app_config.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise HTTPException(status_code=503, detail="Portable runtime execution is not implemented")

    access = app_config.get("access") or {}
    mode = access.get("mode")
    if mode == "FREE":
        return
    if mode not in SUPPORTED_MANUAL_ACCESS:
        raise HTTPException(status_code=503, detail="This paid access mode is not supported by manual hosted entitlement v0")
    if access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise HTTPException(status_code=503, detail="Paid hosted entitlement enforcement is not activated")

    billing = app_config.get("billing") or {}
    if billing.get("allowed_payer_modes") != ["BYOK"] or billing.get("default_payer_mode") != "BYOK":
        raise HTTPException(status_code=503, detail="Paid hosted v0 requires BYOK-only inference to avoid unallocated subsidy risk")


def require_entitlement(app_config: dict, token: str | None) -> None:
    ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") == "FREE":
        return
    if not entitlements.authorize(package_id=app_config["slug"], token=(token or "").strip()):
        raise HTTPException(status_code=401, detail="Valid buyer access token is required")


# Core route functions resolve this global at call time. Replacing it lets the
# commercial gateway reuse the existing provider/cost path without duplicating it.
core.ensure_hosted_runnable = ensure_commercial_hosted_runnable

app = FastAPI(title="WebAI Bridge Commercial Gateway", version="0.3.0-manual-entitlement")


@app.get("/health")
def health() -> dict:
    return core.health()


@app.get("/runtime")
def runtime_identity() -> dict:
    return core.runtime_identity()


@app.get("/studio")
def creator_studio_page():
    return core.creator_studio_page()


@app.get("/api/studio/options")
def creator_studio_options() -> dict:
    options = core.creator_studio_options()
    options["manual_paid_hosted_entitlement"] = "BUY_ONCE_OR_SUBSCRIPTION__HOSTED__BYOK_ONLY"
    return options


@app.post("/api/studio/validate")
def creator_studio_validate(payload: core.StudioDraft, request: Request) -> dict:
    result = core.creator_studio_validate(payload=payload, request=request)
    return adapt_manual_hosted_entitlement(result)


@app.get("/apps/{slug}/public-config")
def paid_public_config(
    slug: str,
    request: Request,
    buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement"),
) -> dict:
    core.enforce_rate_limit(request)
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    if (app_config.get("access") or {}).get("mode") != "FREE":
        require_secure_transport(request)
    require_entitlement(app_config, buyer_token)
    return core.public_config(app_config)


@app.get("/a/{slug}")
def paid_app_page(slug: str, request: Request):
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") == "FREE":
        return FileResponse(core.STATIC_DIR / "index.html")
    require_secure_transport(request)
    if not PAID_PAGE.exists():
        raise HTTPException(status_code=503, detail="Paid hosted UI is missing")
    return paid_page_response()


@app.post("/api/chat")
def paid_chat(
    payload: core.ChatRequest,
    request: Request,
    byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key"),
    buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement"),
) -> dict:
    require_secure_transport(request)
    try:
        app_config = core.registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token)
    return core.chat(payload=payload, request=request, byok_api_key=byok_api_key)


# Intentionally no root mount of core.app here.
# Every externally reachable route on the commercial entrypoint is explicit so a
# routing-order/path-normalization mistake cannot silently fall through to a core
# chat route that lacks buyer entitlement context.
