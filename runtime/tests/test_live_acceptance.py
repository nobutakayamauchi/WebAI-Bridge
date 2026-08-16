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
                return Response(200, {"content-type": "application/json"}, json.dumps({
                    "slug": "paid-ai",
                    "display_name": "Paid AI",
                    "access": {"mode": "BUY_ONCE"},
                }).encode())
            return Response(401, {"content-type": "application/json"}, json.dumps({"detail": "Valid buyer access token is required"}).encode())
        if url.endswith("/api/chat"):
            if headers.get("X-WebAI-Entitlement") != "webai_abcdefghijklmnopqrstuvwxyz123456":
                return Response(401, {}, b"{}")
            if headers.get("X-Provider-API-Key") != "provider-secret":
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
    assert result["evidence"][-1] == {"gate": "live_provider", "status": "SKIPPED"}
    assert not any(call["url"].endswith("/api/chat") for call in requester.calls)


def test_provider_acceptance_uses_secrets_but_never_returns_them():
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
    provider = result["evidence"][-1]
    assert provider["status"] == "PASS"
    assert provider["payer_mode"] == "BYOK"
    assert provider["response_chars"] > 0
    assert len(provider["response_sha256"]) == 64


def test_remote_http_is_never_allowed_even_with_local_override():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://ai.example.com", allow_local_http=True)


def test_local_http_requires_explicit_override():
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base_url("http://127.0.0.1:8080", allow_local_http=False)
    assert normalize_base_url("http://127.0.0.1:8080", allow_local_http=True) == "http://127.0.0.1:8080"


def test_base_url_rejects_credentials_path_query_and_fragment():
    for value in [
        "https://user:pass@ai.example.com",
        "https://ai.example.com/path",
        "https://ai.example.com?token=x",
        "https://ai.example.com#secret",
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


def test_live_provider_call_requires_provider_key_before_any_chat_request():
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
