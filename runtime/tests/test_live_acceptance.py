from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from live_acceptance import Response, normalize_base_url, run_acceptance


class FakeRequester:
    def __init__(self):
        self.calls = []
        self.config_override = None
        self.cookie = "webai_byok_paid-ai=byok_opaque-session"

    def request(self, method, url, *, headers=None, json_body=None, timeout=30.0):
        headers = dict(headers or {})
        self.calls.append({
            "method": method,
            "url": url,
            "headers": headers,
            "json_body": json_body,
            "timeout": timeout,
        })
        if url.endswith("/health"):
            return Response(200, {"content-type": "application/json"}, json.dumps({"status": "ok", "pricing_version": "test-pricing"}).encode())
        if "/a/" in url:
            return Response(200, {
                "cache-control": "no-store",
                "referrer-policy": "no-referrer",
                "x-frame-options": "DENY",
                "x-content-type-options": "nosniff",
                "content-security-policy": "default-src 'none'; connect-src 'self'; frame-ancestors 'none'",
            }, b"<html></html>")
        if url.endswith("/public-config"):
            if headers.get("X-WebAI-Entitlement") == "webai_abcdefghijklmnopqrstuvwxyz123456":
                config = self.config_override or {
                    "slug": "paid-ai",
                    "display_name": "Paid AI",
                    "status": "active",
                    "access": {
                        "mode": "BUY_ONCE",
                        "commercial_enforcement": "ENTITLEMENT_ENFORCED",
                    },
                    "delivery": {
                        "mode": "HOSTED_ONLY",
                        "runtime_implementation": "AVAILABLE",
                    },
                    "allowed_payer_modes": ["BYOK"],
                    "default_payer_mode": "BYOK",
                }
                return Response(200, {"content-type": "application/json"}, json.dumps(config).encode())
            return Response(401, {"content-type": "application/json"}, json.dumps({"detail": "Valid buyer access token is required"}).encode())
        if url.endswith("/api/byok/session") and method.upper() == "POST":
            if headers.get("X-WebAI-Entitlement") != "webai_abcdefghijklmnopqrstuvwxyz123456":
                return Response(401, {}, b"{}")
            if json_body != {"slug": "paid-ai", "api_key": "provider-secret"}:
                return Response(400, {}, b"{}")
            return Response(200, {
                "content-type": "application/json",
                "set-cookie": "webai_byok_paid-ai=byok_opaque-session; Path=/; HttpOnly; Secure; SameSite=Strict",
            }, json.dumps({
                "connected": True,
                "expires_in_seconds": 900,
                "storage": "PROCESS_MEMORY_ONLY",
                "browser_api_key_retained": False,
            }).encode())
        if url.endswith("/api/byok/session/paid-ai"):
            if headers.get("X-WebAI-Entitlement") != "webai_abcdefghijklmnopqrstuvwxyz123456":
                return Response(401, {}, b"{}")
            if headers.get("Cookie") != self.cookie:
                return Response(402, {}, b"{}")
            if method.upper() == "DELETE":
                return Response(200, {"content-type": "application/json"}, json.dumps({"forgotten": True, "connected": False}).encode())
            return Response(200, {"content-type": "application/json"}, json.dumps({
                "connected": True,
                "expires_in_seconds": 899,
                "storage": "PROCESS_MEMORY_ONLY",
            }).encode())
        if url.endswith("/api/chat"):
            if headers.get("X-WebAI-Entitlement") != "webai_abcdefghijklmnopqrstuvwxyz123456":
                return Response(401, {}, b"{}")
            if headers.get("X-Provider-API-Key"):
                return Response(400, {}, json.dumps({"detail": "legacy provider header forbidden"}).encode())
            if headers.get("Cookie") != self.cookie:
                return Response(402, {}, b"{}")
            return Response(200, {"content-type": "application/json"}, json.dumps({
                "text": "live answer",
                "model": "gpt-test",
                "payer_mode": "BYOK",
            }).encode())
        raise AssertionError(f"unexpected URL {url}")


def token():
    return "webai_abcdefghijklmnopqrstuvwxyz123456"


