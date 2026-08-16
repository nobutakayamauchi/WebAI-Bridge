from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

import app as core
from entitlements import EntitlementStore

BASE_DIR = Path(__file__).resolve().parent
ENTITLEMENT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))
PAID_PAGE = BASE_DIR / "static" / "paid.html"
entitlements = EntitlementStore(ENTITLEMENT_DB)
SUPPORTED_MANUAL_ACCESS = {"BUY_ONCE", "SUBSCRIPTION"}


def ensure_commercial_hosted_runnable(app_config: dict) -> None:
    """Structural runtime gate used by the commercial wrapper.

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
# commercial wrapper reuse the existing chat/provider/cost path without copying it.
core.ensure_hosted_runnable = ensure_commercial_hosted_runnable

app = FastAPI(title="WebAI Bridge Commercial Gateway", version="0.3.0-manual-entitlement")


@app.get("/apps/{slug}/public-config")
def paid_public_config(slug: str, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token)
    return core.public_config(app_config)


@app.get("/a/{slug}")
def paid_app_page(slug: str):
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") == "FREE":
        return FileResponse(core.STATIC_DIR / "index.html")
    if not PAID_PAGE.exists():
        raise HTTPException(status_code=503, detail="Paid hosted UI is missing")
    return FileResponse(PAID_PAGE)


@app.post("/api/chat")
def paid_chat(
    payload: core.ChatRequest,
    request: Request,
    byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key"),
    buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement"),
) -> dict:
    try:
        app_config = core.registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token)
    return core.chat(payload=payload, request=request, byok_api_key=byok_api_key)


# Everything else (health, opt-in diagnostics, Creator Studio, etc.) stays on the
# already-tested core app. Specific routes above are registered before this mount.
app.mount("/", core.app)
