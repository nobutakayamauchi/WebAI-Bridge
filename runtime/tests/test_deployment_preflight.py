from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RUNTIME_DIR.parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from deployment_preflight import run_preflight


def paid_active_package() -> dict:
    data = json.loads((REPO_DIR / "package-schema" / "package.example.json").read_text(encoding="utf-8"))
    data["status"] = "active"
    data["access"].update({
        "mode": "BUY_ONCE",
        "charge_basis": "ONE_TIME",
        "currency": "JPY",
        "price_amount_minor": 1500,
        "included_runs": 0,
        "commercial_enforcement": "ENTITLEMENT_ENFORCED",
        "checkout": {
            "provider": "STRIPE_PAYMENT_LINK",
            "setup_mode": "SELF_SETUP",
            "payment_link_url": "https://buy.stripe.com/example",
            "binding_verification": "CREATOR_ATTESTED",
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
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": [],
    }
    return data


def good_env(tmp_path: Path) -> dict[str, str]:
    state = tmp_path / "state"
    state.mkdir()
    return {
        "WEB_AI_SERVICE_UNIT": "webai-bridge.service",
        "WEB_AI_WORKING_DIRECTORY": str(RUNTIME_DIR.resolve()),
        "WEB_AI_ROUTE_SURFACE": "commercial:app",
        "DEPLOYED_REVISION": "a" * 40,
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "0",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "WEB_AI_ENTITLEMENT_DB": str((state / "entitlements.sqlite3").resolve()),
        "WEB_AI_LEDGER_PATH": str((state / "ledger.sqlite3").resolve()),
    }


def run_with_package(tmp_path: Path, package: dict, env: dict[str, str] | None = None):
    config = tmp_path / "configs"
    config.mkdir(exist_ok=True)
    os.chmod(config, 0o700)
    package_path = config / "paid.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    os.chmod(package_path, 0o600)
    slug = package.get("slug")
    if slug:
        instructions = config / f"{slug}.instructions.md"
        instructions.write_text("private hosted instructions", encoding="utf-8")
        os.chmod(instructions, 0o600)
    return run_preflight(
        env=env or good_env(tmp_path),
        runtime_dir=RUNTIME_DIR,
        config_dir=config,
        verify_git_revision=False,
    )


def codes(result: dict) -> set[str]:
    return {item["code"] for item in result["findings"]}


def test_preflight_passes_bounded_active_paid_hosted_byok_shape(tmp_path):
    result = run_with_package(tmp_path, paid_active_package())
    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert result["active_packages"] == 1
    assert result["active_paid_packages"] == 1
    assert result["findings"] == []


def test_preflight_requires_deployment_identity_and_secure_public_settings(tmp_path):
    env = good_env(tmp_path)
    env["WEB_AI_SERVICE_UNIT"] = "UNSET"
    env["WEB_AI_WORKING_DIRECTORY"] = "/wrong/path"
    env["WEB_AI_ROUTE_SURFACE"] = "app:app"
    env["DEPLOYED_REVISION"] = "UNSET"
    env["WEB_AI_DIAGNOSTICS_ENABLED"] = "1"
    env["WEB_AI_STUDIO_ENABLED"] = "1"
    env["WEB_AI_ALLOW_INSECURE_HTTP"] = "1"
    result = run_with_package(tmp_path, paid_active_package(), env)
    assert result["ok"] is False
    assert {
        "DEPLOYMENT_SERVICE_UNIT_UNSET",
        "DEPLOYMENT_WORKING_DIRECTORY_MISMATCH",
        "DEPLOYMENT_ROUTE_SURFACE_INVALID",
        "DEPLOYED_REVISION_UNESTABLISHED",
        "PUBLIC_DIAGNOSTICS_ENABLED",
        "PUBLIC_STUDIO_ENABLED",
        "INSECURE_HTTP_OVERRIDE_ENABLED",
    } <= codes(result)


def test_preflight_rejects_runtime_local_or_colliding_state_databases(tmp_path):
    env = good_env(tmp_path)
    same = RUNTIME_DIR / ".runtime" / "shared.sqlite3"
    env["WEB_AI_ENTITLEMENT_DB"] = str(same)
    env["WEB_AI_LEDGER_PATH"] = str(same)
    result = run_with_package(tmp_path, paid_active_package(), env)
    assert "WEB_AI_ENTITLEMENT_DB_INSIDE_RUNTIME" in codes(result)
    assert "WEB_AI_LEDGER_PATH_INSIDE_RUNTIME" in codes(result)
    assert "STATE_DATABASE_PATH_COLLISION" in codes(result)


def test_preflight_rejects_group_or_world_readable_existing_state_file(tmp_path):
    env = good_env(tmp_path)
    db = Path(env["WEB_AI_ENTITLEMENT_DB"])
    db.write_text("test", encoding="utf-8")
    os.chmod(db, 0o644)
    result = run_with_package(tmp_path, paid_active_package(), env)
    assert "WEB_AI_ENTITLEMENT_DB_PERMISSIONS_TOO_OPEN" in codes(result)


def test_preflight_rejects_unreviewed_checkout_and_platform_subsidy(tmp_path):
    package = paid_active_package()
    package["access"]["checkout"]["setup_mode"] = "ASSISTED_SETUP"
    package["access"]["checkout"]["binding_verification"] = "MANUAL_REVIEW_REQUIRED"
    package["billing"]["allowed_payer_modes"] = ["BYOK", "PLATFORM_CREDIT"]
    package["billing"]["platform_credit"] = {
        "enabled": True,
        "budget_id_env": "PAID_BUDGET_ID",
        "hard_limit_usd_micros": 100000,
    }
    result = run_with_package(tmp_path, package)
    assert "ACTIVE_PAID_CHECKOUT_UNVERIFIED" in codes(result)
    assert "ACTIVE_PAID_PAYER_NOT_BYOK_ONLY" in codes(result)
    assert "ACTIVE_PAID_PLATFORM_SUBSIDY_PRESENT" in codes(result)


def test_preflight_accepts_operator_reviewed_assisted_checkout(tmp_path):
    package = paid_active_package()
    package["access"]["checkout"]["setup_mode"] = "ASSISTED_SETUP"
    package["access"]["checkout"]["binding_verification"] = "OPERATOR_REVIEWED"
    result = run_with_package(tmp_path, package)
    assert result["ok"] is True


def test_preflight_rejects_secret_material_embedded_in_package_json_even_when_nested_container(tmp_path):
    package = paid_active_package()
    package["credential"] = {"value": "do-not-store-this"}
    result = run_with_package(tmp_path, package)
    assert "SECRET_MATERIAL_IN_PACKAGE" in codes(result)


def test_preflight_rejects_model_without_pricing_evidence(tmp_path):
    package = paid_active_package()
    package["routing"]["allowed_models"].append("imaginary-unpriced-model")
    result = run_with_package(tmp_path, package)
    assert "MODEL_PRICE_MISSING" in codes(result)


def test_preflight_rejects_active_knowledge_without_server_binding(tmp_path):
    package = paid_active_package()
    package["knowledge"]["enabled"] = True
    package["knowledge"]["vector_store_env"] = "MISSING_VECTOR_STORE_ID"
    result = run_with_package(tmp_path, package)
    assert "ACTIVE_KNOWLEDGE_BINDING_MISSING" in codes(result)


def test_preflight_rejects_active_package_with_stale_blocked_readiness(tmp_path):
    package = paid_active_package()
    package["readiness"]["runtime"] = "BLOCKED"
    package["readiness"]["blockers"] = ["SOMETHING_STALE"]
    result = run_with_package(tmp_path, package)
    assert "ACTIVE_PACKAGE_RUNTIME_NOT_READY" in codes(result)
    assert "ACTIVE_PACKAGE_HAS_BLOCKERS" in codes(result)


def test_preflight_rejects_active_portable_package_on_current_commercial_entrypoint(tmp_path):
    package = paid_active_package()
    package["delivery"]["mode"] = "PORTABLE_LICENSE"
    package["delivery"]["runtime_implementation"] = "NOT_IMPLEMENTED"
    package["delivery"]["protection_level"] = "LEVEL_1_LICENSE_ONLY"
    package["delivery"]["portable_protection"] = "LICENSE_ONLY"
    package["delivery"]["copy_protection_guarantee"] = "NOT_GUARANTEED"
    package["delivery"]["portable_copy_risk_acknowledged"] = True
    result = run_with_package(tmp_path, package)
    assert "ACTIVE_PACKAGE_DELIVERY_UNSUPPORTED" in codes(result)


def test_preflight_rejects_world_writable_config_authority(tmp_path):
    config = tmp_path / "configs"
    config.mkdir()
    os.chmod(config, 0o777)
    package = paid_active_package()
    package_path = config / "paid.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    os.chmod(package_path, 0o600)
    instructions = config / f"{package['slug']}.instructions.md"
    instructions.write_text("private", encoding="utf-8")
    os.chmod(instructions, 0o600)
    result = run_preflight(
        env=good_env(tmp_path),
        runtime_dir=RUNTIME_DIR,
        config_dir=config,
        verify_git_revision=False,
    )
    assert "CONFIG_DIR_WORLD_WRITABLE" in codes(result)


def test_preflight_rejects_open_permissions_on_active_package_and_instructions(tmp_path):
    config = tmp_path / "configs"
    config.mkdir()
    os.chmod(config, 0o700)
    package = paid_active_package()
    package_path = config / "paid.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    os.chmod(package_path, 0o644)
    instructions = config / f"{package['slug']}.instructions.md"
    instructions.write_text("private", encoding="utf-8")
    os.chmod(instructions, 0o644)
    result = run_preflight(
        env=good_env(tmp_path),
        runtime_dir=RUNTIME_DIR,
        config_dir=config,
        verify_git_revision=False,
    )
    assert "ACTIVE_PACKAGE_PERMISSIONS_TOO_OPEN" in codes(result)
    assert "ACTIVE_INSTRUCTIONS_PERMISSIONS_TOO_OPEN" in codes(result)


def test_draft_package_is_not_treated_as_active(tmp_path):
    package = paid_active_package()
    package["status"] = "draft"
    package["access"]["commercial_enforcement"] = "NOT_IMPLEMENTED"
    result = run_with_package(tmp_path, package)
    warning_codes = {item["code"] for item in result["warnings"]}
    assert "DRAFT_PACKAGE_PRESENT" in warning_codes
    assert result["active_packages"] == 0
    assert result["active_paid_packages"] == 0
