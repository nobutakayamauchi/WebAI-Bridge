from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import app as core
from byok_sessions import ByokSessionStore
from commercial_studio import adapt_manual_hosted_entitlement
from entitlements import EntitlementStore

BASE_DIR = Path(__file__).resolve().parent
ENTITLEMENT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))
PAID_PAGE = BASE_DIR / "static" / "paid.html"
entitlements = EntitlementStore(ENTITLEMENT_DB)
SUPPORTED_MANUAL_ACCESS = {"BUY_ONCE", "SUBSCRIPTION"}
BYOK_SESSION_TTL_SECONDS = int(os.getenv("WEB_AI_BYOK_SESSION_TTL_SECONDS", "900"))
BYOK_SESSION_MAX = int(os.getenv("WEB_AI_BYOK_SESSION_MAX", "1000"))
byok_sessions = ByokSessionStore(ttl_seconds=BYOK_SESSION_TTL_SECONDS, max_sessions=BYOK_SESSION_MAX)


class ByokSessionRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    api_key: str = Field(min_length=8, max_length=4096)


def insecure_http_allowed() -> bool:
    return os.getenv("WEB_AI_ALLOW_INSECURE_HTTP", "0").strip().lower() in {"1", "true", "yes", "on"}


def require_secure_transport(request: Request) -> None:
    if insecure_http_allowed():
        return
    if request.url.scheme.lower() != "https":
        raise HTTPException(status_code=426, detail="HTTPS is required for buyer credentials and BYOK")


def byok_cookie_name(slug: str) -> str:
    return f"webai_byok_{slug}"


def set_byok_cookie(response: Response, *, slug: str, token: str) -> None:
    response.set_cookie(
        key=byok_cookie_name(slug),
        value=token,
        max_age=BYOK_SESSION_TTL_SECONDS,
        httponly=True,
        secure=not insecure_http_allowed(),
        samesite="strict",
        path="/",
    )


def clear_byok_cookie(response: Response, *, slug: str) -> None:
    response.delete_cookie(
        key=byok_cookie_name(slug),
        httponly=True,
        secure=not insecure_http_allowed(),
        samesite="strict",
        path="/",
    )


def free_page_response() -> FileResponse:
    response = FileResponse(core.STATIC_DIR / "index.html")
    # The free dogfood page evolves quickly during real-device testing. Do not let
    # mobile Safari reuse an older credential UI after a runtime revision changes.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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


def resolve_byok_package(slug: str, buyer_token: str | None) -> dict:
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token)
    billing = app_config.get("billing") or {}
    if "BYOK" not in (billing.get("allowed_payer_modes") or []):
        raise HTTPException(status_code=403, detail="BYOK is not allowed for this AI Package")
    return app_config


core.ensure_hosted_runnable = ensure_commercial_hosted_runnable
app = FastAPI(title="WebAI Bridge Commercial Gateway", version="0.4.0-ephemeral-byok")


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
    options["byok_credential_transport"] = "EPHEMERAL_PROCESS_MEMORY_HTTPONLY_COOKIE"
    return options


@app.post("/api/studio/validate")
def creator_studio_validate(payload: core.StudioDraft, request: Request) -> dict:
    result = core.creator_studio_validate(payload=payload, request=request)
    return adapt_manual_hosted_entitlement(result)


@app.get("/apps/{slug}/public-config")
def paid_public_config(slug: str, request: Request, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
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
        return free_page_response()
    require_secure_transport(request)
    if not PAID_PAGE.exists():
        raise HTTPException(status_code=503, detail="Paid hosted UI is missing")
    return paid_page_response()


@app.post("/api/byok/session")
def create_byok_session(payload: ByokSessionRequest, request: Request, response: Response, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    require_secure_transport(request)
    core.enforce_rate_limit(request)
    resolve_byok_package(payload.slug, buyer_token)
    try:
        session = byok_sessions.create(package_id=payload.slug, api_key=payload.api_key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    set_byok_cookie(response, slug=payload.slug, token=session.token)
    return {
        "connected": True,
        "expires_in_seconds": BYOK_SESSION_TTL_SECONDS,
        "storage": "PROCESS_MEMORY_ONLY",
        "browser_api_key_retained": False,
    }


@app.get("/api/byok/session/{slug}")
def byok_session_status(slug: str, request: Request, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    require_secure_transport(request)
    resolve_byok_package(slug, buyer_token)
    token = request.cookies.get(byok_cookie_name(slug))
    result = byok_sessions.status(package_id=slug, token=token)
    result["storage"] = "PROCESS_MEMORY_ONLY"
    return result


@app.delete("/api/byok/session/{slug}")
def forget_byok_session(slug: str, request: Request, response: Response, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    require_secure_transport(request)
    resolve_byok_package(slug, buyer_token)
    token = request.cookies.get(byok_cookie_name(slug))
    forgotten = byok_sessions.forget(token)
    clear_byok_cookie(response, slug=slug)
    return {"forgotten": forgotten, "connected": False}


@app.post("/api/chat")
def paid_chat(
    payload: core.ChatRequest,
    request: Request,
    buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement"),
    legacy_byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key"),
) -> dict:
    require_secure_transport(request)
    try:
        app_config = core.registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token)
    payer_mode = core.resolve_payer_mode(payload, app_config)
    byok_api_key = None
    if payer_mode == "BYOK":
        if legacy_byok_api_key:
            if not insecure_http_allowed():
                raise HTTPException(status_code=400, detail="Direct BYOK header transport is disabled; create an ephemeral BYOK session first")
            byok_api_key = legacy_byok_api_key
        else:
            session_token = request.cookies.get(byok_cookie_name(payload.slug))
            byok_api_key = byok_sessions.resolve(package_id=payload.slug, token=session_token)
            if not byok_api_key:
                raise HTTPException(status_code=402, detail="BYOK session is missing or expired; reconnect your provider key")
    return core.chat(payload=payload, request=request, byok_api_key=byok_api_key)


# Intentionally no root mount of core.app here.
