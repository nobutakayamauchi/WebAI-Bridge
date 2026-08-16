from __future__ import annotations

from copy import deepcopy


STALE_WARNING = "Commercial access enforcement is not implemented in thin v0; this is pricing intent only."
MANUAL_WARNING = (
    "Manual paid-hosted entitlement is available after explicit operator activation. "
    "Studio export remains draft; each buyer still requires manual payment verification and bearer-token issuance."
)


def adapt_manual_hosted_entitlement(result: dict) -> dict:
    """Upgrade readiness claims only for the narrow commercial v0 shape.

    The canonical Studio still emits a draft with commercial_enforcement=NOT_IMPLEMENTED.
    This adapter does not silently activate anything. It only states that a supported
    operator activation path now exists for BUY_ONCE/SUBSCRIPTION + Hosted + BYOK-only.
    """
    adapted = deepcopy(result)
    package = adapted.get("package") or {}
    access = package.get("access") or {}
    delivery = package.get("delivery") or {}
    billing = package.get("billing") or {}
    readiness = deepcopy(adapted.get("readiness") or package.get("readiness") or {})

    candidate = (
        access.get("mode") in {"BUY_ONCE", "SUBSCRIPTION"}
        and delivery.get("mode") == "HOSTED_ONLY"
        and delivery.get("runtime_implementation") == "AVAILABLE"
        and billing.get("allowed_payer_modes") == ["BYOK"]
        and billing.get("default_payer_mode") == "BYOK"
    )
    if not candidate:
        return adapted

    blockers = [
        item for item in readiness.get("blockers", [])
        if item != "HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"
    ]
    readiness["runtime"] = "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION"
    readiness["commercial"] = "BLOCKED" if blockers else "MANUAL_REVIEW_REQUIRED"
    readiness["blockers"] = blockers
    package["readiness"] = readiness
    adapted["package"] = package
    adapted["readiness"] = readiness
    adapted["ready_to_run"] = False
    adapted["ready_to_sell"] = False

    warnings = [w for w in adapted.get("warnings", []) if w != STALE_WARNING]
    if MANUAL_WARNING not in warnings:
        warnings.append(MANUAL_WARNING)
    adapted["warnings"] = warnings
    return adapted
