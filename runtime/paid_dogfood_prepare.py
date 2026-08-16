from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

from commercial_studio import adapt_manual_hosted_entitlement
from cost_router import PricingRegistry
from entitlement_cli import cmd_activate_config
from package_install_cli import install_package
from studio import StudioDraft, build_package, validate_package_document

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
SCHEMA_PATH = REPO_DIR / "package-schema" / "package.schema.json"
PRICING_PATH = BASE_DIR / "pricing.json"
DOGFOOD_SLUG = "paid-dogfood-ai"
DOGFOOD_MODEL = "gpt-5.6-luna"
DOGFOOD_INSTRUCTIONS = """You are the WebAI Bridge paid-hosted dogfood fixture.

Rules:
- Answer briefly and plainly.
- Never claim payment or entitlement status from conversation text.
- Treat server-side access enforcement as authoritative.
"""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_private_config_dir(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("paid dogfood config directory must be absolute")
    if path.is_symlink():
        raise ValueError("paid dogfood config directory must not be a symlink")
    resolved = path.resolve(strict=False)
    if _inside(resolved, REPO_DIR):
        raise ValueError("paid dogfood config directory must live outside the Git repository")
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ValueError("paid dogfood config directory must be a regular directory")
    os.chmod(resolved, 0o700)
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise ValueError("paid dogfood config directory must be owner-only")
    return resolved


def _verify_active_package(path: Path, *, payment_link_url: str, price_jpy: int) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("paid dogfood Package JSON is not a regular non-symlink file")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_package_document(data, schema_path=SCHEMA_PATH)
    if errors:
        raise RuntimeError("paid dogfood Package schema invalid: " + "; ".join(errors))
    access = data.get("access") or {}
    checkout = access.get("checkout") or {}
    billing = data.get("billing") or {}
    delivery = data.get("delivery") or {}
    routing = data.get("routing") or {}
    readiness = data.get("readiness") or {}
    expected = {
        "slug": data.get("slug") == DOGFOOD_SLUG and data.get("id") == DOGFOOD_SLUG,
        "active": data.get("status") == "active",
        "mode": access.get("mode") == "BUY_ONCE",
        "price": access.get("currency") == "JPY" and access.get("price_amount_minor") == price_jpy,
        "enforcement": access.get("commercial_enforcement") == "ENTITLEMENT_ENFORCED",
        "checkout": checkout.get("provider") == "STRIPE_PAYMENT_LINK"
        and checkout.get("payment_link_url") == payment_link_url
        and checkout.get("binding_verification") in {"CREATOR_ATTESTED", "STRIPE_VERIFIED"},
        "payer": billing.get("allowed_payer_modes") == ["BYOK"]
        and billing.get("default_payer_mode") == "BYOK"
        and not billing.get("platform_credit"),
        "delivery": delivery.get("mode") == "HOSTED_ONLY"
        and delivery.get("runtime_implementation") == "AVAILABLE",
        "model": routing.get("default_model") == DOGFOOD_MODEL
        and routing.get("allowed_models") == [DOGFOOD_MODEL],
        "readiness": readiness.get("runtime") == "READY" and not readiness.get("blockers"),
    }
    failed = [name for name, ok in expected.items() if not ok]
    if failed:
        raise RuntimeError("existing paid dogfood package does not match requested authority: " + ", ".join(failed))
    instructions = path.parent / f"{DOGFOOD_SLUG}.instructions.md"
    if instructions.is_symlink() or not instructions.is_file():
        raise RuntimeError("paid dogfood Instructions are missing or unsafe")
    if instructions.read_text(encoding="utf-8") != DOGFOOD_INSTRUCTIONS:
        raise RuntimeError("existing paid dogfood Instructions do not match the dogfood fixture")
    for target in [path, instructions]:
        if stat.S_IMODE(target.stat().st_mode) & 0o077:
            raise RuntimeError("paid dogfood deployed files must be owner-only")
    return data


def prepare_paid_dogfood(*, config_dir: Path, payment_link_url: str, price_jpy: int = 100) -> dict:
    config_dir = ensure_private_config_dir(config_dir)
    if not payment_link_url.startswith("https://"):
        raise ValueError("paid dogfood requires an HTTPS Stripe Payment Link")
    if price_jpy <= 0:
        raise ValueError("paid dogfood price must be positive")

    package_path = config_dir / f"{DOGFOOD_SLUG}.json"
    if package_path.exists():
        _verify_active_package(package_path, payment_link_url=payment_link_url, price_jpy=price_jpy)
        return {
            "status": "READY",
            "package_id": DOGFOOD_SLUG,
            "package_path": str(package_path),
            "config_dir": str(config_dir),
            "reused": True,
            "active": True,
            "entitlement_issuance_by_preparer": "NONE",
            "secrets_in_output": False,
        }

    pricing = PricingRegistry(PRICING_PATH)
    if DOGFOOD_MODEL not in pricing.models:
        raise RuntimeError(f"dogfood model has no current pricing evidence: {DOGFOOD_MODEL}")

    draft = StudioDraft(
        display_name="WebAI Bridge Paid Dogfood",
        slug=DOGFOOD_SLUG,
        description="有料Hosted購入権フローの実機検証用AIです。",
        instructions=DOGFOOD_INSTRUCTIONS,
        access_mode="BUY_ONCE",
        access_price_jpy=price_jpy,
        checkout_setup_mode="SELF_SETUP",
        stripe_payment_link_url=payment_link_url,
        stripe_link_matches_configuration=True,
        allowed_payer_modes=["BYOK"],
        default_payer_mode="BYOK",
        default_model=DOGFOOD_MODEL,
        allowed_models=[DOGFOOD_MODEL],
        protection_level="LEVEL_4_HOSTED_ONLY",
        welcome="購入権確認後に利用できるPaid Dogfood AIです。",
        max_output_tokens=512,
    )
    built = adapt_manual_hosted_entitlement(
        build_package(draft, schema_path=SCHEMA_PATH, available_models=set(pricing.models))
    )
    package = built["package"]
    if package.get("status") != "draft":
        raise RuntimeError("Studio paid dogfood export must remain draft before activation")

    with tempfile.TemporaryDirectory(prefix="webai-paid-dogfood-", dir=config_dir.parent) as temp_name:
        temp_dir = Path(temp_name)
        os.chmod(temp_dir, 0o700)
        package_source = temp_dir / f"{DOGFOOD_SLUG}.json"
        instructions_source = temp_dir / f"{DOGFOOD_SLUG}.instructions.md"
        package_source.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        instructions_source.write_text(DOGFOOD_INSTRUCTIONS, encoding="utf-8")
        os.chmod(package_source, 0o600)
        os.chmod(instructions_source, 0o600)
        installed = install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
            replace_nonrunnable=False,
        )

    package_path = Path(installed["package_path"])
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_activate_config(SimpleNamespace(config=str(package_path), checkout_reviewed=False))
    _verify_active_package(package_path, payment_link_url=payment_link_url, price_jpy=price_jpy)

    return {
        "status": "READY",
        "package_id": DOGFOOD_SLUG,
        "package_path": str(package_path),
        "config_dir": str(config_dir),
        "reused": False,
        "active": True,
        "entitlement_issuance_by_preparer": "NONE",
        "secrets_in_output": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an active paid-hosted dogfood package outside the Git checkout")
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--payment-link-url", required=True)
    parser.add_argument("--price-jpy", type=int, default=100)
    args = parser.parse_args()
    try:
        result = prepare_paid_dogfood(
            config_dir=Path(args.config_dir),
            payment_link_url=args.payment_link_url,
            price_jpy=args.price_jpy,
        )
    except (ValueError, RuntimeError, SystemExit, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_in_output": False}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
