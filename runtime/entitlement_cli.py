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


def cmd_activate_config(args) -> int:
    path = Path(args.config)
    data = json.loads(path.read_text(encoding="utf-8"))

    errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Package schema invalid before activation: " + "; ".join(errors))

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
    if checkout.get("provider") != "STRIPE_PAYMENT_LINK":
        raise SystemExit("Paid hosted v0 requires Stripe Payment Link metadata")
    if checkout.get("setup_mode") == "SELF_SETUP" and checkout.get("binding_verification") != "CREATOR_ATTESTED":
        raise SystemExit("SELF_SETUP checkout must be creator-attested before activation")
    if not checkout.get("payment_link_url"):
        raise SystemExit("Stripe Payment Link must exist before activation")

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

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "activated": True,
        "package_id": data["slug"],
        "runtime": "READY",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "next": "Verify buyer payment manually, then issue one bearer entitlement with the issue command.",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_issue(args) -> int:
    store = EntitlementStore(Path(args.db))
    expires_at = None
    if args.days is not None:
        expires_at = int(time.time()) + int(args.days * 86400)
    token = store.issue(package_id=args.package, buyer_ref=args.buyer_ref or "", expires_at=expires_at)
    result = {
        "package_id": args.package,
        "buyer_ref": args.buyer_ref or "",
        "expires_at": expires_at,
        "token": token,
        "warning": "Bearer token = access authority. Anyone who receives it can use the paid AI until expiry or revocation.",
    }
    if args.base_url:
        base = args.base_url.rstrip("/")
        result["access_url"] = f"{base}/a/{quote(args.package)}#access={quote(token)}"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_revoke(args) -> int:
    store = EntitlementStore(Path(args.db))
    revoked = store.revoke(args.token)
    print(json.dumps({"revoked": revoked}, ensure_ascii=False))
    return 0 if revoked else 2


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
    activate.set_defaults(func=cmd_activate_config)

    issue = sub.add_parser("issue", help="Issue a high-entropy bearer entitlement after manual payment verification")
    issue.add_argument("--package", required=True)
    issue.add_argument("--buyer-ref", default="", help="Operator-visible opaque buyer reference; avoid secrets")
    issue.add_argument("--days", type=float, default=None, help="Optional expiry in days; omit for non-expiring buy-once")
    issue.add_argument("--base-url", default="", help="Optional deployed base URL to print a fragment-based access URL")
    issue.set_defaults(func=cmd_issue)

    revoke = sub.add_parser("revoke", help="Revoke a bearer token")
    revoke.add_argument("--token", required=True)
    revoke.set_defaults(func=cmd_revoke)

    listing = sub.add_parser("list", help="List non-secret entitlement metadata for one package")
    listing.add_argument("--package", required=True)
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
