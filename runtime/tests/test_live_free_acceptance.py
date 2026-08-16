from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from live_acceptance import Response
from live_free_acceptance import run_free_acceptance


class FakeRequester:
    def __init__(self):
        self.calls = []
        self.config_override = None
        self.session_cookie = "webai_byok_migration-fixture-ai=byok_opaque_test_session"
        self.session_connected = False

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
            return Response(200, {"content-type": "application/json"}, json.dumps({
                "status": "ok",
                "pricing_version": "test-pricing",
            }).encode())
        if "/a/" in url:
            return Response(200, {"content-type": "text/html"}, b"<html></html>")
        if url.endswith("/public-config"):
            config = self.config_override or {
                "slug": "migration-fixture-ai",
                "display_name": "Migration Fixture AI",
                "status": "dogfood",
                "access": {"mode": "FREE", "price_amount_minor": 0},
                "delivery": {"mode": "HOSTED_ONLY", "runtime_implementation": "AVAILABLE"},
                "allowed_payer_modes": ["BYOK", "PLATFORM_CREDIT"],
                "default_payer_mode": "BYOK",
            }
            return Response(200, {"content-type": "application/json"}, json.dumps(config).encode())
        if url.endswith("/api/byok/session") and method == "POST":
            if (json_body or {}).get("api_key") != "provider-secret":
                return Response(422, {}, b"{}")
            self.session_connected = True
            return Response(
                200,
                {
                    "content-type": "application/json",
                    "set-cookie": self.session_cookie + "; Path=/; Max-Age=900; Secure; HttpOnly; SameSite=Strict",
                },
                json.dumps({
                    "connected": True,
                    "expires_in_seconds": 900,
                    "storage": "PROCESS_MEMORY_ONLY",
                    "browser_api_key_retained": False,
                }).encode(),
            )
        if url.endswith("/api/byok/session/migration-fixture-ai") and method == "GET":
            connected = self.session_connected and headers.get("Cookie") == self.session_cookie
            return Response(200, {"content-type": "application/json"}, json.dumps({
                "connected": connected,
                "expires_in_seconds": 899 if connected else 0,
                "storage": "PROCESS_MEMORY_ONLY",
            }).encode())
        if url.endswith("/api/byok/session/migration-fixture-ai") and method == "DELETE":
            self.session_connected = False
            return Response(200, {"content-type": "application/json"}, b'{"forgotten":true,"connected":false}')
        if url.endswith("/api/chat"):
            if headers.get("X-Provider-API-Key"):
                return Response(400, {}, b"{}")
            if not self.session_connected or headers.get("Cookie") != self.session_cookie:
                return Response(401, {}, b"{}")
            return Response(200, {"content-type": "application/json"}, json.dumps({
                "text": "free-live-ok",
                "model": "gpt-test",
                "payer_mode": "BYOK",
            }).encode())
        raise AssertionError(f"unexpected URL {url}")


def test_free_perimeter_acceptance_skips_provider_by_default():
    requester = FakeRequester()
    result = run_free_acceptance(
        requester,
        base_url="https://random.trycloudflare.com",
        slug="migration-fixture-ai",
    )
    assert result["status"] == "PASS"
    assert result["profile"] == "FREE_BYOK_DOGFOOD"
    assert result["secrets_returned"] is False
    assert result["evidence"][-1] == {"gate": "live_provider", "status": "SKIPPED"}
    assert not any(call["url"].endswith("/api/chat") for call in requester.calls)
    assert not any("/api/byok/session" in call["url"] for call in requester.calls)


def test_free_provider_acceptance_uses_ephemeral_session_and_never_returns_secret_or_text():
    requester = FakeRequester()
    result = run_free_acceptance(
        requester,
        base_url="https://random.trycloudflare.com",
        slug="migration-fixture-ai",
        provider_call=True,
        provider_key="provider-secret",
    )
    encoded = json.dumps(result)
    assert "provider-secret" not in encoded
    assert "free-live-ok" not in encoded
    assert "byok_opaque_test_session" not in encoded
    assert any(item["gate"] == "ephemeral_byok_session" and item["status"] == "PASS" for item in result["evidence"])
    provider = result["evidence"][-1]
    assert provider["status"] == "PASS"
    assert provider["payer_mode"] == "BYOK"
    assert provider["response_chars"] == len("free-live-ok")
    assert len(provider["response_sha256"]) == 64

    chat_call = next(call for call in requester.calls if call["url"].endswith("/api/chat"))
    assert "X-Provider-API-Key" not in chat_call["headers"]
    assert chat_call["headers"]["Cookie"] == requester.session_cookie
    assert requester.session_connected is False, "acceptance must forget the temporary BYOK session after the call"


def test_wrong_free_contract_fails_before_provider_or_session_creation():
    cases = [
        {"status": "draft"},
        {"access": {"mode": "BUY_ONCE", "price_amount_minor": 1500}},
        {"access": {"mode": "FREE", "price_amount_minor": 1}},
        {"delivery": {"mode": "PORTABLE_LICENSE", "runtime_implementation": "NOT_IMPLEMENTED"}},
        {"allowed_payer_modes": ["PLATFORM_CREDIT"]},
    ]
    for patch in cases:
        requester = FakeRequester()
        config = {
            "slug": "migration-fixture-ai",
            "display_name": "Migration Fixture AI",
            "status": "dogfood",
            "access": {"mode": "FREE", "price_amount_minor": 0},
            "delivery": {"mode": "HOSTED_ONLY", "runtime_implementation": "AVAILABLE"},
            "allowed_payer_modes": ["BYOK", "PLATFORM_CREDIT"],
            "default_payer_mode": "BYOK",
        }
        config.update(patch)
        requester.config_override = config
        with pytest.raises(RuntimeError):
            run_free_acceptance(
                requester,
                base_url="https://random.trycloudflare.com",
                slug="migration-fixture-ai",
                provider_call=True,
                provider_key="provider-secret",
            )
        assert not any(call["url"].endswith("/api/chat") for call in requester.calls)
        assert not any(call["url"].endswith("/api/byok/session") for call in requester.calls)


def test_provider_key_is_required_before_any_http_request():
    requester = FakeRequester()
    with pytest.raises(ValueError, match="provider_key"):
        run_free_acceptance(
            requester,
            base_url="https://random.trycloudflare.com",
            slug="migration-fixture-ai",
            provider_call=True,
        )
    assert requester.calls == []


def test_remote_http_is_rejected_for_free_dogfood():
    requester = FakeRequester()
    with pytest.raises(ValueError, match="HTTPS"):
        run_free_acceptance(
            requester,
            base_url="http://140.83.39.200:8080",
            slug="migration-fixture-ai",
            allow_local_http=True,
        )
    assert requester.calls == []
