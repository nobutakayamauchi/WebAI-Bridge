from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from payment_adapter import BankTransactionClaimStore, PaymentVerificationError, verify_bank_transfer
from payment_fulfillment import EntitlementAuthority, FulfillmentResult, fulfill_verified_payment


@dataclass(frozen=True)
class BankOrder:
    order_ref: str
    package_id: str
    buyer_ref: str
    amount_minor: int
    currency: str
    status: str = "AWAITING_PAYMENT"
    claim_hash: str = ""
    payment_ref: str = ""

    def as_mapping(self) -> dict[str, Any]:
        return {
            "order_ref": self.order_ref,
            "package_id": self.package_id,
            "buyer_ref": self.buyer_ref,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "status": self.status,
        }


class BankOrderStore:
    """Durable authority for bank-transfer orders.

    A bank adapter is never allowed to invent package, buyer, expected amount,
    browser claim authority, or payment_ref from deposit payloads. The order
    store is the server-side source of truth.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bank_orders (
                    order_ref TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    buyer_ref TEXT NOT NULL DEFAULT '',
                    amount_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claim_hash TEXT NOT NULL DEFAULT '',
                    payment_ref TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(bank_orders)").fetchall()}
            if "claim_hash" not in columns:
                conn.execute("ALTER TABLE bank_orders ADD COLUMN claim_hash TEXT NOT NULL DEFAULT ''")
            if "payment_ref" not in columns:
                conn.execute("ALTER TABLE bank_orders ADD COLUMN payment_ref TEXT NOT NULL DEFAULT ''")

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, order: BankOrder) -> None:
        if not order.order_ref or not order.package_id or order.amount_minor <= 0 or not order.currency:
            raise ValueError("invalid bank order")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO bank_orders(order_ref, package_id, buyer_ref, amount_minor, currency, status, claim_hash, payment_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order.order_ref,
                    order.package_id,
                    order.buyer_ref,
                    order.amount_minor,
                    order.currency.upper(),
                    order.status,
                    order.claim_hash,
                    order.payment_ref,
                ),
            )

    def get(self, order_ref: str) -> BankOrder | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bank_orders WHERE order_ref=?", (order_ref,)).fetchone()
        if row is None:
            return None
        return BankOrder(
            order_ref=row["order_ref"],
            package_id=row["package_id"],
            buyer_ref=row["buyer_ref"],
            amount_minor=int(row["amount_minor"]),
            currency=row["currency"],
            status=row["status"],
            claim_hash=row["claim_hash"],
            payment_ref=row["payment_ref"],
        )

    def mark_paid(self, order_ref: str, payment_ref: str = "") -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE bank_orders SET status='PAID', payment_ref=? WHERE order_ref=? AND status IN ('PENDING','AWAITING_PAYMENT')",
                (payment_ref, order_ref),
            )
            if cursor.rowcount != 1:
                raise PaymentVerificationError("bank order could not transition to PAID")


class BankPaymentIngress:
    """Provider-neutral entry point for authenticated bank deposit data.

    Real MUFG/GMO/etc adapters should authenticate/normalize provider responses,
    then call this boundary. The deposit may identify an order_ref, but it may
    never supply authoritative product/price/buyer fields.
    """

    def __init__(self, *, orders: BankOrderStore, entitlements: EntitlementAuthority, claims: BankTransactionClaimStore):
        self.orders = orders
        self.entitlements = entitlements
        self.claims = claims

    def process(self, deposit: Mapping[str, Any]) -> FulfillmentResult:
        order_ref = str(deposit.get("order_ref") or "").strip()
        if not order_ref:
            raise PaymentVerificationError("deposit.order_ref is required")
        order = self.orders.get(order_ref)
        if order is None:
            raise PaymentVerificationError("bank deposit references unknown order")
        if order.status not in {"PENDING", "AWAITING_PAYMENT"}:
            raise PaymentVerificationError("bank order is not awaiting payment")

        event = verify_bank_transfer(deposit=deposit, order=order.as_mapping())
        result = fulfill_verified_payment(event=event, entitlements=self.entitlements, bank_claims=self.claims)
        self.orders.mark_paid(order_ref, payment_ref=result.payment_ref)
        return result
