from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RUNTIME_DIR.parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import entitlement_cli


def assisted_paid_package() -> dict:
    data = json.loads((REPO_DIR / "package-schema" / "package.example.json").read_text(encoding="utf-8"))
    data["status"] = "draft"
    data["access"].update({
        "mode": "BUY_ONCE",
        "charge_basis": "ONE_TIME",
        "currency": "JPY",
        "price_amount_minor": 1500,
        "included_runs": 0,
        "commercial_enforcement": "NOT_IMPLEMENTED",
        "checkout": {
            "provider": "STRIPE_PAYMENT_LINK",
            "setup_mode": "ASSISTED_SETUP",
            "payment_link_url": "https://buy.stripe.com/example",
            "binding_verification": "MANUAL_REVIEW_REQUIRED",
            "fulfillment": "MANUAL_HANDOFF",
            "entitlement_verification": "NOT_IMPLEMENTED",
        },
    })
    data["billing"] = {
        "allowed_payer_modes": ["BYOK"],
        "default_payer_mode": "BYOK",
        "byok_transport": "SERVER_PROXY_EPHEMERAL",
    }
    data["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": [],
    }
    return data


def test_assisted_checkout_cannot_activate_before_explicit_operator_review(tmp_path):
    path = tmp_path / "assisted.json"
    path.write_text(json.dumps(assisted_paid_package()), encoding="utf-8")

    with pytest.raises(SystemExit, match="checkout-reviewed"):
        entitlement_cli.cmd_activate_config(SimpleNamespace(config=str(path), checkout_reviewed=False))

    unchanged = json.loads(path.read_text(encoding="utf-8"))
    assert unchanged["status"] == "draft"
    assert unchanged["access"]["checkout"]["binding_verification"] == "MANUAL_REVIEW_REQUIRED"


def test_assisted_checkout_review_becomes_machine_readable_operator_review(tmp_path):
    path = tmp_path / "assisted.json"
    path.write_text(json.dumps(assisted_paid_package()), encoding="utf-8")

    assert entitlement_cli.cmd_activate_config(SimpleNamespace(config=str(path), checkout_reviewed=True)) == 0
    activated = json.loads(path.read_text(encoding="utf-8"))
    assert activated["status"] == "active"
    assert activated["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert activated["access"]["checkout"]["binding_verification"] == "OPERATOR_REVIEWED"
