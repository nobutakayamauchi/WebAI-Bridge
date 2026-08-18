from __future__ import annotations

import html
import importlib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

COOKIE_SECRET = "h" * 48
SLUG = "migration-fixture-ai"
PAYMENT_REF = "pi_HANDOFF123"
SESSION_ID = "cs_test_HANDOFF123"
PAYMENT_LINK_ID = "plink_HANDOFF123"
PAYMENT_LINK_URL = "https://buy.stripe.com/handoff-test"


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_TTL_SECONDS", "600")
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", COOKIE_SECRET)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_handoff")
    for name in ["commercial_handoff", "commercial", "app", "entitlements", "handoff_tickets", "cost_router"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial_handoff")
    cfg = module.base.core.registry.get(SLUG)
    cfg["status"] = "active"
    cfg["access"].update({"mode": "BUY_ONCE", "charge_basis": "ONE_TIME", "currency": "JPY", "price_amount_minor": 100, "commercial_enforcement": "ENTITLEMENT_ENFORCED", "checkout": {"provider": "STRIPE_PAYMENT_LINK", "setup_mode": "SELF_SETUP", "payment_link_url": PAYMENT_LINK_URL, "binding_verification": "CREATOR_ATTESTED", "fulfillment": "MANUAL_HANDOFF", "entitlement_verification": "NOT_IMPLEMENTED"}})
    cfg["billing"]["allowed_payer_modes"] = ["BYOK"]
    cfg["billing"]["default_payer_mode"] = "BYOK"
    cfg["billing"].pop("platform_credit", None)
    return module


def fake_session():
    return {"id": SESSION_ID, "status": "complete", "payment_status": "paid", "mode": "payment", "payment_link": PAYMENT_LINK_ID, "payment_intent": PAYMENT_REF, "currency": "jpy", "amount_total": 100, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def fake_payment_link():
    return {"id": PAYMENT_LINK_ID, "url": PAYMENT_LINK_URL, "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"}}


def _extract_transfer_code(page: str) -> str:
    match = re.search(r"<code>(handoff_[^<]+)</code>", page)
    assert match is not None
    return html.unescape(match.group(1))


def test_checkout_can_transfer_once_from_embedded_browser_to_safari_without_authority_in_url(gateway, monkeypatch):
    module = gateway
    monkeypatch.setattr(module.base, "retrieve_checkout_session", lambda **kwargs: fake_session())
    monkeypatch.setattr(module.base, "retrieve_payment_link", lambda **kwargs: fake_payment_link())
    embedded = TestClient(module.app)
    safari = TestClient(module.app)

    completed = embedded.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert completed.status_code == 200
    assert "history.replaceState" in completed.text
    assert f"/checkout/handoff/{SLUG}?ticket=" not in completed.text
    transfer_code = _extract_transfer_code(completed.text)

    clean_handoff_url = f"/checkout/handoff/{SLUG}"
    landing = safari.get(clean_handoff_url)
    assert landing.status_code == 200
    assert transfer_code not in landing.text
    activate_url = f"/checkout/activate/{SLUG}"
    assert safari.get(activate_url, follow_redirects=False).status_code == 405

    activated = safari.post(activate_url, data={"ticket": transfer_code}, follow_redirects=False)
    assert activated.status_code == 303
    assert module.base.entitlement_cookie_name(SLUG) in activated.headers.get("set-cookie", "")
    assert "ticket=" not in activated.headers.get("location", "")
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 200

    assert embedded.post(activate_url, data={"ticket": transfer_code}, follow_redirects=False).status_code == 409
    assert embedded.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False).status_code == 409
    assert module.base.entitlements.revoke_payment(package_id=SLUG, payment_ref=PAYMENT_REF) == 1
    assert safari.get(f"/apps/{SLUG}/public-config").status_code == 401


def test_missing_checkout_session_id_is_fail_closed_human_readable_html(gateway):
    module = gateway
    response = TestClient(module.app).get(f"/checkout/complete/{SLUG}")
    assert response.status_code == 400
    assert "購入情報を確認できません" in response.text
    assert response.headers["content-type"].startswith("text/html")
    assert "Field required" not in response.text
