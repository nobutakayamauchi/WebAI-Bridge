from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

COOKIE_SECRET = "c" * 48
SLUG = "migration-fixture-ai"
PAYMENT_REF = "pi_CANONICAL_HANDOFF123"
SESSION_ID = "cs_test_CANONICAL_HANDOFF123"
PAYMENT_LINK_ID = "plink_CANONICAL_HANDOFF123"
PAYMENT_LINK_URL = "https://buy.stripe.com/canonical-handoff-test"


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_TTL_SECONDS", "600")
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", COOKIE_SECRET)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_canonical_handoff")
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "1")
    for name in ["commercial", "app", "entitlements", "handoff_tickets", "cost_router"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial")
    cfg = module.core.registry.get(SLUG)
    cfg["status"] = "active"
    cfg["access"].update({
        "mode": "BUY_ONCE",
        "charge_basis": "ONE_TIME",
        "currency": "JPY",
        "price_amount_minor": 100,
        "commercial_enforcement": "ENTITLEMENT_ENFORCED",
        "checkout": {
            "provider": "STRIPE_PAYMENT_LINK",
            "setup_mode": "SELF_SETUP",
            "payment_link_url": PAYMENT_LINK_URL,
            "binding_verification": "CREATOR_ATTESTED",
            "fulfillment": "MANUAL_HANDOFF",
            "entitlement_verification": "NOT_IMPLEMENTED",
        },
    })
    cfg["billing"]["allowed_payer_modes"] = ["BYOK"]
    cfg["billing"]["default_payer_mode"] = "BYOK"
    cfg["billing"].pop("platform_credit", None)
    cfg["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": [],
    }
    return module


def fake_session():
    return {
        "id": SESSION_ID,
        "status": "complete",
        "payment_status": "paid",
        "mode": "payment",
        "payment_link": PAYMENT_LINK_ID,
        "payment_intent": PAYMENT_REF,
        "currency": "jpy",
        "amount_total": 100,
        "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"},
    }


def fake_payment_link():
    return {
        "id": PAYMENT_LINK_ID,
        "url": PAYMENT_LINK_URL,
        "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"},
    }


def test_canonical_gateway_transfers_checkout_once_to_target_browser(gateway, monkeypatch):
    module = gateway
    monkeypatch.setattr(module, "retrieve_checkout_session", lambda **kwargs: fake_session())
    monkeypatch.setattr(module, "retrieve_payment_link", lambda **kwargs: fake_payment_link())

    payment_browser = TestClient(module.app)
    safari = TestClient(module.app)

    completed = payment_browser.get(
        f"/checkout/complete/{SLUG}?session_id={SESSION_ID}",
        follow_redirects=False,
    )
    assert completed.status_code == 303, completed.text
    handoff_url = completed.headers["location"]
    assert handoff_url.startswith(f"/checkout/handoff/{SLUG}?ticket=handoff_")
    assert module.entitlement_cookie_name(SLUG) not in completed.headers.get("set-cookie", "")
    assert payment_browser.get(f"/apps/{SLUG}/public-config").status_code == 401

    landing = safari.get(handoff_url)
    assert landing.status_code == 200
    assert "Safari" in landing.text
    assert "購入者コード" in landing.text
    match = re.search(r'href="([^"]*checkout/activate/[^"]+)"', landing.text)
    assert match is not None
    activate_url = match.group(1).replace("&amp;", "&")

    activated = safari.get(activate_url, follow_redirects=False)
    assert activated.status_code == 303
    assert activated.headers["location"] == f"/a/{SLUG}"
    cookie = activated.headers.get("set-cookie", "")
    assert module.entitlement_cookie_name(SLUG) in cookie
    assert "HttpOnly" in cookie
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 200
    assert payment_browser.get(f"/apps/{SLUG}/public-config").status_code == 401

    assert payment_browser.get(activate_url, follow_redirects=False).status_code == 409
    assert payment_browser.get(
        f"/checkout/complete/{SLUG}?session_id={SESSION_ID}",
        follow_redirects=False,
    ).status_code == 409

    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref=PAYMENT_REF) == 1
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 401


def test_canonical_gateway_exposes_browser_transfer_capability(gateway):
    client = TestClient(gateway.app)
    response = client.get("/api/studio/options")
    assert response.status_code == 200, response.text
    options = response.json()
    assert options["stripe_auto_handoff"] == "BUY_ONCE_REDIRECT_VERIFICATION_SINGLE_CLAIM_BROWSER_TRANSFER_V1"
