import time

from entitlements import EntitlementStore


def test_payment_reference_authority_tracks_issue_expiry_and_revoke(tmp_path):
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    store.issue(package_id="paid-a", payment_ref="pi_123", buyer_ref="buyer")
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_123") is True
    assert store.authorize_payment(package_id="paid-b", payment_ref="pi_123") is False
    assert store.revoke_payment(package_id="paid-a", payment_ref="pi_123") == 1
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_123") is False


def test_payment_reference_respects_entitlement_expiry(tmp_path):
    store = EntitlementStore(tmp_path / "entitlements.sqlite3")
    store.issue(package_id="paid-a", payment_ref="pi_exp", expires_at=int(time.time()) + 60)
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_exp") is True
    assert store.authorize_payment(package_id="paid-a", payment_ref="pi_exp", now=int(time.time()) + 120) is False
