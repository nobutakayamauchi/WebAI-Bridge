from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from bank_payment_ingress import BankOrderStore, BankPaymentIngress
from payment_adapter import BankTransactionClaimStore

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

SLUG = "migration-fixture-ai"


def _load_gateway(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(tmp_path / "entitlements.sqlite3"))
    monkeypatch.setenv("WEB_AI_HANDOFF_DB", str(tmp_path / "handoff.sqlite3"))
    monkeypatch.setenv("WEB_AI_CHECKOUT_STATE_DB", str(tmp_path / "checkout-state.sqlite3"))
    monkeypatch.setenv("WEB_AI_BANK_ORDER_DB", str(tmp_path / "bank-orders.sqlite3"))
    monkeypatch.setenv("WEB_AI_BANK_CLAIM_DB", str(tmp_path / "bank-claims.sqlite3"))
    monkeypatch.setenv("WEB_AI_BANK_NAME", "MUFG")
    monkeypatch.setenv("WEB_AI_BANK_BRANCH", "TEST")
    monkeypatch.setenv("WEB_AI_BANK_ACCOUNT_TYPE", "普通")
    monkeypatch.setenv("WEB_AI_BANK_ACCOUNT_NO", "0000000")
    monkeypatch.setenv("WEB_AI_BANK_ACCOUNT_HOLDER", "WEB AI TEST")
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_COOKIE_SECRET", "b" * 48)
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "0")
    for name in [
        "commercial_bound", "commercial", "app", "entitlements", "handoff_tickets",
        "checkout_state", "cost_router", "checkout_binding", "checkout_browser_binding",
        "bank_checkout", "bank_checkout_binding", "bank_payment_ingress", "payment_adapter",
    ]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial_bound")
    cfg = module.base.core.registry.get(SLUG)
    cfg["status"] = "active"
    cfg["access"].update({
        "mode": "BUY_ONCE",
        "charge_basis": "ONE_TIME",
        "currency": "JPY",
        "price_amount_minor": 100000,
        "commercial_enforcement": "ENTITLEMENT_ENFORCED",
    })
    cfg["billing"]["allowed_payer_modes"] = ["BYOK"]
    cfg["billing"]["default_payer_mode"] = "BYOK"
    cfg["billing"].pop("platform_credit", None)
    return module


def test_bank_checkout_to_paid_to_handoff(tmp_path: Path, monkeypatch) -> None:
    gateway = _load_gateway(tmp_path, monkeypatch)
    client = TestClient(gateway.app)

    started = client.post(f"/api/bank/buy/{SLUG}")
    assert started.status_code == 200
    match = re.search(r"照合番号：\s*<code>(\d{8})</code>", started.text)
    assert match
    order_ref = match.group(1)
    assert f"webai_bank_{SLUG}_{order_ref}" in started.headers.get("set-cookie", "")

    orders = BankOrderStore(tmp_path / "bank-orders.sqlite3")
    ingress = BankPaymentIngress(
        orders=orders,
        entitlements=gateway.base.entitlements,
        claims=BankTransactionClaimStore(tmp_path / "bank-claims.sqlite3"),
    )
    fulfilled = ingress.process({
        "provider": "MUFG",
        "transaction_ref": "mufg-live-shaped-001",
        "order_ref": order_ref,
        "amount_minor": 100000,
        "currency": "JPY",
        "status": "SETTLED",
    })
    assert fulfilled.active
    assert orders.get(order_ref).status == "PAID"
    assert orders.get(order_ref).payment_ref == fulfilled.payment_ref

    completed = client.get(f"/bank/checkout/{SLUG}/{order_ref}")
    assert completed.status_code == 200
    assert "購入確認が完了しました" in completed.text
    assert "handoff_" in completed.text


def test_order_ref_alone_cannot_claim_paid_bank_order(tmp_path: Path, monkeypatch) -> None:
    gateway = _load_gateway(tmp_path, monkeypatch)
    buyer = TestClient(gateway.app)
    started = buyer.post(f"/api/bank/buy/{SLUG}")
    order_ref = re.search(r"照合番号：\s*<code>(\d{8})</code>", started.text).group(1)

    orders = BankOrderStore(tmp_path / "bank-orders.sqlite3")
    ingress = BankPaymentIngress(
        orders=orders,
        entitlements=gateway.base.entitlements,
        claims=BankTransactionClaimStore(tmp_path / "bank-claims.sqlite3"),
    )
    ingress.process({
        "provider": "MUFG",
        "transaction_ref": "mufg-live-shaped-002",
        "order_ref": order_ref,
        "amount_minor": 100000,
        "currency": "JPY",
        "status": "SETTLED",
    })

    attacker = TestClient(gateway.app)
    stolen = attacker.get(f"/bank/checkout/{SLUG}/{order_ref}")
    assert stolen.status_code == 403
    assert "handoff_" not in stolen.text
