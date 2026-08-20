from __future__ import annotations

import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from checkout_binding import sign_checkout_binding, verify_checkout_binding

SECRET = "b" * 48
SLUG = "browser-bound-ai"
REFERENCE = "wb_public_reference_123"


def test_checkout_binding_round_trip_is_package_scoped_and_time_bounded() -> None:
    cookie = sign_checkout_binding(
        secret=SECRET,
        package_id=SLUG,
        client_reference_id=REFERENCE,
        ttl_seconds=600,
        now=1_000,
    )
    assert verify_checkout_binding(secret=SECRET, cookie=cookie, package_id=SLUG, now=1_100) == REFERENCE
    assert verify_checkout_binding(secret=SECRET, cookie=cookie, package_id="other-ai", now=1_100) is None
    assert verify_checkout_binding(secret=SECRET, cookie=cookie, package_id=SLUG, now=1_600) is None


def test_checkout_binding_rejects_tampering_and_wrong_secret() -> None:
    cookie = sign_checkout_binding(
        secret=SECRET,
        package_id=SLUG,
        client_reference_id=REFERENCE,
        ttl_seconds=600,
        now=1_000,
    )
    encoded, signature = cookie.split(".", 1)
    tampered = encoded + ("A" if encoded[-1] != "A" else "B") + "." + signature
    assert verify_checkout_binding(secret=SECRET, cookie=tampered, package_id=SLUG, now=1_100) is None
    assert verify_checkout_binding(secret="x" * 48, cookie=cookie, package_id=SLUG, now=1_100) is None


def test_checkout_binding_rejects_weak_secret_and_unsafe_ttl() -> None:
    for secret, ttl in [("short", 600), (SECRET, 59), (SECRET, 86_401)]:
        try:
            sign_checkout_binding(
                secret=secret,
                package_id=SLUG,
                client_reference_id=REFERENCE,
                ttl_seconds=ttl,
                now=1_000,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe checkout binding parameters must fail closed")
