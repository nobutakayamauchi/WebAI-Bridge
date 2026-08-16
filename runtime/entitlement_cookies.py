from __future__ import annotations

import base64
import hashlib
import hmac
import json

COOKIE_VERSION = 1


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_entitlement_cookie(*, secret: str, package_id: str, payment_ref: str) -> str:
    if len(secret) < 32:
        raise ValueError("entitlement cookie secret must be at least 32 characters")
    if not package_id or not payment_ref:
        raise ValueError("package_id and payment_ref are required")
    payload = json.dumps(
        {"v": COOKIE_VERSION, "package_id": package_id, "payment_ref": payment_ref},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64url(payload)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return encoded + "." + _b64url(signature)


def verify_entitlement_cookie(*, secret: str, cookie: str | None, package_id: str) -> str | None:
    if len(secret) < 32 or not cookie or "." not in cookie or not package_id:
        return None
    encoded, supplied_sig = cookie.split(".", 1)
    expected = _b64url(
        hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, supplied_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if payload.get("v") != COOKIE_VERSION or payload.get("package_id") != package_id:
        return None
    payment_ref = payload.get("payment_ref")
    return payment_ref if isinstance(payment_ref, str) and payment_ref else None