def test_perimeter_acceptance_proves_https_headers_and_entitlement_without_provider_spend():
    requester = FakeRequester()
    result = run_acceptance(
        requester,
        base_url="https://ai.example.com",
        slug="paid-ai",
        entitlement=token(),
        provider_call=False,
    )
    assert result["status"] == "PASS"
    assert result["provider_call"] is False
    assert result["secrets_returned"] is False
    contract = result["evidence"][-2]
    assert contract["gate"] == "buyer_entitlement_contract"
    assert contract["access_mode"] == "BUY_ONCE"
    assert contract["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert contract["delivery_mode"] == "HOSTED_ONLY"
    assert contract["payer_mode"] == "BYOK"
    assert result["evidence"][-1] == {"gate": "live_provider", "status": "SKIPPED"}
    assert not any("/api/byok/session" in call["url"] for call in requester.calls)
    assert not any(call["url"].endswith("/api/chat") for call in requester.calls)


def test_provider_acceptance_uses_ephemeral_session_and_never_returns_secrets():
    requester = FakeRequester()
    result = run_acceptance(
        requester,
        base_url="https://ai.example.com",
        slug="paid-ai",
        entitlement=token(),
        provider_call=True,
        provider_key="provider-secret",
    )
    assert result["status"] == "PASS"
    encoded = json.dumps(result)
    assert token() not in encoded
    assert "provider-secret" not in encoded
    assert "byok_opaque-session" not in encoded
    session = next(item for item in result["evidence"] if item["gate"] == "ephemeral_byok_session")
    assert session == {"gate": "ephemeral_byok_session", "status": "PASS", "browser_api_key_retained": False}
    provider = result["evidence"][-1]
    assert provider["status"] == "PASS"
    assert provider["payer_mode"] == "BYOK"
    assert provider["response_chars"] > 0
    assert len(provider["response_sha256"]) == 64

    chat = next(call for call in requester.calls if call["url"].endswith("/api/chat"))
    assert "X-Provider-API-Key" not in chat["headers"]
    assert chat["headers"]["Cookie"] == requester.cookie
    assert any(call["method"] == "DELETE" and call["url"].endswith("/api/byok/session/paid-ai") for call in requester.calls)


def test_wrong_live_contract_fails_before_provider_or_session_call():
    cases = [
        {"status": "draft"},
        {"access": {"mode": "FREE", "commercial_enforcement": "NOT_IMPLEMENTED"}},
        {"access": {"mode": "BUY_ONCE", "commercial_enforcement": "NOT_IMPLEMENTED"}},
        {"delivery": {"mode": "PORTABLE_LICENSE", "runtime_implementation": "NOT_IMPLEMENTED"}},
        {"allowed_payer_modes": ["BYOK", "PLATFORM_CREDIT"]},
    ]
    for patch in cases:
        requester = FakeRequester()
        config = {
            "slug": "paid-ai",
            "display_name": "Paid AI",
            "status": "active",
            "access": {"mode": "BUY_ONCE", "commercial_enforcement": "ENTITLEMENT_ENFORCED"},
            "delivery": {"mode": "HOSTED_ONLY", "runtime_implementation": "AVAILABLE"},
            "allowed_payer_modes": ["BYOK"],
            "default_payer_mode": "BYOK",
        }
        config.update(patch)
        requester.config_override = config
        with pytest.raises(RuntimeError):
            run_acceptance(
                requester,
                base_url="https://ai.example.com",
                slug="paid-ai",
                entitlement=token(),
                provider_call=True,
                provider_key="provider-secret",
            )
        assert not any("/api/byok/session" in call["url"] for call in requester.calls)
        assert not any(call["url"].endswith("/api/chat") for call in requester.calls)


def test_remote_http_is_never_allowed_even_with_local_override():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://ai.example.com", allow_local_http=True)


def test_local_http_requires_explicit_override():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://127.0.0.1:8080", allow_local_http=False)
    assert normalize_base_url("http://127.0.0.1:8080", allow_local_http=True) == "http://127.0.0.1:8080"


def test_base_url_rejects_credentials_path_query_fragment_and_invalid_port():
    for value in [
        "https://user:pass@ai.example.com",
        "https://ai.example.com/path",
        "https://ai.example.com?token=x",
        "https://ai.example.com#secret",
        "https://ai.example.com:notaport",
    ]:
        with pytest.raises(ValueError):
            normalize_base_url(value)


def test_bad_buyer_page_security_headers_fail_acceptance():
    requester = FakeRequester()
    original = requester.request

    def bad(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if "/a/" in url:
            response.headers.pop("referrer-policy", None)
        return response

    requester.request = bad
    with pytest.raises(RuntimeError, match="referrer-policy"):
        run_acceptance(
            requester,
            base_url="https://ai.example.com",
            slug="paid-ai",
            entitlement=token(),
        )


def test_missing_entitlement_denial_is_required_evidence():
    requester = FakeRequester()
    original = requester.request

    def insecure(method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if url.endswith("/public-config") and "X-WebAI-Entitlement" not in headers:
            return Response(200, {}, json.dumps({"slug": "paid-ai"}).encode())
        return original(method, url, **kwargs)

    requester.request = insecure
    with pytest.raises(RuntimeError, match="expected HTTP 401"):
        run_acceptance(
            requester,
            base_url="https://ai.example.com",
            slug="paid-ai",
            entitlement=token(),
        )


def test_live_provider_call_requires_provider_key_before_any_http_request():
    requester = FakeRequester()
    with pytest.raises(ValueError, match="provider_key"):
        run_acceptance(
            requester,
            base_url="https://ai.example.com",
            slug="paid-ai",
            entitlement=token(),
            provider_call=True,
            provider_key=None,
        )
    assert requester.calls == []
