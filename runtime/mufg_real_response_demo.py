from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from bank_payment_ingress import BankOrder, BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from mufg_batch_fulfillment import fulfill_mufg_batch
from mufg_response_ingress import normalize_mufg_payment_arrivals_response
from payment_adapter import BankTransactionClaimStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely exercise a saved MUFG trial response through order matching and entitlement issuance.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--order-ref", required=True)
    parser.add_argument("--amount", required=True, type=int)
    parser.add_argument("--package-id", default="mufg-trial-product")
    parser.add_argument("--buyer-ref", default="trial@example.test")
    args = parser.parse_args()

    payload = json.loads(args.json_path.read_text(encoding="utf-8"))
    batch = normalize_mufg_payment_arrivals_response(response=payload, account_id=args.account_id, order_ref_source="auto")

    with tempfile.TemporaryDirectory(prefix="webai-mufg-trial-") as tmp:
        root = Path(tmp)
        orders = BankOrderStore(root / "orders.sqlite3")
        entitlements = EntitlementStore(root / "entitlements.sqlite3")
        claims = BankTransactionClaimStore(root / "claims.sqlite3")
        ingress = BankPaymentIngress(orders=orders, entitlements=entitlements, claims=claims)
        orders.create(BankOrder(args.order_ref, args.package_id, args.buyer_ref, args.amount, "JPY"))

        result = fulfill_mufg_batch(batch=batch, ingress=ingress)
        print(json.dumps({
            "status": "TEMPORARY_TRIAL_FULFILLMENT",
            "provider_records": batch.declared_number,
            "normalized": len(batch.deposits),
            "provider_unmatchable": len(batch.unmatchable),
            "fulfilled": list(result.fulfilled),
            "fulfilled_count": len(result.fulfilled),
            "unknown_order_count": len(result.skipped_unknown_orders),
            "rejected_known_order_count": len(result.rejected_known_orders),
            "order_status": orders.get(args.order_ref).status if orders.get(args.order_ref) else None,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
