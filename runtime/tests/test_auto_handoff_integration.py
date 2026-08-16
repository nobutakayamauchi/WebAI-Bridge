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
PAYMENT_REF = "pi_AUTO123"
SESSION_ID = "cs_test_AUTO123"
PAYMENT_LINK_ID = "plink_AUTO123"
PAYMENT_LINK_URL = "https://buy.stripe.com/auto-test"


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", COOKIE_SECRET)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_auto")
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
    cfg["readiness"] = {"configuration": "VALIDATED", "runtime": "READY", "commercial": "MANUAL_REVIEW_REQUIRED", "blockers": []}
    return module, TestClient(module.app)


def fake_session():
    return {"id": SESSION_ID, "status": "complete", "payment_status": "paid", "mode": "payment", "payment_link": PAYMENT_LINK_ID, "payment_intent": PAYMENT_REF, "currency": "jpy", "amount_total": 100, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def fake_payment_link():
    return {"id": PAYMENT_LINK_ID, "url": PAYMENT_LINK_URL, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def test_signed_cookie_authority_is_revoked_by_database_immediately(gateway):
    module, client = gateway
    module.entitlements.issue(package_id=SLUG, payment_ref="pi_COOKIE", buyer_ref="buyer")
    cookie = module.sign_entitlement_cookie(secret=COOKIE_SECRET, package_id=SLUG, payment_ref="pi_COOKIE")
    client.cookies.set(module.entitlement_cookie_name(SLUG), cookie)
    assert client.get(f"/apps/{SLUG}/public-config").status_code == 200
    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref="pi_COOKIE") == 1
    assert client.get(f"/apps/{SLUG}/public-config").status_code == 401


def test_checkout_handoff_can_be_claimed_once_and_cannot_replay_after_revoke(gateway, monkeypatch):
    module, payment_browser = gateway
    monkeypatch.setattr(module, "retrieve_checkout_session", lambda **kwargs: fake_session())
    monkeypatch.setattr(module, "retrieve_payment_link", lambda **kwargs: fake_payment_link())
    first = payment_browser.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert first.status_code == 303
    handoff_url = first.headers["location"]
    assert module.entitlement_cookie_name(SLUG) not in first.headers.get("set-cookie", "")
    safari = TestClient(module.app)
    landing = safari.get(handoff_url)
    match = re.search(r'action="([^"]*checkout/activate/[^"]+)"', landing.text)
    assert match is not None
    activate_url = match.group(1).replace("&amp;", "&")
    assert safari.get(activate_url, follow_redirects=False).status_code == 405
    activated = safari.post(activate_url, follow_redirects=False)
    assert activated.status_code == 303
    assert module.entitlement_cookie_name(SLUG) in activated.headers.get("set-cookie", "")
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 200
    assert payment_browser.post(activate_url, follow_redirects=False).status_code == 409
    duplicate_checkout = payment_browser.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert duplicate_checkout.status_code == 409
    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref=PAYMENT_REF) == 1
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 401
    replay = payment_browser.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert replay.status_code == 403
