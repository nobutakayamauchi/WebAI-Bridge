from __future__ import annotations

from stripe_external_acceptance import (
    expected_completion_url,
    expected_webhook_url,
    validate_payment_link_external_contract,
    validate_webhook_external_contract,
)


def _package() -> dict:
    return {
        "slug": "second-product-acceptance-ai",
        "status": "active",
        "access": {
            "mode": "BUY_ONCE",
            "currency": "JPY",
            "price_amount_minor": 500,
            "checkout": {
                "payment_link_url": "https://buy.stripe.com/test-link",
            },
        },
    }


def _payment_link() -> dict:
    package = _package()
    return {
        "id": "plink_123456789",
        "url": package["access"]["checkout"]["payment_link_url"],
        "active": True,
        "livemode": True,
        "metadata": {
            "webai_package_id": package["slug"],
            "access_mode": "BUY_ONCE",
        },
        "after_completion": {
            "type": "redirect",
            "redirect": {
                "url": expected_completion_url(domain="ai.example.com", slug=package["slug"]),
            },
        },
    }


def _line_items() -> list[dict]:
    return [
        {
            "quantity": 1,
            "price": {
                "currency": "jpy",
                "unit_amount": 500,
                "type": "one_time",
            },
        }
    ]


def test_live_payment_link_contract_passes_when_metadata_amount_and_redirect_match() -> None:
    findings = validate_payment_link_external_contract(
        payment_link=_payment_link(),
        line_items=_line_items(),
        app_config=_package(),
        domain="ai.example.com",
        require_live=True,
    )

    assert findings == []


def test_live_payment_link_contract_catches_metadata_redirect_and_amount_drift() -> None:
    payment_link = _payment_link()
    payment_link["metadata"] = {"webai_slug": "second-product-acceptance-ai"}
    payment_link["after_completion"] = {"type": "hosted_confirmation"}
    line_items = _line_items()
    line_items[0]["price"]["unit_amount"] = 100

    findings = validate_payment_link_external_contract(
        payment_link=payment_link,
        line_items=line_items,
        app_config=_package(),
        domain="ai.example.com",
        require_live=True,
    )

    assert any(item.startswith("PAYMENT_LINK_BINDING:") for item in findings)
    assert "PAYMENT_LINK_REDIRECT_MISMATCH" in findings
    assert "PAYMENT_LINK_AMOUNT_MISMATCH" in findings


def test_fixed_domain_webhook_contract_requires_exact_enabled_destination_and_events() -> None:
    endpoint = {
        "url": expected_webhook_url(domain="ai.example.com"),
        "status": "enabled",
        "livemode": True,
        "enabled_events": [
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        ],
    }

    assert validate_webhook_external_contract(
        endpoints=[endpoint],
        domain="ai.example.com",
        require_live=True,
    ) == []


def test_stale_quick_tunnel_webhook_does_not_satisfy_fixed_domain_acceptance() -> None:
    endpoint = {
        "url": "https://retired.trycloudflare.com/webhooks/stripe",
        "status": "enabled",
        "livemode": True,
        "enabled_events": [
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        ],
    }

    assert validate_webhook_external_contract(
        endpoints=[endpoint],
        domain="ai.example.com",
        require_live=True,
    ) == ["FIXED_DOMAIN_WEBHOOK_ENDPOINT_MISSING"]


def test_fixed_domain_webhook_requires_both_fulfillment_events() -> None:
    endpoint = {
        "url": expected_webhook_url(domain="ai.example.com"),
        "status": "enabled",
        "livemode": True,
        "enabled_events": ["checkout.session.completed"],
    }

    assert validate_webhook_external_contract(
        endpoints=[endpoint],
        domain="ai.example.com",
        require_live=True,
    ) == ["FIXED_DOMAIN_WEBHOOK_EVENTS_INCOMPLETE"]
