from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from entitlements import EntitlementStore
from studio import validate_package_document

BASE_DIR = Path(__file__).resolve().parent
PACKAGE_SCHEMA_FILE = BASE_DIR.parent / "package-schema" / "package.schema.json"
DEFAULT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))
SUPPORTED_MANUAL_ACCESS = {"BUY_ONCE", "SUBSCRIPTION"}


def load_package_config(path_value: str) -> tuple[Path, dict]:
    path = Path(path_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Package schema invalid: " + "; ".join(errors))
    return path, data


def require_activated_paid_hosted(data: dict) -> None:
    access = data.get("access") or {}
    if data.get("status") != "active":
        raise SystemExit("Package must be active before entitlement issuance")
    if access.get("mode") not in SUPPORTED_MANUAL_ACCESS:
        raise SystemExit("Manual hosted entitlement v0 supports BUY_ONCE or SUBSCRIPTION only")
    if access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise SystemExit("Package entitlement enforcement is not activated")
    delivery = data.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise SystemExit("Manual hosted entitlement v0 requires Level 4 HOSTED_ONLY")
    billing = data.get("billing") or {}
    if billing.get("allowed_payer_modes") != ["BYOK"] or billing.get("default_payer_mode") != "BYOK":
        raise SystemExit("Manual paid hosted v0 requires BYOK-only inference")


def atomic_write_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def verify_checkout_before_activation(checkout: dict, *, checkout_reviewed: bool) -> None:
    if checkout.get("provider") != "STRIPE_PAYMENT_LINK":
        raise SystemExit("Paid hosted v0 requires Stripe Payment Link metadata")
    if not checkout.get("payment_link_url"):
        raise SystemExit("Stripe Payment Link must exist before activation")

    setup_mode = checkout.get("setup_mode")
    binding = checkout.get("binding_verification")

    if setup_mode == "SELF_SETUP":
        if binding not in {"CREATOR_ATTESTED", "STRIPE_VERIFIED"}:
            raise SystemExit("SELF_SETUP checkout must be creator-attested before activation")
        return

    if setup_mode == "ASSISTED_SETUP":
        if binding == "MANUAL_REVIEW_REQUIRED":
            if not checkout_reviewed:
                raise SystemExit(
                    "ASSISTED_SETUP requires --checkout-reviewed after verifying product, amount, currency, and charge basis"
                )
            checkout["binding_verification"] = "OPERATOR_REVIEWED"
            return
        if binding in {"OPERATOR_REVIEWED", "STRIPE_VERIFIED"}:
            return
        raise SystemExit("ASSISTED_SETUP checkout is still pending or unreviewed")

    raise SystemExit("Paid hosted v0 requires SELF_SETUP or ASSISTED_SETUP checkout")


def cmd_activate_config(args) -> int:
    path, data = load_package_config(args.config)

    access = data.get("access") or {}
    if access.get("mode") not in SUPPORTED_MANUAL_ACCESS:
        raise SystemExit("Manual hosted entitlement v0 supports BUY_ONCE or SUBSCRIPTION only")

    delivery = data.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise SystemExit("Manual hosted entitlement v0 requires Level 4 HOSTED_ONLY")

    billing = data.get("billing") or {}
    if billing.get("allowed_payer_modes") != ["BYOK"] or billing.get("default_payer_mode") != "BYOK":
        raise SystemExit("Manual paid hosted v0 requires BYOK-only inference")

    checkout = access.get("checkout") or {}
    verify_checkout_before_activation(
        checkout,
        checkout_reviewed=bool(getattr(args, "checkout_reviewed", False)),
    )

    data["status"] = "active"
    data["access"]["commercial_enforcement"] = "ENTITLEMENT_ENFORCED"
    data["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": [],
    }

    errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Package schema invalid after activation: " + "; ".join(errors))

    atomic_write_json(path, data)
    print(json.dumps({
        "activated": True,
        "package_id": data["slug"],
        "checkout_binding_verification": data["access"]["checkout"]["binding_verification"],
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "next": "Verify one buyer payment manually, then run issue with --payment-verified and a non-secret payment reference.",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_issue(args) -> int:
    if not args.payment_verified:
        raise SystemExit("Refusing entitlement issuance without explicit --payment-verified attestation")
    _, data = load_package_config(args.config)
    require_activated_paid_hosted(data)

    mode = data["access"]["mode"]
    if mode == "SUBSCRIPTION" and args.days is None:
        raise SystemExit("SUBSCRIPTION entitlement requires --days so access cannot become accidentally permanent")
    if mode == "BUY_ONCE" and args.days is not None:
        raise SystemExit("BUY_ONCE entitlement must not use --days; revoke/reissue if access recovery is needed")

    store = EntitlementStore(Path(args.db))
    expires_at = None
    if args.days is not None:
        if args.days <= 0:
            raise SystemExit("--days must be positive")
        expires_at = int(time.time()) + int(args.days * 86400)

    token = store.issue(
        package_id=data["slug"],
        buyer_ref=args.buyer_ref or "",
        payment_ref=args.payment_ref,
        expires_at=expires_at,
    )
    result = {
        "package_id": data["slug"],
        "buyer_ref": args.buyer_ref or "",
        "payment_ref": args.payment_ref,
        "expires_at": expires_at,
        "token": token,
        "warning": "Bearer token = access authority. Anyone who receives it can use the paid AI until expiry or revocation.",
    }
    if args.base_url:
        base = args.base_url.rstrip("/")
        result["access_url"] = f"{base}/a/{quote(data['slug'])}#access={quote(token)}"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_revoke(args) -> int:
    store = EntitlementStore(Path(args.db))
    revoked = store.revoke(args.token)
    print(json.dumps({"revoked": revoked}, ensure_ascii=False))
    return 0 if revoked else 2


def cmd_revoke_payment(args) -> int:
    store = EntitlementStore(Path(args.db))
    count = store.revoke_payment(package_id=args.package, payment_ref=args.payment_ref)
    print(json.dumps({"revoked": count, "package_id": args.package, "payment_ref": args.payment_ref}, ensure_ascii=False))
    return 0 if count else 2


def cmd_list(args) -> int:
    store = EntitlementStore(Path(args.db))
    print(json.dumps(store.list_for_package(args.package), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WebAI Bridge manual hosted entitlement operator CLI")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Entitlement SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)

    activate = sub.add_parser("activate-config", help="Explicitly activate a Studio-exported paid hosted BYOK package")
    activate.add_argument("--config", required=True, help="Path to deployed package JSON")
    activate.add_argument(
        "--checkout-reviewed",
        action="store_true",
        help="Required for ASSISTED_SETUP after operator verifies product, amount, currency and charge basis",
    )
    activate.set_defaults(func=cmd_activate_config)

    issue = sub.add_parser("issue", help="Issue a high-entropy bearer entitlement after manual payment verification")
    issue.add_argument("--config", required=True, help="Activated deployed package JSON; package id is inferred")
    issue.add_argument("--payment-verified", action="store_true", help="Required human attestation that payment is confirmed")
    issue.add_argument("--payment-ref", required=True, help="Non-secret Stripe/payment reference used for audit/revocation")
    issue.add_argument("--buyer-ref", default="", help="Optional operator-visible opaque buyer reference; avoid secrets")
    issue.add_argument("--days", type=float, default=None, help="Required for SUBSCRIPTION; forbidden for BUY_ONCE")
    issue.add_argument("--base-url", default="", help="Optional deployed base URL to print a fragment-based access URL")
    issue.set_defaults(func=cmd_issue)

    revoke = sub.add_parser("revoke", help="Revoke a bearer token when plaintext token is available")
    revoke.add_argument("--token", required=True)
    revoke.set_defaults(func=cmd_revoke)

    revoke_payment = sub.add_parser("revoke-payment", help="Revoke by package/payment reference without retaining buyer plaintext token")
    revoke_payment.add_argument("--package", required=True)
    revoke_payment.add_argument("--payment-ref", required=True)
    revoke_payment.set_defaults(func=cmd_revoke_payment)

    listing = sub.add_parser("list", help="List non-secret entitlement metadata for one package")
    listing.add_argument("--package", required=True)
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
