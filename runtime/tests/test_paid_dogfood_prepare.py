from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from paid_dogfood_prepare import DOGFOOD_SLUG, prepare_paid_dogfood


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_prepare_installs_and_activates_paid_package_outside_repo(tmp_path):
    config_dir = tmp_path / "private-state" / "apps"
    result = prepare_paid_dogfood(
        config_dir=config_dir,
        payment_link_url="https://buy.stripe.com/dogfood-test",
        price_jpy=100,
    )
    assert result["status"] == "READY"
    assert result["package_id"] == DOGFOOD_SLUG
    assert result["reused"] is False
    assert result["active"] is True
    assert result["entitlement_issuance_by_preparer"] == "NONE"
    assert "entitlement_issued" not in result
    assert result["secrets_in_output"] is False
    assert mode(config_dir) & 0o077 == 0

    package_path = config_dir / f"{DOGFOOD_SLUG}.json"
    instructions_path = config_dir / f"{DOGFOOD_SLUG}.instructions.md"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["status"] == "active"
    assert package["access"]["mode"] == "BUY_ONCE"
    assert package["access"]["price_amount_minor"] == 100
    assert package["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert package["access"]["checkout"]["payment_link_url"] == "https://buy.stripe.com/dogfood-test"
    assert package["access"]["checkout"]["binding_verification"] == "CREATOR_ATTESTED"
    assert package["billing"]["allowed_payer_modes"] == ["BYOK"]
    assert package["billing"]["default_payer_mode"] == "BYOK"
    assert "platform_credit" not in package["billing"]
    assert package["delivery"]["mode"] == "HOSTED_ONLY"
    assert package["readiness"]["runtime"] == "READY"
    assert package["readiness"]["blockers"] == []
    assert mode(package_path) & 0o077 == 0
    assert mode(instructions_path) & 0o077 == 0


def test_prepare_is_idempotent_only_for_identical_authority(tmp_path):
    config_dir = tmp_path / "state" / "apps"
    first = prepare_paid_dogfood(
        config_dir=config_dir,
        payment_link_url="https://buy.stripe.com/same",
        price_jpy=100,
    )
    second = prepare_paid_dogfood(
        config_dir=config_dir,
        payment_link_url="https://buy.stripe.com/same",
        price_jpy=100,
    )
    assert first["reused"] is False
    assert second["reused"] is True
    assert second["entitlement_issuance_by_preparer"] == "NONE"

    with pytest.raises(RuntimeError, match="does not match requested authority"):
        prepare_paid_dogfood(
            config_dir=config_dir,
            payment_link_url="https://buy.stripe.com/different",
            price_jpy=100,
        )

    with pytest.raises(RuntimeError, match="does not match requested authority"):
        prepare_paid_dogfood(
            config_dir=config_dir,
            payment_link_url="https://buy.stripe.com/same",
            price_jpy=200,
        )


def test_prepare_rejects_repo_local_config_and_non_https_link(tmp_path):
    with pytest.raises(ValueError, match="outside the Git repository"):
        prepare_paid_dogfood(
            config_dir=RUNTIME_DIR / ".paid-dogfood-test",
            payment_link_url="https://buy.stripe.com/test",
            price_jpy=100,
        )

    with pytest.raises(ValueError, match="HTTPS"):
        prepare_paid_dogfood(
            config_dir=tmp_path / "apps",
            payment_link_url="http://example.com/not-safe",
            price_jpy=100,
        )
