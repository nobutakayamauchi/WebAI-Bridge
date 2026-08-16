from __future__ import annotations

import hashlib
import hmac
import json
import time


class StripeWebhookError(RuntimeError):
    pass


def verify_stripe_signature(
    *,
    payload: bytes,
    signature_header: str,
    endpoint_secret: str,
    now: int | None = None,
    tolerance_seconds: int = 300,
) -> dict:
    """Verify Stripe's signed raw request body without mutating it first."""
    if not endpoint_secret:
        raise StripeWebhookError("Stripe webhook endpoint secret is not configured")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in (signature_header or "").split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                pass
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise StripeWebhookError("Stripe-Signature header is invalid")
    current = int(time.time()) if now is None else int(now)
    if tolerance_seconds >= 0 and abs(current - timestamp) > tolerance_seconds:
        raise StripeWebhookError("Stripe webhook signature timestamp is outside tolerance")
    signed = str(timestamp).encode("ascii") + b"." + payload
    expected = hmac.new(endpoint_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeWebhookError("Stripe webhook signature mismatch")
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StripeWebhookError("Stripe webhook payload is not valid JSON") from None
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"].startswith("evt_"):
        raise StripeWebhookError("Stripe webhook event is invalid")
    return event
