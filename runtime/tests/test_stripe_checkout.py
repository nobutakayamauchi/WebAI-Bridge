import pytest

from stripe_checkout import (
    StripeCheckoutError,
    validate_paid_checkout_session,
    validate_payment_link_binding,
)


def app_config():
    return {
        "slug": "paid-dogfood-ai",
        "access": {
            "mode": "BUY_ONCE",
            "currency": "JPY",
            "price_amount_minor": 100,
            "checkout": {"payment_link_url": "https://buy.stripe.com/dogfood"},
        },
    }


def paid_session():
    return {
        "id": "cs_live_ABC123",
        "status": "complete",
        "payment_status": "paid",
        "mode": "payment",
        "payment_link": "plink_123",
        "payment_intent": "pi_123",
        "currency": "jpy",
        "amount_total": 100,
        "metadata": {"webai_package_id": "paid-dogfood-ai", "access_mode": "BUY_ONCE"},
    }


def payment_link():
    return {
        "id": "plink_123",
        "url": "https://buy.stripe.com/dogfood",
        "metadata": {"webai_package_id": "paid-dogfood-ai", "access_mode": "BUY_ONCE"},
    }


def test_valid_checkout_is_bound_to_package_amount_currency_payment_ref_and_link_id():
    verified = validate_paid_checkout_session(session=paid_session(), app_config=app_config())
    assert verified["package_id"] == "paid-dogfood-ai"
    assert verified["payment_ref"] == "pi_123"
    assert verified["payment_link_id"] == "plink_123"
    assert verified["buyer_ref"] == "stripe-checkout:cs_live_ABC123"


def test_payment_link_must_match_exact_configured_url_and_metadata():
    validate_payment_link_binding(payment_link=payment_link(), app_config=app_config())

    wrong_url = payment_link()
    wrong_url["url"] = "https://buy.stripe.com/other"
    with pytest.raises(StripeCheckoutError, match="URL binding mismatch"):
        validate_payment_link_binding(payment_link=wrong_url, app_config=app_config())

    wrong_meta = payment_link()
    wrong_meta["metadata"]["webai_package_id"] = "other"
    with pytest.raises(StripeCheckoutError, match="metadata binding mismatch"):
        validate_payment_link_binding(payment_link=wrong_meta, app_config=app_config())


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda s: s.update(payment_status="unpaid"), "not fully paid"),
        (lambda s: s["metadata"].update(webai_package_id="other"), "package binding mismatch"),
        (lambda s: s.update(amount_total=101), "amount mismatch"),
        (lambda s: s.update(currency="usd"), "currency mismatch"),
        (lambda s: s.update(payment_link=None), "not bound to a valid Payment Link"),
        (lambda s: s.update(payment_intent=None), "no usable PaymentIntent"),
    ],
)
def test_checkout_validation_fails_closed(mutation, message):
    session = paid_session()
    mutation(session)
    with pytest.raises(StripeCheckoutError, match=message):
        validate_paid_checkout_session(session=session, app_config=app_config())


def test_non_buy_once_is_not_silently_accepted():
    config = app_config()
    config["access"]["mode"] = "SUBSCRIPTION"
    with pytest.raises(StripeCheckoutError, match="BUY_ONCE only"):
        validate_paid_checkout_session(session=paid_session(), app_config=config)
