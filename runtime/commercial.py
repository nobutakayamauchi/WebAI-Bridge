from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

import app as core
from byok_sessions import ByokSessionStore
from checkout_state import CheckoutStateStore
from commercial_studio import adapt_manual_hosted_entitlement
from entitlement_cookies import sign_entitlement_cookie, verify_entitlement_cookie
from entitlements import EntitlementStore, PAYMENT_ACTIVE, PAYMENT_EXPIRED, PAYMENT_MISSING, PAYMENT_REVOKED
from handoff_tickets import HandoffTicketStore
from stripe_checkout import StripeCheckoutError, retrieve_checkout_session, retrieve_payment_link, validate_paid_checkout_session, validate_payment_link_binding
from stripe_webhook import StripeWebhookError, verify_stripe_signature

BASE_DIR = Path(__file__).resolve().parent
ENTITLEMENT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))
HANDOFF_DB = Path(os.getenv("WEB_AI_HANDOFF_DB", ENTITLEMENT_DB.parent / "webai-handoff.sqlite3"))
CHECKOUT_STATE_DB = Path(os.getenv("WEB_AI_CHECKOUT_STATE_DB", ENTITLEMENT_DB.parent / "webai-checkout-state.sqlite3"))
PAID_PAGE = BASE_DIR / "static" / "paid.html"
entitlements = EntitlementStore(ENTITLEMENT_DB)
checkout_state = CheckoutStateStore(CHECKOUT_STATE_DB)
SUPPORTED_MANUAL_ACCESS = {"BUY_ONCE", "SUBSCRIPTION"}
BYOK_SESSION_TTL_SECONDS = int(os.getenv("WEB_AI_BYOK_SESSION_TTL_SECONDS", "900"))
BYOK_SESSION_MAX = int(os.getenv("WEB_AI_BYOK_SESSION_MAX", "1000"))
HANDOFF_TTL_SECONDS = int(os.getenv("WEB_AI_HANDOFF_TTL_SECONDS", "600"))
ENTITLEMENT_COOKIE_MAX_AGE_SECONDS = int(os.getenv("WEB_AI_ENTITLEMENT_COOKIE_MAX_AGE_SECONDS", "31536000"))
ENTITLEMENT_COOKIE_SECRET = os.getenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", "")
STRIPE_SECRET_KEY = os.getenv("WEB_AI_STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("WEB_AI_STRIPE_WEBHOOK_SECRET", "")
byok_sessions = ByokSessionStore(ttl_seconds=BYOK_SESSION_TTL_SECONDS, max_sessions=BYOK_SESSION_MAX)
handoffs = HandoffTicketStore(HANDOFF_DB, ttl_seconds=HANDOFF_TTL_SECONDS)


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


def entitlement_cookie_name(slug: str) -> str:
    return f"webai_access_{slug}"


def set_byok_cookie(response: Response, *, slug: str, token: str) -> None:
    response.set_cookie(key=byok_cookie_name(slug), value=token, max_age=BYOK_SESSION_TTL_SECONDS, httponly=True, secure=not insecure_http_allowed(), samesite="strict", path="/")


def clear_byok_cookie(response: Response, *, slug: str) -> None:
    response.delete_cookie(key=byok_cookie_name(slug), httponly=True, secure=not insecure_http_allowed(), samesite="strict", path="/")


def set_entitlement_cookie(response: Response, *, slug: str, payment_ref: str) -> None:
    if len(ENTITLEMENT_COOKIE_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Automatic buyer handoff is not configured")
    cookie = sign_entitlement_cookie(secret=ENTITLEMENT_COOKIE_SECRET, package_id=slug, payment_ref=payment_ref)
    response.set_cookie(key=entitlement_cookie_name(slug), value=cookie, max_age=ENTITLEMENT_COOKIE_MAX_AGE_SECONDS, httponly=True, secure=not insecure_http_allowed(), samesite="lax", path="/")


def entitlement_payment_ref(request: Request, *, slug: str) -> str | None:
    if len(ENTITLEMENT_COOKIE_SECRET) < 32:
        return None
    return verify_entitlement_cookie(secret=ENTITLEMENT_COOKIE_SECRET, cookie=request.cookies.get(entitlement_cookie_name(slug)), package_id=slug)


def free_page_response() -> FileResponse:
    response = FileResponse(core.STATIC_DIR / "index.html")
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
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    return response


def secure_handoff_html(body: str, *, status_code: int = 200) -> HTMLResponse:
    response = HTMLResponse(body, status_code=status_code)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # The only inline script on the checkout completion page calls
    # history.replaceState to scrub the Stripe session_id from the visible URL.
    # No external scripts, network calls, or user-authored HTML are permitted.
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


def _handoff_page(*, slug: str, ticket: str | None = None, scrub_completion_url: bool = False) -> str:
    activate_url = f"/checkout/activate/{slug}"
    clean_handoff_url = f"/checkout/handoff/{slug}"
    scrub = f"<script>history.replaceState(null,'','{clean_handoff_url}');</script>" if scrub_completion_url else ""
    common_style = "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;color:#111;background:#fff}main{max-width:720px;margin:auto;padding:40px 28px}h1{font-size:32px}p{font-size:18px;line-height:1.65;color:#555}.card{border:1px solid #ddd;border-radius:18px;padding:24px;margin-top:28px}form{margin:0}button{display:block;width:100%;border:0;background:#111;color:#fff;text-align:center;font-size:20px;font-weight:700;padding:18px;border-radius:16px;margin-top:22px}input{box-sizing:border-box;width:100%;font-size:18px;padding:15px;border:1px solid #bbb;border-radius:12px}small{display:block;margin-top:20px;color:#777;line-height:1.5}details{margin-top:24px}code{display:block;overflow-wrap:anywhere;background:#f5f5f5;padding:12px;border-radius:10px;margin:12px 0}a{color:#111}"
    if ticket:
        escaped_ticket = html.escape(ticket, quote=True)
        return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>購入確認完了</title><style>{common_style}</style></head><body>{scrub}<main><h1>購入確認が完了しました</h1><div class="card"><p>同じブラウザで使う場合は、そのまま下のボタンを押してください。</p><form method="post" action="{html.escape(activate_url, quote=True)}"><input type="hidden" name="ticket" value="{escaped_ticket}"><button type="submit">この端末でAIを使う</button></form><details><summary>別のSafariへ受け渡す</summary><p>下の1回限りの転送コードをコピーし、Safariで <a href="{html.escape(clean_handoff_url, quote=True)}">購入者アクセス受け渡し画面</a> を開いて貼り付けてください。転送コードをスクリーンショットやログへ残さないでください。</p><code>{html.escape(ticket)}</code></details><small>転送コードは約10分・1回だけ有効です。URLには転送コードを含めません。</small></div></main></body></html>"""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>購入者アクセス受け渡し</title><style>{common_style}</style></head><body><main><h1>購入者アクセス受け渡し</h1><div class="card"><p>購入完了画面で表示された1回限りの転送コードを入力してください。</p><form method="post" action="{html.escape(activate_url, quote=True)}"><input name="ticket" required autocomplete="off" autocapitalize="none" spellcheck="false" aria-label="転送コード"><button type="submit">この端末でAIを使う</button></form><small>転送コードはURLへ入れないでください。期限切れ・使用済みのコードは拒否されます。</small></div></main></body></html>"""


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
        raise HTTPException(status_code=503, detail="This paid access mode is not supported by hosted entitlement v0")
    if access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise HTTPException(status_code=503, detail="Paid hosted entitlement enforcement is not activated")
    billing = app_config.get("billing") or {}
    if billing.get("allowed_payer_modes") != ["BYOK"] or billing.get("default_payer_mode") != "BYOK":
        raise HTTPException(status_code=503, detail="Paid hosted v0 requires BYOK-only inference to avoid unallocated subsidy risk")


def require_entitlement(app_config: dict, token: str | None, *, request: Request) -> None:
    ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") == "FREE":
        return
    package_id = app_config["slug"]
    if entitlements.authorize(package_id=package_id, token=(token or "").strip()):
        return
    payment_ref = entitlement_payment_ref(request, slug=package_id)
    if entitlements.authorize_payment(package_id=package_id, payment_ref=payment_ref):
        return
    raise HTTPException(status_code=401, detail="Valid buyer access is required")


def resolve_byok_package(slug: str, buyer_token: str | None, *, request: Request) -> dict:
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token, request=request)
    billing = app_config.get("billing") or {}
    if "BYOK" not in (billing.get("allowed_payer_modes") or []):
        raise HTTPException(status_code=403, detail="BYOK is not allowed for this AI Package")
    return app_config


def ensure_payment_entitlement(*, verified: dict) -> str:
    package_id = verified["package_id"]
    payment_ref = verified["payment_ref"]
    state = entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)
    if state == PAYMENT_MISSING:
        try:
            entitlements.issue(package_id=package_id, buyer_ref=verified["buyer_ref"], payment_ref=payment_ref)
        except ValueError:
            state = entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)
            if state != PAYMENT_ACTIVE:
                raise HTTPException(status_code=409, detail="Checkout fulfillment could not establish an active entitlement") from None
    elif state in {PAYMENT_REVOKED, PAYMENT_EXPIRED}:
        raise HTTPException(status_code=403, detail="This payment's buyer access is no longer active")
    elif state != PAYMENT_ACTIVE:
        raise HTTPException(status_code=409, detail="Unknown entitlement lifecycle state")
    if not entitlements.authorize_payment(package_id=package_id, payment_ref=payment_ref):
        raise HTTPException(status_code=409, detail="Checkout fulfillment did not establish an active entitlement")
    return payment_ref


