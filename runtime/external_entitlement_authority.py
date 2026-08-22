from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from entitlements import PAYMENT_ACTIVE, PAYMENT_EXPIRED, PAYMENT_MISSING, PAYMENT_REVOKED


REF_PREFIX = "sdn1"


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def build_external_entitlement_ref(*, package_id: str, order_reference: str) -> str:
    if not package_id or not order_reference:
        raise ValueError("package_id and order_reference are required")
    return f"{REF_PREFIX}.{_b64(package_id)}.{_b64(order_reference)}"


def parse_external_entitlement_ref(reference: str) -> tuple[str, str]:
    try:
        prefix, package_part, order_part = reference.split(".", 2)
    except ValueError as exc:
        raise ValueError("invalid external entitlement reference") from exc
    if prefix != REF_PREFIX:
        raise ValueError("invalid external entitlement reference")
    try:
        package_id = _unb64(package_part)
        order_reference = _unb64(order_part)
    except Exception as exc:  # malformed external identifier, never secret authority
        raise ValueError("invalid external entitlement reference") from exc
    if not package_id or not order_reference:
        raise ValueError("invalid external entitlement reference")
    return package_id, order_reference


@dataclass(frozen=True, slots=True)
class ExternalGrantResult:
    external_entitlement_ref: str
    status: str
    idempotent: bool


class ExternalEntitlementAuthority:
    """Trusted service-to-service paid entitlement bridge.

    The external reference is a durable identifier, not buyer access authority.
    Browser access still requires WebAI's existing entitlement-cookie/handoff path.
    """

    def __init__(self, *, entitlement_store, package_resolver, package_validator) -> None:
        self._entitlements = entitlement_store
        self._resolve_package = package_resolver
        self._validate_package = package_validator

    def grant(self, *, package_id: str, buyer_reference: str, order_reference: str) -> ExternalGrantResult:
        app_config = self._resolve_package(package_id)
        self._validate_package(app_config)
        access = app_config.get("access") or {}
        if access.get("mode") != "BUY_ONCE":
            raise ValueError("external entitlement v1 requires BUY_ONCE package access")

        external_ref = build_external_entitlement_ref(
            package_id=package_id,
            order_reference=order_reference,
        )
        state = self._entitlements.payment_state(
            package_id=package_id,
            payment_ref=external_ref,
        )
        if state == PAYMENT_ACTIVE:
            return ExternalGrantResult(external_ref, PAYMENT_ACTIVE, True)
        if state in {PAYMENT_REVOKED, PAYMENT_EXPIRED}:
            raise ValueError("external entitlement cannot be resurrected")
        if state != PAYMENT_MISSING:
            raise ValueError("unsupported entitlement state")

        # The returned legacy bearer token is intentionally discarded. External
        # callers receive only a non-secret durable reference; WebAI remains the
        # authority that later creates browser access through its own handoff.
        self._entitlements.issue(
            package_id=package_id,
            buyer_ref=buyer_reference,
            payment_ref=external_ref,
        )
        return ExternalGrantResult(external_ref, PAYMENT_ACTIVE, False)

    def revoke(self, *, external_entitlement_ref: str, reason: str) -> ExternalGrantResult:
        if not reason.strip():
            raise ValueError("revoke reason is required")
        package_id, _order_reference = parse_external_entitlement_ref(external_entitlement_ref)
        state = self._entitlements.payment_state(
            package_id=package_id,
            payment_ref=external_entitlement_ref,
        )
        if state == PAYMENT_MISSING:
            raise KeyError(external_entitlement_ref)
        if state == PAYMENT_REVOKED:
            return ExternalGrantResult(external_entitlement_ref, PAYMENT_REVOKED, True)
        if state == PAYMENT_EXPIRED:
            return ExternalGrantResult(external_entitlement_ref, PAYMENT_EXPIRED, True)
        if state != PAYMENT_ACTIVE:
            raise ValueError("unsupported entitlement state")
        self._entitlements.revoke_payment(
            package_id=package_id,
            payment_ref=external_entitlement_ref,
        )
        return ExternalGrantResult(external_entitlement_ref, PAYMENT_REVOKED, False)


class ExternalGrantBody(BaseModel):
    package_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    buyer_reference: str = Field(min_length=1, max_length=500)
    order_reference: str = Field(min_length=1, max_length=500)


class ExternalRevokeBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


def install_external_entitlement_routes(base):
    """Install the SDN-facing authority on a canonical commercial surface."""

    service_token = os.getenv("WEB_AI_EXTERNAL_ENTITLEMENT_SERVICE_TOKEN", "")
    authority = ExternalEntitlementAuthority(
        entitlement_store=base.entitlements,
        package_resolver=base.core.registry.get,
        package_validator=base.ensure_commercial_hosted_runnable,
    )

    def require_service(authorization: str | None) -> None:
        if len(service_token) < 32:
            raise HTTPException(status_code=503, detail="external entitlement authority is not configured")
        expected = f"Bearer {service_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="service authorization required")

    @base.app.post("/api/internal/entitlements/grant")
    def external_grant(body: ExternalGrantBody, authorization: str | None = Header(default=None)) -> dict:
        require_service(authorization)
        try:
            result = authority.grant(
                package_id=body.package_id,
                buyer_reference=body.buyer_reference,
                order_reference=body.order_reference,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown package") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "external_entitlement_ref": result.external_entitlement_ref,
            "status": result.status,
            "idempotent": result.idempotent,
        }

    @base.app.post("/api/internal/entitlements/{external_entitlement_ref}/revoke")
    def external_revoke(
        external_entitlement_ref: str,
        body: ExternalRevokeBody,
        authorization: str | None = Header(default=None),
    ) -> dict:
        require_service(authorization)
        try:
            result = authority.revoke(
                external_entitlement_ref=external_entitlement_ref,
                reason=body.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown external entitlement") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "external_entitlement_ref": result.external_entitlement_ref,
            "status": result.status,
            "idempotent": result.idempotent,
        }

    return authority
