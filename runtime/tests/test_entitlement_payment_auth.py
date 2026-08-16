import time

from entitlements import (
    EntitlementStore,
    PAYMENT_ACTIVE,
    PAYMENT_EXPIRED,
    PAYMENT_MISSING,
    PAYMENT_REVOKED,
)


def test_payment_reference_authority_tracks_issue_expiry_and_revoke(tmp_path):
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    assert store.payment_state(package_id="paid-a", payment_ref="pi_123") == PAYMENT_MISSING
    store.issue(package_id="paid-a", payment_ref="pi_123", buyer_ref="buyer")
    assert store.payment_state(package_id="paid-a", payment_ref="pi_123") == PAYMENT_ACTIVE
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_123") is True
    assert store.authorize_payment(package_id="paid-b", payment_ref="pi_123") is False
    assert store.revoke_payment(package_id="paid-a", payment_ref="pi_123") == 1
    assert store.payment_state(package_id="paid-a", payment_ref="pi_123") == PAYMENT_REVOKED
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_123") is False


def test_payment_reference_respects_entitlement_expiry_without_becoming_missing(tmp_path):
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    now = int(time.time())
    store.issue(package_id="paid-a", payment_ref="pi_exp", expires_at=now + 60)
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_exp") is True
    assert store.payment_state(package_id="paid-a", payment_ref="pi_exp", now=now + 120) == PAYMENT_EXPIRED
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_exp", now=now + 120) is False
