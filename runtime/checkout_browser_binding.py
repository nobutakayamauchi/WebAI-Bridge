from __future__ import annotations

import html
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from checkout_binding import sign_checkout_binding, verify_checkout_binding
from stripe_checkout import StripeCheckoutError

CHECKOUT_BINDING_TTL_SECONDS = 1800
REFERENCE_PREFIX = "wb_"


def _cookie_name(slug: str) -> str:
    return f"webai_checkout_{slug}"


def _cookie_path(slug: str) -> str:
    return f"/checkout/complete/{slug}"


def _payment_link_with_reference(payment_link_url: str, client_reference_id: str) -> str:
    parts = urlsplit(payment_link_url)
    if parts.scheme.lower() != "https" or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise HTTPException(status_code=503, detail="Stripe Payment Link URL is not a safe HTTPS URL")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "client_reference_id"]
    query.append(("client_reference_id", client_reference_id))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _set_binding_cookie(base, response, *, slug: str, client_reference_id: str) -> None:
    if len(base.ENTITLEMENT_COOKIE_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Automatic buyer handoff is not configured")
    signed = sign_checkout_binding(
        secret=base.ENTITLEMENT_COOKIE_SECRET,
        package_id=slug,
        client_reference_id=client_reference_id,
        ttl_seconds=CHECKOUT_BINDING_TTL_SECONDS,
    )
    response.set_cookie(
        key=_cookie_name(slug),
        value=signed,
        max_age=CHECKOUT_BINDING_TTL_SECONDS,
        httponly=True,
        secure=not base.insecure_http_allowed(),
        samesite="lax",
        path=_cookie_path(slug),
    )


def _clear_binding_cookie(base, response, *, slug: str) -> None:
    response.delete_cookie(
        key=_cookie_name(slug),
        httponly=True,
        secure=not base.insecure_http_allowed(),
        samesite="lax",
        path=_cookie_path(slug),
    )


def _binding_error(base, *, slug: str, message: str, status_code: int):
    body = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>購入確認</title></head><body><main><h1>購入ブラウザを確認できません</h1><p>{html.escape(message)}</p><p><a href="/a/{html.escape(slug, quote=True)}">購入者アクセスへ戻る</a></p></main></body></html>"""
    return base.secure_handoff_html(body, status_code=status_code)


def install_checkout_browser_binding(base) -> None:
    """Bind Stripe completion to the browser that initiated checkout.

    Stripe's Checkout Session id remains a transaction locator in the success URL,
    but it is not sufficient to mint browser authority: the completion request must
    also carry a signed HttpOnly cookie whose public client_reference_id matches the
    verified Stripe Checkout Session. Handoff authority itself stays in a POST body.
    """

    replaced = {"/checkout/complete/{slug}", "/api/buy/{slug}"}
    base.app.router.routes[:] = [
        route for route in base.app.router.routes
        if getattr(route, "path", None) not in replaced
    ]

    @base.app.get("/api/buy/{slug}")
    def begin_checkout(slug: str, request: Request):
        base.require_secure_transport(request)
        base.core.enforce_rate_limit(request)
        try:
            app_config = base.core.registry.get(slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown app") from None
        base.ensure_commercial_hosted_runnable(app_config)
        access = app_config.get("access") or {}
        if access.get("mode") != "BUY_ONCE":
            raise HTTPException(status_code=503, detail="Automatic Checkout handoff supports BUY_ONCE only")
        checkout = access.get("checkout") or {}
        payment_link_url = str(checkout.get("payment_link_url") or "")
        if not payment_link_url:
            raise HTTPException(status_code=503, detail="Stripe Payment Link is not configured")

        client_reference_id = REFERENCE_PREFIX + secrets.token_urlsafe(24)
        target = _payment_link_with_reference(payment_link_url, client_reference_id)
        response = RedirectResponse(url=target, status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        _set_binding_cookie(base, response, slug=slug, client_reference_id=client_reference_id)
        return response

    @base.app.get("/checkout/complete/{slug}")
    def bound_checkout_complete(slug: str, request: Request, session_id: str | None = None):
        base.require_secure_transport(request)
        base.core.enforce_rate_limit(request)
        try:
            app_config = base.core.registry.get(slug)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown app") from None
        base.ensure_commercial_hosted_runnable(app_config)
        if (app_config.get("access") or {}).get("mode") != "BUY_ONCE":
            raise HTTPException(status_code=503, detail="Automatic Checkout handoff supports BUY_ONCE only")
        if not session_id:
            return _binding_error(
                base,
                slug=slug,
                message="Stripeからの購入完了情報がありません。購入者画面から決済を開始し直してください。",
                status_code=400,
            )
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

        browser_reference = verify_checkout_binding(
            secret=base.ENTITLEMENT_COOKIE_SECRET,
            cookie=request.cookies.get(_cookie_name(slug)),
            package_id=slug,
        )
        stripe_reference = session.get("client_reference_id")
        if not browser_reference or not isinstance(stripe_reference, str) or not secrets.compare_digest(browser_reference, stripe_reference):
            return _binding_error(
                base,
                slug=slug,
                message="この決済を開始したブラウザの確認情報が一致しません。購入者画面から決済を開始し直してください。",
                status_code=403,
            )

        payment_ref = base.ensure_payment_entitlement(verified=verified)
        if not base.checkout_state.claim_checkout(
            session_id=verified["checkout_session_id"],
            package_id=verified["package_id"],
            payment_ref=payment_ref,
        ):
            raise HTTPException(status_code=409, detail="This Checkout Session has already been claimed")
        ticket = base.handoffs.issue(package_id=verified["package_id"], payment_ref=payment_ref)
        response = base.secure_handoff_html(base._handoff_page(slug=slug, ticket=ticket, scrub_completion_url=True))
        _clear_binding_cookie(base, response, slug=slug)
        return response
