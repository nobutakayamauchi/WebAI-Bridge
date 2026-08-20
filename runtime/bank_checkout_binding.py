from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from bank_checkout import BankCheckoutService
from bank_payment_ingress import BankOrderStore


BANK_CLAIM_COOKIE_TTL_SECONDS = int(os.getenv("WEB_AI_BANK_CLAIM_COOKIE_TTL_SECONDS", "604800"))


def _cookie_name(slug: str, order_ref: str) -> str:
    return f"webai_bank_{slug}_{order_ref}"


def _cookie_path(slug: str, order_ref: str) -> str:
    return f"/bank/checkout/{slug}/{order_ref}"


def _bank_details() -> dict[str, str]:
    return {
        "bank": os.getenv("WEB_AI_BANK_NAME", "").strip(),
        "branch": os.getenv("WEB_AI_BANK_BRANCH", "").strip(),
        "account_type": os.getenv("WEB_AI_BANK_ACCOUNT_TYPE", "").strip(),
        "account_no": os.getenv("WEB_AI_BANK_ACCOUNT_NO", "").strip(),
        "account_holder": os.getenv("WEB_AI_BANK_ACCOUNT_HOLDER", "").strip(),
    }


def _require_bank_details() -> dict[str, str]:
    details = _bank_details()
    if not all(details.values()):
        raise HTTPException(status_code=503, detail="Bank transfer destination is not configured")
    return details


def _instructions_page(base, *, slug: str, order_ref: str, amount_minor: int, details: dict[str, str]):
    status_url = f"/bank/checkout/{slug}/{order_ref}"
    body = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>銀行振込</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;color:#111}}main{{max-width:720px;margin:auto;padding:36px 24px}}.card{{border:1px solid #ddd;border-radius:16px;padding:22px}}dt{{font-weight:700;margin-top:14px}}dd{{margin:4px 0 0}}code{{font-size:22px;font-weight:800}}a{{display:block;margin-top:26px;padding:16px;border-radius:12px;background:#111;color:#fff;text-decoration:none;text-align:center}}</style></head><body><main><h1>銀行振込</h1><div class="card"><p>下記へ <strong>{amount_minor:,}円</strong> をお振込みください。</p><dl><dt>銀行</dt><dd>{html.escape(details['bank'])}</dd><dt>支店</dt><dd>{html.escape(details['branch'])}</dd><dt>口座種別</dt><dd>{html.escape(details['account_type'])}</dd><dt>口座番号</dt><dd>{html.escape(details['account_no'])}</dd><dt>口座名義</dt><dd>{html.escape(details['account_holder'])}</dd></dl><p>照合番号： <code>{html.escape(order_ref)}</code></p><p>振込時に利用できる場合は、振込依頼人番号またはEDI情報へこの照合番号を入力してください。入力欄がない場合は自動照合できないため、案内済みの問い合わせ窓口をご利用ください。</p><a href="{html.escape(status_url, quote=True)}">入金状況を確認</a></div></main></body></html>"""
    return base.secure_handoff_html(body)


def install_bank_checkout_binding(base) -> None:
    bank_order_db = Path(os.getenv("WEB_AI_BANK_ORDER_DB", base.ENTITLEMENT_DB.parent / "webai-bank-orders.sqlite3"))
    orders = BankOrderStore(bank_order_db)
    service = BankCheckoutService(orders)

    @base.app.post("/api/bank/buy/{slug}")
    def begin_bank_checkout(slug: str, request: Request):
        base.require_secure_transport(request)
        base.core.enforce_rate_limit(request)
        try:
            app_config = base.core.registry.get(slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown app") from None
        base.ensure_commercial_hosted_runnable(app_config)
        access = app_config.get("access") or {}
        if access.get("mode") != "BUY_ONCE":
            raise HTTPException(status_code=503, detail="Bank checkout supports BUY_ONCE only")
        amount_minor = int(access.get("price_amount_minor") or 0)
        currency = str(access.get("currency") or "").upper()
        if amount_minor <= 0 or currency != "JPY":
            raise HTTPException(status_code=503, detail="Bank checkout requires a positive JPY package price")
        details = _require_bank_details()
        checkout = service.create(package_id=slug, amount_minor=amount_minor, currency=currency)
        response = _instructions_page(base, slug=slug, order_ref=checkout.order_ref, amount_minor=amount_minor, details=details)
        response.set_cookie(
            key=_cookie_name(slug, checkout.order_ref),
            value=checkout.claim_token,
            max_age=BANK_CLAIM_COOKIE_TTL_SECONDS,
            httponly=True,
            secure=not base.insecure_http_allowed(),
            samesite="lax",
            path=_cookie_path(slug, checkout.order_ref),
        )
        return response

    @base.app.get("/bank/checkout/{slug}/{order_ref}")
    def bank_checkout_status(slug: str, order_ref: str, request: Request):
        base.require_secure_transport(request)
        base.core.enforce_rate_limit(request)
        claim_token = request.cookies.get(_cookie_name(slug, order_ref)) or ""
        try:
            order = service.claim_paid(order_ref=order_ref, claim_token=claim_token)
        except ValueError as exc:
            order = orders.get(order_ref)
            if order is not None and order.package_id == slug and order.status in {"PENDING", "AWAITING_PAYMENT"}:
                details = _require_bank_details()
                return _instructions_page(base, slug=slug, order_ref=order_ref, amount_minor=order.amount_minor, details=details)
            raise HTTPException(status_code=403, detail=str(exc)) from None
        if order.package_id != slug:
            raise HTTPException(status_code=403, detail="Bank order package mismatch")
        if not base.entitlements.authorize_payment(package_id=slug, payment_ref=order.payment_ref):
            raise HTTPException(status_code=409, detail="Paid bank order has no active entitlement")
        ticket = base.handoffs.issue(package_id=slug, payment_ref=order.payment_ref)
        response = base.secure_handoff_html(base._handoff_page(slug=slug, ticket=ticket))
        response.delete_cookie(
            key=_cookie_name(slug, order_ref),
            httponly=True,
            secure=not base.insecure_http_allowed(),
            samesite="lax",
            path=_cookie_path(slug, order_ref),
        )
        return response

    @base.app.get("/bank/checkout/{slug}")
    def bank_checkout_entry(slug: str, request: Request):
        base.require_secure_transport(request)
        base.core.enforce_rate_limit(request)
        try:
            app_config = base.core.registry.get(slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown app") from None
        base.ensure_commercial_hosted_runnable(app_config)
        body = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>銀行振込</title></head><body><main><h1>銀行振込で購入</h1><form method="post" action="/api/bank/buy/{html.escape(slug, quote=True)}"><button type="submit">銀行振込の注文を作成</button></form></main></body></html>"""
        return base.secure_handoff_html(body)
