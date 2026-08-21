from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bank_payment_ingress import BankOrderStore, BankPaymentIngress
from entitlements import EntitlementStore
from mufg_batch_fulfillment import fulfill_mufg_batch
from mufg_response_ingress import normalize_mufg_payment_arrivals_response
from payment_adapter import BankTransactionClaimStore, PaymentVerificationError


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENTITLEMENT_DB = BASE_DIR / ".runtime" / "webai-entitlements.sqlite3"
DEFAULT_MUFG_BASE_URL = "https://developer.api.bk.mufg.jp/btmu/corporation/trial/v1/accounts"


@dataclass(frozen=True)
class MUFGPollSummary:
    pages: int
    provider_records: int
    normalized: int
    provider_unmatchable: int
    fulfilled: int
    unknown_orders: int
    rejected_known_orders: int


class MUFGAccountClient:
    def __init__(self, *, api_key: str, account_id: str, base_url: str = DEFAULT_MUFG_BASE_URL, timeout_seconds: int = 20):
        self.api_key = str(api_key or "").strip()
        self.account_id = str(account_id or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = int(timeout_seconds)
        self._counter = 0
        if not self.api_key:
            raise ValueError("MUFG API key is required")
        if len(self.account_id) != 11:
            raise ValueError("MUFG account id must be exactly 11 characters")

    def _sequence_no(self) -> str:
        import secrets
        import string

        prefix = datetime.now().strftime("%Y%m%d")
        suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        value = f"{prefix}-{suffix}"
        if len(value) != 25:
            raise RuntimeError("MUFG sequence number must be exactly 25 characters")
        return value

    def fetch_payment_arrivals(self, *, inquiry_date_from: str, inquiry_date_to: str, next_keyword: str | None = None) -> Mapping[str, Any]:
        query: dict[str, str] = {
            "inquiryDateFrom": inquiry_date_from,
            "inquiryDateTo": inquiry_date_to,
        }
        if next_keyword:
            query["nextKeyword"] = next_keyword
        url = f"{self.base_url}/{self.account_id}/transactions/paymentarrivals?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "X-IBM-Client-Id": self.api_key,
                "X-BTMU-Seq-No": self._sequence_no(),
            },
            method="GET",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - fixed HTTPS provider endpoint by configuration
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise PaymentVerificationError("MUFG API response must be a JSON object")
        return payload


def production_ingress_from_env() -> BankPaymentIngress:
    entitlement_db = Path(os.getenv("WEB_AI_ENTITLEMENT_DB", DEFAULT_ENTITLEMENT_DB))
    bank_order_db = Path(os.getenv("WEB_AI_BANK_ORDER_DB", entitlement_db.parent / "webai-bank-orders.sqlite3"))
    bank_claim_db = Path(os.getenv("WEB_AI_BANK_CLAIM_DB", entitlement_db.parent / "webai-bank-claims.sqlite3"))
    return BankPaymentIngress(
        orders=BankOrderStore(bank_order_db),
        entitlements=EntitlementStore(entitlement_db),
        claims=BankTransactionClaimStore(bank_claim_db),
    )


def run_mufg_poll(
    *,
    fetch_page: Callable[[str | None], Mapping[str, Any]],
    account_id: str,
    ingress: BankPaymentIngress,
    order_ref_source: str = "auto",
    currency: str = "JPY",
    max_pages: int = 100,
) -> MUFGPollSummary:
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")

    pages = provider_records = normalized = provider_unmatchable = 0
    fulfilled = unknown_orders = rejected_known_orders = 0
    next_keyword: str | None = None
    seen_keywords: set[str] = set()

    while True:
        if pages >= max_pages:
            raise PaymentVerificationError("MUFG pagination exceeded max_pages")
        payload = fetch_page(next_keyword)
        batch = normalize_mufg_payment_arrivals_response(
            response=payload,
            account_id=account_id,
            order_ref_source=order_ref_source,
            currency=currency,
        )
        result = fulfill_mufg_batch(batch=batch, ingress=ingress)

        pages += 1
        provider_records += batch.declared_number
        normalized += len(batch.deposits)
        provider_unmatchable += len(batch.unmatchable)
        fulfilled += len(result.fulfilled)
        unknown_orders += len(result.skipped_unknown_orders)
        rejected_known_orders += len(result.rejected_known_orders)

        if batch.next_flag == "0":
            break
        candidate = str(batch.next_keyword or "").strip()
        if not candidate:
            raise PaymentVerificationError("MUFG pagination requires nextKeyword")
        if candidate in seen_keywords:
            raise PaymentVerificationError("MUFG pagination repeated nextKeyword")
        seen_keywords.add(candidate)
        next_keyword = candidate

    return MUFGPollSummary(
        pages=pages,
        provider_records=provider_records,
        normalized=normalized,
        provider_unmatchable=provider_unmatchable,
        fulfilled=fulfilled,
        unknown_orders=unknown_orders,
        rejected_known_orders=rejected_known_orders,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll MUFG payment-arrival API and fulfill matching WebAI bank orders.")
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--currency", default="JPY")
    args = parser.parse_args()

    api_key = os.getenv("WEB_AI_MUFG_API_KEY", "")
    account_id = os.getenv("WEB_AI_MUFG_ACCOUNT_ID", "")
    base_url = os.getenv("WEB_AI_MUFG_BASE_URL", DEFAULT_MUFG_BASE_URL)
    client = MUFGAccountClient(api_key=api_key, account_id=account_id, base_url=base_url)
    ingress = production_ingress_from_env()

    summary = run_mufg_poll(
        fetch_page=lambda keyword: client.fetch_payment_arrivals(
            inquiry_date_from=args.from_date,
            inquiry_date_to=args.to_date,
            next_keyword=keyword,
        ),
        account_id=account_id,
        ingress=ingress,
        order_ref_source="auto",
        currency=args.currency,
        max_pages=args.max_pages,
    )
    print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
