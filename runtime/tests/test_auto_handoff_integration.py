from __future__ import annotations

import importlib
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
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", COOKIE_SECRET)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_auto")
    for name in ["commercial", "app", "entitlements", "cost_router"]:
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
    return module, TestClient(module.app)


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


def test_signed_cookie_authority_is_revoked_by_database_immediately(gateway):
    module, client = gateway
    module.entitlements.issue(package_id=SLUG, payment_ref="pi_COOKIE", buyer_ref="buyer")
    cookie = module.sign_entitlement_cookie(
        secret=COOKIE_SECRET,
        package_id=SLUG,
        payment_ref="pi_COOKIE",
    )
    client.cookies.set(module.entitlement_cookie_name(SLUG), cookie)

    assert client.get(f"/apps/{SLUG}/public-config").status_code == 200
    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref="pi_COOKIE") == 1
    assert client.get(f"/apps/{SLUG}/public-config").status_code == 401


def test_checkout_handoff_can_be_claimed_once_and_cannot_replay_after_revoke(gateway, monkeypatch):
    module, client = gateway
    monkeypatch.setattr(module, "retrieve_checkout_session", lambda **kwargs: fake_session())
    monkeypatch.setattr(module, "retrieve_payment_link", lambda **kwargs: fake_payment_link())

    first = client.get(
        f"/checkout/complete/{SLUG}?session_id={SESSION_ID}",
        follow_redirects=False,
    )
    assert first.status_code == 303
    assert first.headers["location"] == f"/a/{SLUG}"
    set_cookie = first.headers.get("set-cookie", "")
    assert module.entitlement_cookie_name(SLUG) in set_cookie
    assert "HttpOnly" in set_cookie
    assert client.get(f"/apps/{SLUG}/public-config").status_code == 200

    second_client = TestClient(module.app)
    duplicate = second_client.get(
        f"/checkout/complete/{SLUG}?session_id={SESSION_ID}",
        follow_redirects=False,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "This Checkout Session has already been claimed"
    assert module.entitlement_cookie_name(SLUG) not in duplicate.headers.get("set-cookie", "")
    assert second_client.get(f"/apps/{SLUG}/public-config").status_code == 401
    assert len(module.entitlements.list_for_package(SLUG)) == 1

    assert module.entitlements.revoke_payment(package_id=SLUG, payment_ref=PAYMENT_REF) == 1
    assert client.get(f"/apps/{SLUG}/public-config").status_code == 401

    replay = second_client.get(
        f"/checkout/complete/{SLUG}?session_id={SESSION_ID}",
        follow_redirects=False,
    )
    assert replay.status_code == 403
    rows = module.entitlements.list_for_package(SLUG)
    assert len(rows) == 1
    assert rows[0]["status"] == "revoked"
