from __future__ import annotations

import importlib
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

SLUG = "migration-fixture-ai"
PAYMENT_LINK_URL = "https://buy.stripe.com/buyer-only-bound-test"
SESSION_ID = "cs_test_BUYERONLYBOUND"
PAYMENT_LINK_ID = "plink_BUYERONLYBOUND"
PAYMENT_REF = "pi_BUYERONLYBOUND"


def _load_gateway(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_CHECKOUT_STATE_DB", str(tmp_path / "checkout-state.sqlite3"))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", "z" * 48)
    monkeypatch.setenv("WEB_AI_STRIPE_SECRET_KEY", "rk_test_buyer_only_bound")
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "0")
    for name in [
        "commercial_bound", "commercial", "app", "entitlements", "handoff_tickets",
        "checkout_state", "cost_router", "checkout_binding", "checkout_browser_binding",
    ]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial_bound")
    cfg = module.base.core.registry.get(SLUG)
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
        },
    })
    cfg["billing"]["allowed_payer_modes"] = ["BYOK"]
    cfg["billing"]["default_payer_mode"] = "BYOK"
    cfg["billing"].pop("platform_credit", None)
    return module


def _session(client_reference_id: str | None) -> dict:
    return {
        "id": SESSION_ID,
        "status": "complete",
        "payment_status": "paid",
        "mode": "payment",
        "payment_link": PAYMENT_LINK_ID,
        "payment_intent": PAYMENT_REF,
        "currency": "jpy",
        "amount_total": 100,
        "client_reference_id": client_reference_id,
        "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"},
    }


def _payment_link() -> dict:
    return {
        "id": PAYMENT_LINK_ID,
        "url": PAYMENT_LINK_URL,
        "metadata": {"webai_package_id": SLUG, "access_mode": "BUY_ONCE"},
    }


def test_buyer_only_surface_starts_checkout_with_browser_binding(tmp_path: Path, monkeypatch) -> None:
    gateway = _load_gateway(tmp_path, monkeypatch)
    client = TestClient(gateway.app)

    started = client.get(f"/api/buy/{SLUG}", follow_redirects=False)
    assert started.status_code == 303
    reference = (parse_qs(urlsplit(started.headers["location"]).query).get("client_reference_id") or [None])[0]
    assert isinstance(reference, str) and reference.startswith("wb_")
    assert "webai_checkout_" + SLUG in started.headers.get("set-cookie", "")

    monkeypatch.setattr(gateway.base, "retrieve_checkout_session", lambda **_kwargs: _session(reference))
    monkeypatch.setattr(gateway.base, "retrieve_payment_link", lambda **_kwargs: _payment_link())
    completed = client.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert completed.status_code == 200
    assert "handoff_" in completed.text
    assert "?ticket=handoff_" not in completed.text


def test_buyer_only_surface_rejects_valid_session_without_initiating_cookie(tmp_path: Path, monkeypatch) -> None:
    gateway = _load_gateway(tmp_path, monkeypatch)
    monkeypatch.setattr(gateway.base, "retrieve_checkout_session", lambda **_kwargs: _session("wb_public_only"))
    monkeypatch.setattr(gateway.base, "retrieve_payment_link", lambda **_kwargs: _payment_link())

    attacker = TestClient(gateway.app)
    completed = attacker.get(f"/checkout/complete/{SLUG}?session_id={SESSION_ID}", follow_redirects=False)
    assert completed.status_code == 403
    assert gateway.base.entitlements.list_for_package(SLUG) == []
