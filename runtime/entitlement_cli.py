from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

from entitlements import EntitlementStore

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"))


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
