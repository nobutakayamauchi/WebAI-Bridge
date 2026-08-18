from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

COOKIE_VERSION = 1
_SIGNATURE_DOMAIN = b"webai-checkout-binding-v1\x00"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_checkout_binding(
    *,
    secret: str,
    package_id: str,
    client_reference_id: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    if len(secret) < 32:
        raise ValueError("checkout binding secret must be at least 32 characters")
    if not package_id or not client_reference_id:
        raise ValueError("package_id and client_reference_id are required")
    if ttl_seconds < 60 or ttl_seconds > 86_400:
        raise ValueError("checkout binding TTL must be between 60 and 86400 seconds")
    issued_at = int(time.time()) if now is None else int(now)
    payload = json.dumps(
        {
            "v": COOKIE_VERSION,
            "package_id": package_id,
            "client_reference_id": client_reference_id,
            "exp": issued_at + int(ttl_seconds),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64url(payload)
    signature = hmac.new(
        secret.encode("utf-8"),
        _SIGNATURE_DOMAIN + encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return encoded + "." + _b64url(signature)


def verify_checkout_binding(
    *,
    secret: str,
    cookie: str | None,
    package_id: str,
    now: int | None = None,
) -> str | None:
    if len(secret) < 32 or not cookie or "." not in cookie or not package_id:
        return None
    encoded, supplied_sig = cookie.split(".", 1)
    expected = _b64url(
        hmac.new(
            secret.encode("utf-8"),
            _SIGNATURE_DOMAIN + encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(expected, supplied_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    current = int(time.time()) if now is None else int(now)
    if payload.get("v") != COOKIE_VERSION or payload.get("package_id") != package_id:
        return None
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at <= current:
        return None
    reference = payload.get("client_reference_id")
    return reference if isinstance(reference, str) and reference else None
