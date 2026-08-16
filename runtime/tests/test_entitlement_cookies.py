from entitlement_cookies import sign_entitlement_cookie, verify_entitlement_cookie


def test_signed_cookie_roundtrip_and_package_binding():
    secret = "s" * 48
    cookie = sign_entitlement_cookie(secret=secret, package_id="paid-a", payment_ref="pi_123")
    assert "pi_123" not in cookie
    assert verify_entitlement_cookie(secret=secret, cookie=cookie, package_id="paid-a") == "pi_123"
    assert verify_entitlement_cookie(secret=secret, cookie=cookie, package_id="paid-b") is None


def test_signed_cookie_rejects_tamper_wrong_secret_and_short_secret():
    cookie = sign_entitlement_cookie(secret="a" * 48, package_id="paid-a", payment_ref="pi_123")
    assert verify_entitlement_cookie(secret="b" * 48, cookie=cookie, package_id="paid-a") is None
    assert verify_entitlement_cookie(secret="a" * 48, cookie=cookie + "x", package_id="paid-a") is None
    assert verify_entitlement_cookie(secret="short", cookie=cookie, package_id="paid-a") is None