core.ensure_hosted_runnable = ensure_commercial_hosted_runnable
app = FastAPI(title="WebAI Bridge Commercial Gateway", version="0.8.0-body-handoff")


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
    options["buyer_entitlement_transport"] = "SIGNED_HTTPONLY_COOKIE_WITH_LEGACY_BEARER_FALLBACK"
    options["stripe_auto_handoff"] = "BUY_ONCE_WEBHOOK_PLUS_REDIRECT_SINGLE_BROWSER_CLAIM_V1"
    options["stripe_webhook_fulfillment"] = "CHECKOUT_SESSION_COMPLETED_OR_ASYNC_SUCCEEDED__IDEMPOTENT"
    options["browser_handoff_transport"] = "ONE_TIME_POST_BODY_CODE_NO_AUTHORITY_IN_URL_V1"
    return options


@app.post("/api/studio/validate")
def creator_studio_validate(payload: core.StudioDraft, request: Request) -> dict:
    return adapt_manual_hosted_entitlement(core.creator_studio_validate(payload=payload, request=request))


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")) -> dict:
    require_secure_transport(request)
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhook verification is not configured")
    raw = await request.body()
    try:
        event = verify_stripe_signature(payload=raw, signature_header=stripe_signature or "", endpoint_secret=STRIPE_WEBHOOK_SECRET)
    except StripeWebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    event_id = event["id"]
    event_type = str(event.get("type") or "")
    if checkout_state.event_processed(event_id):
        return {"received": True, "duplicate": True}
    if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        checkout_state.mark_event_processed(event_id=event_id, event_type=event_type or "ignored")
        return {"received": True, "ignored": True}
    session = ((event.get("data") or {}).get("object") or {})
    if not isinstance(session, dict) or session.get("payment_status") != "paid":
        checkout_state.mark_event_processed(event_id=event_id, event_type=event_type)
        return {"received": True, "ignored_unpaid": True}
    slug = str((session.get("metadata") or {}).get("webai_package_id") or "")
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        checkout_state.mark_event_processed(event_id=event_id, event_type=event_type)
        return {"received": True, "ignored_unknown_package": True}
    ensure_commercial_hosted_runnable(app_config)
    try:
        verified = validate_paid_checkout_session(session=session, app_config=app_config)
        payment_link = retrieve_payment_link(secret_key=STRIPE_SECRET_KEY, payment_link_id=verified["payment_link_id"])
        validate_payment_link_binding(payment_link=payment_link, app_config=app_config)
    except StripeCheckoutError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    lifecycle = entitlements.payment_state(package_id=verified["package_id"], payment_ref=verified["payment_ref"])
    if lifecycle in {PAYMENT_REVOKED, PAYMENT_EXPIRED}:
        checkout_state.mark_event_processed(event_id=event_id, event_type=event_type)
        return {"received": True, "ignored_terminal": True}
    ensure_payment_entitlement(verified=verified)
    checkout_state.mark_event_processed(event_id=event_id, event_type=event_type)
    return {"received": True, "fulfilled": True, "package_id": slug}


