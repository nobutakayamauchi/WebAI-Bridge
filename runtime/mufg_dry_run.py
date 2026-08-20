from __future__ import annotations

import argparse
import json
from pathlib import Path

from mufg_response_ingress import normalize_mufg_payment_arrivals_response


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a saved MUFG payment-arrivals JSON response without granting access.")
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--order-ref-source", choices=["ediInfo", "paymentApplicantNo"], default="paymentApplicantNo")
    parser.add_argument("--currency", default="JPY")
    parser.add_argument("--show", type=int, default=5)
    args = parser.parse_args()

    payload = json.loads(args.json_path.read_text(encoding="utf-8"))
    batch = normalize_mufg_payment_arrivals_response(
        response=payload,
        account_id=args.account_id,
        order_ref_source=args.order_ref_source,
        currency=args.currency,
    )

    print(json.dumps({
        "status": "DRY_RUN_ONLY",
        "normalized_count": len(batch.deposits),
        "declared_number": batch.declared_number,
        "next_flag": batch.next_flag,
        "next_keyword": batch.next_keyword,
        "sample": list(batch.deposits[:max(0, args.show)]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
