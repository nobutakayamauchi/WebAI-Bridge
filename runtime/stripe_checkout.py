from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SESSION_RE = re.compile(r"^cs_(?:live|test)_[A-Za-z0-9]+$")
PAYMENT_LINK_RE = re.compile(r"^plink_[A-Za-z0-9]+$")


class StripeCheckoutError(RuntimeError):
    pass


def _retrieve_json(*, secret_key: str, path: str, label: str, timeout: float) -> dict:
    if not secret_key.startswith("sk_") and not secret_key.startswith("rk_"):
        raise StripeCheckoutError("Stripe server API key is not configured")
    request = Request(
        "https://api.stripe.com" + path,
        headers={"Authorization": f"Bearer {secret_key}", "User-Agent": "WebAI-Bridge/stripe-auto-handoff-v0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise StripeCheckoutError(f"{label} lookup failed: HTTP {exc.code}") from None
    except URLError as exc:
        raise StripeCheckoutError(f"{label} lookup failed: {exc.reason}") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StripeCheckoutError(f"{label} response was not valid JSON") from None
    if not isinstance(payload, dict):
        raise StripeCheckoutError(f"{label} response was not an object")
    return payload


def retrieve_checkout_session(*, secret_key: str, session_id: str, timeout: float = 10.0) -> dict:
    if not SESSION_RE.fullmatch(session_id or ""):
        raise StripeCheckoutError("Invalid Stripe Checkout Session id")
    return _retrieve_json(
        secret_key=secret_key,
        path="/v1/checkout/sessions/" + quote(session_id, safe=""),
        label="Stripe Checkout Session",
        timeout=timeout,
    )


def retrieve_payment_link(*, secret_key: str, payment_link_id: str, timeout: float = 10.0) -> dict:
    if not PAYMENT_LINK_RE.fullmatch(payment_link_id or ""):
        raise StripeCheckoutError("Invalid Stripe Payment Link id")
    return _retrieve_json(
        secret_key=secret_key,
        path="/v1/payment_links/" + quote(payment_link_id, safe=""),
        label="Stripe Payment Link",
        timeout=timeout,
    )


def validate_payment_link_binding(*, payment_link: dict, app_config: dict) -> None:
    access = app_config.get("access") or {}
    checkout = access.get("checkout") or {}
    expected_url = str(checkout.get("payment_link_url") or "")
    actual_id = payment_link.get("id")
    actual_url = payment_link.get("url")
    if not isinstance(actual_id, str) or not PAYMENT_LINK_RE.fullmatch(actual_id):
        raise StripeCheckoutError("Stripe Payment Link id is invalid")
    if not expected_url or actual_url != expected_url:
        raise StripeCheckoutError("Stripe Payment Link URL binding mismatch")
    metadata = payment_link.get("metadata") or {}
    slug = str(app_config.get("slug") or "")
    if metadata.get("webai_package_id") != slug or metadata.get("access_mode") != "BUY_ONCE":
        raise StripeCheckoutError("Stripe Payment Link metadata binding mismatch")


def validate_paid_checkout_session(*, session: dict, app_config: dict) -> dict:
    access = app_config.get("access") or {}
    slug = str(app_config.get("slug") or "")
    if access.get("mode") != "BUY_ONCE":
        raise StripeCheckoutError("Automatic Checkout handoff v0 supports BUY_ONCE only")
    if session.get("status") != "complete" or session.get("payment_status") != "paid":
        raise StripeCheckoutError("Stripe Checkout Session is not fully paid")
    if session.get("mode") != "payment":
        raise StripeCheckoutError("Stripe Checkout Session mode does not match BUY_ONCE")
    payment_link_id = session.get("payment_link")
    if not isinstance(payment_link_id, str) or not PAYMENT_LINK_RE.fullmatch(payment_link_id):
        raise StripeCheckoutError("Stripe Checkout Session is not bound to a valid Payment Link")

    metadata = session.get("metadata") or {}
    if metadata.get("webai_package_id") != slug:
        raise StripeCheckoutError("Stripe Checkout Session package binding mismatch")
    if metadata.get("access_mode") != "BUY_ONCE":
        raise StripeCheckoutError("Stripe Checkout Session access-mode binding mismatch")

    expected_currency = str(access.get("currency") or "").lower()
    if str(session.get("currency") or "").lower() != expected_currency:
        raise StripeCheckoutError("Stripe Checkout Session currency mismatch")
    if int(session.get("amount_total") or -1) != int(access.get("price_amount_minor") or 0):
        raise StripeCheckoutError("Stripe Checkout Session amount mismatch")

    payment_ref = session.get("payment_intent")
    if not isinstance(payment_ref, str) or not payment_ref.startswith("pi_"):
        raise StripeCheckoutError("Stripe Checkout Session has no usable PaymentIntent reference")
    session_id = session.get("id")
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        raise StripeCheckoutError("Stripe Checkout Session id is invalid")

    return {
        "package_id": slug,
        "payment_ref": payment_ref,
        "payment_link_id": payment_link_id,
        "buyer_ref": f"stripe-checkout:{session_id}",
        "checkout_session_id": session_id,
    }
