from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from entitlements import EntitlementStore, PAYMENT_ACTIVE, PAYMENT_REVOKED
from external_entitlement_authority import (
    ExternalEntitlementAuthority,
    build_external_entitlement_ref,
    install_external_entitlement_routes,
    parse_external_entitlement_ref,
)


def _active_package(slug: str) -> dict:
    return {
        "slug": slug,
        "status": "active",
        "access": {
            "mode": "BUY_ONCE",
            "commercial_enforcement": "ENTITLEMENT_ENFORCED",
        },
        "delivery": {"mode": "HOSTED_ONLY", "runtime_implementation": "AVAILABLE"},
        "billing": {"allowed_payer_modes": ["BYOK"], "default_payer_mode": "BYOK"},
    }


def test_external_reference_round_trip():
    ref = build_external_entitlement_ref(package_id="paid-ai", order_reference="order/123:abc")
    assert parse_external_entitlement_ref(ref) == ("paid-ai", "order/123:abc")
    assert "order/123:abc" not in ref


def test_grant_is_idempotent_and_revoke_is_terminal(tmp_path):
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    package = _active_package("paid-ai")
    authority = ExternalEntitlementAuthority(
        entitlement_store=store,
        package_resolver=lambda slug: package if slug == "paid-ai" else (_ for _ in ()).throw(KeyError(slug)),
        package_validator=lambda config: None,
    )

    first = authority.grant(
        package_id="paid-ai",
        buyer_reference="buyer-1",
        order_reference="order-1",
    )
    assert first.status == PAYMENT_ACTIVE
    assert first.idempotent is False
    assert store.authorize_payment(package_id="paid-ai", payment_ref=first.external_entitlement_ref)

    second = authority.grant(
        package_id="paid-ai",
        buyer_reference="buyer-1",
        order_reference="order-1",
    )
    assert second.external_entitlement_ref == first.external_entitlement_ref
    assert second.idempotent is True

    revoked = authority.revoke(
        external_entitlement_ref=first.external_entitlement_ref,
        reason="refund",
    )
    assert revoked.status == PAYMENT_REVOKED
    assert revoked.idempotent is False
    assert not store.authorize_payment(package_id="paid-ai", payment_ref=first.external_entitlement_ref)

    replay = authority.revoke(
        external_entitlement_ref=first.external_entitlement_ref,
        reason="refund replay",
    )
    assert replay.status == PAYMENT_REVOKED
    assert replay.idempotent is True

    try:
        authority.grant(
            package_id="paid-ai",
            buyer_reference="buyer-1",
            order_reference="order-1",
        )
    except ValueError as exc:
        assert "cannot be resurrected" in str(exc)
    else:
        raise AssertionError("revoked external entitlement must never be resurrected")


def test_http_routes_fail_closed_and_require_service_bearer(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AI_EXTERNAL_ENTITLEMENT_SERVICE_TOKEN", "s" * 48)
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    package = _active_package("paid-ai")

    class Registry:
        def get(self, slug: str):
            if slug != "paid-ai":
                raise KeyError(slug)
            return package

    base = SimpleNamespace(
        app=FastAPI(),
        entitlements=store,
        core=SimpleNamespace(registry=Registry()),
        ensure_commercial_hosted_runnable=lambda config: None,
    )
    install_external_entitlement_routes(base)
    client = TestClient(base.app)

    denied = client.post(
        "/api/internal/entitlements/grant",
        json={"package_id": "paid-ai", "buyer_reference": "buyer", "order_reference": "order-1"},
    )
    assert denied.status_code == 401

    headers = {"Authorization": f"Bearer {'s' * 48}"}
    granted = client.post(
        "/api/internal/entitlements/grant",
        headers=headers,
        json={"package_id": "paid-ai", "buyer_reference": "buyer", "order_reference": "order-1"},
    )
    assert granted.status_code == 200
    ref = granted.json()["external_entitlement_ref"]
    assert granted.json()["status"] == PAYMENT_ACTIVE

    revoked = client.post(
        f"/api/internal/entitlements/{ref}/revoke",
        headers=headers,
        json={"reason": "refund"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == PAYMENT_REVOKED


def test_http_routes_are_503_when_service_authority_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("WEB_AI_EXTERNAL_ENTITLEMENT_SERVICE_TOKEN", raising=False)
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    base = SimpleNamespace(
        app=FastAPI(),
        entitlements=store,
        core=SimpleNamespace(registry=SimpleNamespace(get=lambda slug: _active_package(slug))),
        ensure_commercial_hosted_runnable=lambda config: None,
    )
    install_external_entitlement_routes(base)
    client = TestClient(base.app)
    response = client.post(
        "/api/internal/entitlements/grant",
        headers={"Authorization": "Bearer anything"},
        json={"package_id": "paid-ai", "buyer_reference": "buyer", "order_reference": "order-1"},
    )
    assert response.status_code == 503
