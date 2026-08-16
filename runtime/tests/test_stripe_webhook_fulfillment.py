from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import re
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

SLUG = "migration-fixture-ai"
SESSION_ID = "cs_test_WebhookRace123"
PAYMENT_LINK_ID = "plink_WebhookRace123"
PAYMENT_REF = "pi_WebhookRace123"
PAYMENT_LINK_URL = "https://buy.stripe.com/webhook-race-test"
WEBHOOK_SECRET = "whsec_test_webai_bridge_webhook_secret"


def fake_session():
    return {"id": SESSION_ID, "status": "complete", "payment_status": "paid", "mode": "payment", "payment_link": PAYMENT_LINK_ID, "payment_intent": PAYMENT_REF, "currency": "jpy", "amount_total": 100, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def fake_link():
    return {"id": PAYMENT_LINK_ID, "url": PAYMENT_LINK_URL, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def signed_event(event_id: str, event_type: str = "checkout.session.completed"):
    payload = json.dumps({"id": event_id, "type": event_type, "data": {"object": fake_session()}}, separators=(",", ":")).encode()
    ts = int(time.time())
    digest = hmac.new(WEBHOOK_SECRET.encode(), str(ts).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return payload, f"t={ts},v1={digest}"


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_CHECKOUT_STATE_DB", str(tmp_path / "checkout-state.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", "w" * 48)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_webhook")
    monkeypatch.setenv("WEB_AI_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    for name in ["commercial", "app", "entitlements", "checkout_state", "handoff_tickets", "stripe_webhook", "cost_router"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial")
    cfg = module.core.registry.get(SLUG)
    cfg["status"] = "active"
    cfg["access"].update({"mode": "BUY_ONCE", "charge_basis": "ONE_TIME", "currency": "JPY", "price_amount_minor": 100, "commercial_enforcement": "ENTITLEMENT_ENFORCED", "checkout": {"provider": "STRIPE_PAYMENT_LINK", "setup_mode": "SELF_SETUP", "payment_link_url": PAYMENT_LINK_URL, "binding_verification": "CREATOR_ATTESTED", "fulfillment": "AUTO_WEBHOOK_PLUS_REDIRECT", "entitlement_verification": "STRIPE_VERIFIED"}})
    cfg["billing"]["allowed_payer_modes"] = ["BYOK"]
    cfg["billing"]["default_payer_mode"] = "BYOK"
    cfg["billing"].pop("platform_credit", None)
    monkeypatch.setattr(module, "retrieve_payment_link", lambda **kwargs: fake_link())
    monkeypatch.setattr(module, "retrieve_checkout_session", lambda **kwargs: fake_session())
    return module


def post_event(client, event_id: str):
    payload, signature = signed_event(event_id)
    return client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": signature})


def test_webhook_first_then_redirect_still_gets_exactly_one_browser_handoff(gateway):
    module = gateway
    webhook_client = TestClient(module.app)
    payment_browser = TestClient(module.app)
    first = post_event(webhook_client, "evt_WebhookFirst123")
    assert first.status_code == 200, first.text
    assert first.json()["fulfilled"] is True
    assert module.entitlements.authorize_payment(package_id=SLUG, payment_ref=PAYMENT_REF)
    redirect = payment_browser.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert redirect.status_code == 303, redirect.text
    assert redirect.headers["location"].startswith(f"/checkout/handoff/{SLUG}?ticket=handoff_")
    assert payment_browser.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False).status_code == 409
    assert len(module.entitlements.list_for_package(SLUG)) == 1


def test_redirect_first_then_webhook_is_idempotent(gateway):
    module = gateway
    client = TestClient(module.app)
    assert client.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False).status_code == 303
    assert len(module.entitlements.list_for_package(SLUG)) == 1
    webhook = post_event(client, "evt_RedirectFirst123")
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["fulfilled"] is True
    assert len(module.entitlements.list_for_package(SLUG)) == 1
    duplicate = post_event(client, "evt_RedirectFirst123")
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert len(module.entitlements.list_for_package(SLUG)) == 1


def test_bad_signature_is_rejected_without_entitlement(gateway):
    module = gateway
    payload, _ = signed_event("evt_BadSignature123")
    response = TestClient(module.app).post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": f"t={int(time.time())},v1={'0' * 64}"})
    assert response.status_code == 400
    assert module.entitlements.payment_state(package_id=SLUG, payment_ref=PAYMENT_REF) == "MISSING"


def test_webhook_replay_cannot_resurrect_revoked_payment(gateway):
    module = gateway
    client = TestClient(module.app)
    assert post_event(client, "evt_BeforeRevoke123").status_code == 200
    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref=PAYMENT_REF) == 1
    replay_new_event = post_event(client, "evt_AfterRevoke123")
    assert replay_new_event.status_code == 200
    assert replay_new_event.json()["ignored_terminal"] is True
    assert not module.entitlements.authorize_payment(package_id=SLUG, payment_ref=PAYMENT_REF)


def test_browser_handoff_remains_post_only_and_one_time_after_webhook(gateway):
    module = gateway
    client = TestClient(module.app)
    assert post_event(client, "evt_Handoff123").status_code == 200
    redirect = client.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    landing = client.get(redirect.headers["location"])
    match = re.search(r'action="([^"]*checkout/activate/[^"]+)"', landing.text)
    assert match
    activate = match.group(1).replace("&amp;", "&")
    assert client.get(activate, follow_redirects=False).status_code == 405
    assert client.post(activate, follow_redirects=False).status_code == 303
    assert client.post(activate, follow_redirects=False).status_code == 409
