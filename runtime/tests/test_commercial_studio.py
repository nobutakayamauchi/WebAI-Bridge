from __future__ import annotations

import copy
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from commercial_studio import MANUAL_WARNING, adapt_manual_hosted_entitlement


def base_result():
    package = {
        "access": {
            "mode": "BUY_ONCE",
            "commercial_enforcement": "NOT_IMPLEMENTED",
        },
        "billing": {
            "allowed_payer_modes": ["BYOK"],
            "default_payer_mode": "BYOK",
        },
        "delivery": {
            "mode": "HOSTED_ONLY",
            "runtime_implementation": "AVAILABLE",
        },
        "readiness": {
            "configuration": "VALIDATED",
            "runtime": "BLOCKED_PAID_HOSTED_ENTITLEMENT_NOT_IMPLEMENTED",
            "commercial": "BLOCKED",
            "blockers": ["HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"],
        },
    }
    return {
        "valid": True,
        "ready_to_run": False,
        "ready_to_sell": False,
        "readiness": copy.deepcopy(package["readiness"]),
        "package": package,
        "warnings": [
            "Commercial access enforcement is not implemented in thin v0; this is pricing intent only."
        ],
    }


def test_buy_once_hosted_byok_becomes_manual_activation_candidate_without_silent_activation():
    original = base_result()
    adapted = adapt_manual_hosted_entitlement(original)

    assert adapted is not original
    assert original["readiness"]["runtime"] == "BLOCKED_PAID_HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"
    assert adapted["readiness"]["runtime"] == "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION"
    assert adapted["readiness"]["commercial"] == "MANUAL_REVIEW_REQUIRED"
    assert adapted["readiness"]["blockers"] == []
    assert adapted["package"]["access"]["commercial_enforcement"] == "NOT_IMPLEMENTED"
    assert adapted["ready_to_run"] is False
    assert adapted["ready_to_sell"] is False
    assert MANUAL_WARNING in adapted["warnings"]


def test_subscription_hosted_byok_is_also_manual_activation_candidate():
    result = base_result()
    result["package"]["access"]["mode"] = "SUBSCRIPTION"
    adapted = adapt_manual_hosted_entitlement(result)
    assert adapted["readiness"]["runtime"] == "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION"
    assert "HOSTED_ENTITLEMENT_NOT_IMPLEMENTED" not in adapted["readiness"]["blockers"]


def test_platform_credit_candidate_is_not_upgraded():
    result = base_result()
    result["package"]["billing"]["allowed_payer_modes"] = ["BYOK", "PLATFORM_CREDIT"]
    adapted = adapt_manual_hosted_entitlement(result)
    assert adapted == result


def test_portable_candidate_is_not_upgraded():
    result = base_result()
    result["package"]["delivery"] = {
        "mode": "PORTABLE_LICENSE",
        "runtime_implementation": "NOT_IMPLEMENTED",
    }
    adapted = adapt_manual_hosted_entitlement(result)
    assert adapted == result


def test_other_blockers_survive_manual_entitlement_upgrade():
    result = base_result()
    result["readiness"]["blockers"].append("CHECKOUT_SETUP_PENDING")
    result["package"]["readiness"]["blockers"].append("CHECKOUT_SETUP_PENDING")
    adapted = adapt_manual_hosted_entitlement(result)
    assert adapted["readiness"]["blockers"] == ["CHECKOUT_SETUP_PENDING"]
    assert adapted["readiness"]["commercial"] == "BLOCKED"