@app.get("/checkout/complete/{slug}")
def checkout_complete(slug: str, request: Request, session_id: str | None = None):
    require_secure_transport(request)
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") != "BUY_ONCE":
        raise HTTPException(status_code=503, detail="Automatic Checkout handoff supports BUY_ONCE only")
    if not session_id:
        body = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>購入確認</title></head><body><main><h1>購入情報を確認できません</h1><p>Stripeからの購入完了情報がありません。Payment Linkから決済完了ページを開き直してください。</p><p><a href="/a/{html.escape(slug, quote=True)}">購入者アクセスへ戻る</a></p></main></body></html>"""
        return secure_handoff_html(body, status_code=400)
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe Checkout verification is not configured")
    if len(ENTITLEMENT_COOKIE_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Automatic buyer handoff is not configured")
    try:
        session = retrieve_checkout_session(secret_key=STRIPE_SECRET_KEY, session_id=session_id)
        verified = validate_paid_checkout_session(session=session, app_config=app_config)
        payment_link = retrieve_payment_link(secret_key=STRIPE_SECRET_KEY, payment_link_id=verified["payment_link_id"])
        validate_payment_link_binding(payment_link=payment_link, app_config=app_config)
    except StripeCheckoutError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    payment_ref = ensure_payment_entitlement(verified=verified)
    if not checkout_state.claim_checkout(session_id=verified["checkout_session_id"], package_id=verified["package_id"], payment_ref=payment_ref):
        raise HTTPException(status_code=409, detail="This Checkout Session has already been claimed")
    ticket = handoffs.issue(package_id=verified["package_id"], payment_ref=payment_ref)
    return secure_handoff_html(_handoff_page(slug=slug, ticket=ticket, scrub_completion_url=True))


@app.get("/checkout/handoff/{slug}")
def checkout_handoff(slug: str, request: Request):
    require_secure_transport(request)
    core.enforce_rate_limit(request)
    try:
        core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    return secure_handoff_html(_handoff_page(slug=slug))


@app.post("/checkout/activate/{slug}")
async def checkout_activate(slug: str, request: Request):
    require_secure_transport(request)
    core.enforce_rate_limit(request)
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(status_code=413, detail="Browser handoff request is too large")
    try:
        form = parse_qs(raw.decode("utf-8"), keep_blank_values=False, strict_parsing=False)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Browser handoff request is not valid UTF-8") from None
    ticket_values = form.get("ticket") or []
    ticket = ticket_values[0].strip() if len(ticket_values) == 1 else ""
    if not ticket:
        raise HTTPException(status_code=400, detail="One-time browser handoff code is required")
    payment_ref = handoffs.consume(package_id=slug, ticket=ticket)
    if not payment_ref:
        raise HTTPException(status_code=409, detail="This browser handoff code is invalid, expired, or already used")
    if not entitlements.authorize_payment(package_id=slug, payment_ref=payment_ref):
        raise HTTPException(status_code=403, detail="Buyer access is no longer active")
    response = RedirectResponse(url=f"/a/{slug}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    set_entitlement_cookie(response, slug=slug, payment_ref=payment_ref)
    return response


@app.get("/apps/{slug}/public-config")
def paid_public_config(slug: str, request: Request, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    core.enforce_rate_limit(request)
    try:
        app_config = core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    if (app_config.get("access") or {}).get("mode") != "FREE":
        require_secure_transport(request)
    require_entitlement(app_config, buyer_token, request=request)
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
    resolve_byok_package(payload.slug, buyer_token, request=request)
    try:
        session = byok_sessions.create(package_id=payload.slug, api_key=payload.api_key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    set_byok_cookie(response, slug=payload.slug, token=session.token)
    return {"connected": True, "expires_in_seconds": BYOK_SESSION_TTL_SECONDS, "storage": "PROCESS_MEMORY_ONLY", "browser_api_key_retained": False}


@app.get("/api/byok/session/{slug}")
def byok_session_status(slug: str, request: Request, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    require_secure_transport(request)
    resolve_byok_package(slug, buyer_token, request=request)
    result = byok_sessions.status(package_id=slug, token=request.cookies.get(byok_cookie_name(slug)))
    result["storage"] = "PROCESS_MEMORY_ONLY"
    return result


@app.delete("/api/byok/session/{slug}")
def forget_byok_session(slug: str, request: Request, response: Response, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement")) -> dict:
    require_secure_transport(request)
    resolve_byok_package(slug, buyer_token, request=request)
    forgotten = byok_sessions.forget(request.cookies.get(byok_cookie_name(slug)))
    clear_byok_cookie(response, slug=slug)
    return {"forgotten": forgotten, "connected": False}


@app.post("/api/chat")
def paid_chat(payload: core.ChatRequest, request: Request, buyer_token: str | None = Header(default=None, alias="X-WebAI-Entitlement"), legacy_byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key")) -> dict:
    require_secure_transport(request)
    try:
        app_config = core.registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    require_entitlement(app_config, buyer_token, request=request)
    payer_mode = core.resolve_payer_mode(payload, app_config)
    byok_api_key = None
    if payer_mode == "BYOK":
        if legacy_byok_api_key:
            if not insecure_http_allowed():
                raise HTTPException(status_code=400, detail="Direct BYOK header transport is disabled; create an ephemeral BYOK session first")
            byok_api_key = legacy_byok_api_key
        else:
            byok_api_key = byok_sessions.resolve(package_id=payload.slug, token=request.cookies.get(byok_cookie_name(payload.slug)))
            if not byok_api_key:
                raise HTTPException(status_code=402, detail="BYOK session is missing or expired; reconnect your provider key")
    return core.chat(payload=payload, request=request, byok_api_key=byok_api_key)


# Intentionally no root mount of core.app here.
