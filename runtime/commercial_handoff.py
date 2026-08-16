from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import commercial as base
from entitlements import PAYMENT_ACTIVE, PAYMENT_EXPIRED, PAYMENT_MISSING, PAYMENT_REVOKED
from handoff_tickets import HandoffTicketStore
from stripe_checkout import StripeCheckoutError

HANDOFF_TTL_SECONDS = int(os.getenv("WEB_AI_HANDOFF_TTL_SECONDS", "600"))
HANDOFF_DB = Path(
    os.getenv(
        "WEB_AI_HANDOFF_DB",
        str(base.ENTITLEMENT_DB.parent / "webai-handoff.sqlite3"),
    )
)
handoffs = HandoffTicketStore(HANDOFF_DB, ttl_seconds=HANDOFF_TTL_SECONDS)

app = FastAPI(title="WebAI Bridge Commercial Handoff Gateway", version="0.6.0-browser-handoff")


def _secure_html(body: str, *, status_code: int = 200) -> HTMLResponse:
    response = HTMLResponse(body, status_code=status_code)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response


@app.get("/checkout/complete/{slug}")
def checkout_complete(slug: str, session_id: str, request: Request):
    base.require_secure_transport(request)
    try:
        app_config = base.core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    base.ensure_commercial_hosted_runnable(app_config)
    if (app_config.get("access") or {}).get("mode") != "BUY_ONCE":
        raise HTTPException(status_code=503, detail="Automatic Checkout handoff supports BUY_ONCE only")
    if not base.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe Checkout verification is not configured")
    if len(base.ENTITLEMENT_COOKIE_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Automatic buyer handoff is not configured")

    try:
        session = base.retrieve_checkout_session(secret_key=base.STRIPE_SECRET_KEY, session_id=session_id)
        verified = base.validate_paid_checkout_session(session=session, app_config=app_config)
        payment_link = base.retrieve_payment_link(
            secret_key=base.STRIPE_SECRET_KEY,
            payment_link_id=verified["payment_link_id"],
        )
        base.validate_payment_link_binding(payment_link=payment_link, app_config=app_config)
    except StripeCheckoutError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    payment_ref = verified["payment_ref"]
    package_id = verified["package_id"]
    state = base.entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)
    if state == PAYMENT_MISSING:
        try:
            base.entitlements.issue(
                package_id=package_id,
                buyer_ref=verified["buyer_ref"],
                payment_ref=payment_ref,
            )
        except ValueError:
            state = base.entitlements.payment_state(package_id=package_id, payment_ref=payment_ref)
            if state == PAYMENT_ACTIVE:
                raise HTTPException(status_code=409, detail="This Checkout Session has already been claimed") from None
            raise HTTPException(status_code=409, detail="Checkout fulfillment could not establish an active entitlement") from None
    elif state == PAYMENT_ACTIVE:
        raise HTTPException(status_code=409, detail="This Checkout Session has already been claimed")
    elif state in {PAYMENT_REVOKED, PAYMENT_EXPIRED}:
        raise HTTPException(status_code=403, detail="This payment's buyer access is no longer active")
    else:
        raise HTTPException(status_code=409, detail="Unknown entitlement lifecycle state")

    if not base.entitlements.authorize_payment(package_id=package_id, payment_ref=payment_ref):
        raise HTTPException(status_code=409, detail="Checkout fulfillment did not establish an active entitlement")

    ticket = handoffs.issue(package_id=package_id, payment_ref=payment_ref)
    response = RedirectResponse(
        url=f"/checkout/handoff/{slug}?ticket={quote(ticket, safe='')}",
        status_code=303,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/checkout/handoff/{slug}")
def checkout_handoff(slug: str, ticket: str, request: Request):
    base.require_secure_transport(request)
    try:
        base.core.registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    activate_url = f"/checkout/activate/{quote(slug, safe='')}?ticket={quote(ticket, safe='')}"
    body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>購入確認完了</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;color:#111;background:#fff}}main{{max-width:720px;margin:auto;padding:40px 28px}}h1{{font-size:32px}}p{{font-size:18px;line-height:1.65;color:#555}}.card{{border:1px solid #ddd;border-radius:18px;padding:24px;margin-top:28px}}a{{display:block;background:#111;color:#fff;text-decoration:none;text-align:center;font-size:20px;font-weight:700;padding:18px;border-radius:16px;margin-top:22px}}small{{display:block;margin-top:20px;color:#777;line-height:1.5}}</style></head>
<body><main><h1>購入確認が完了しました</h1><div class="card"><p><strong>Safariでこの画面を開いてから</strong>、下のボタンを押してください。</p><p>アプリ内ブラウザの場合は、Safariアイコン／「Safariで開く」を使ってこの画面をSafariへ移してください。</p><a href="{html.escape(activate_url, quote=True)}">この端末でAIを使う</a><small>この受け渡しリンクは約10分・1回だけ有効です。購入者コードを入力する必要はありません。</small></div></main></body></html>"""
    return _secure_html(body)


@app.get("/checkout/activate/{slug}")
def checkout_activate(slug: str, ticket: str, request: Request):
    base.require_secure_transport(request)
    payment_ref = handoffs.consume(package_id=slug, ticket=ticket)
    if not payment_ref:
        raise HTTPException(status_code=409, detail="This browser handoff link is invalid, expired, or already used")
    if not base.entitlements.authorize_payment(package_id=slug, payment_ref=payment_ref):
        raise HTTPException(status_code=403, detail="Buyer access is no longer active")
    response = RedirectResponse(url=f"/a/{slug}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    base.set_entitlement_cookie(response, slug=slug, payment_ref=payment_ref)
    return response


app.mount("/", base.app)
