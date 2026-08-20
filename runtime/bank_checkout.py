from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
from typing import Callable

from bank_payment_ingress import BankOrder, BankOrderStore


@dataclass(frozen=True)
class BankCheckout:
    order_ref: str
    claim_token: str
    package_id: str
    amount_minor: int
    currency: str


class BankCheckoutService:
    """Issue bank-transfer orders without making order_ref a bearer credential."""

    def __init__(self, orders: BankOrderStore, *, random_digits: Callable[[], int] | None = None):
        self.orders = orders
        self.random_digits = random_digits or (lambda: secrets.randbelow(90000000) + 10000000)

    @staticmethod
    def claim_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, *, package_id: str, amount_minor: int, currency: str = "JPY") -> BankCheckout:
        if not package_id or amount_minor <= 0 or currency.upper() != "JPY":
            raise ValueError("bank checkout requires package_id, positive JPY amount")
        claim_token = secrets.token_urlsafe(32)
        claim_hash = self.claim_hash(claim_token)
        buyer_ref = f"bank-claim:{claim_hash[:24]}"

        for _ in range(20):
            order_ref = str(self.random_digits())
            if len(order_ref) != 8 or not order_ref.isdigit():
                raise RuntimeError("bank order reference generator must return 8 digits")
            if self.orders.get(order_ref) is not None:
                continue
            try:
                self.orders.create(
                    BankOrder(
                        order_ref=order_ref,
                        package_id=package_id,
                        buyer_ref=buyer_ref,
                        amount_minor=amount_minor,
                        currency=currency.upper(),
                        claim_hash=claim_hash,
                    )
                )
            except Exception:
                if self.orders.get(order_ref) is not None:
                    continue
                raise
            return BankCheckout(order_ref, claim_token, package_id, amount_minor, currency.upper())
        raise RuntimeError("could not allocate unique bank order reference")

    def claim_paid(self, *, order_ref: str, claim_token: str) -> BankOrder:
        order = self.orders.get(order_ref)
        if order is None:
            raise ValueError("unknown bank order")
        candidate = self.claim_hash(str(claim_token or ""))
        if not order.claim_hash or not secrets.compare_digest(order.claim_hash, candidate):
            raise ValueError("bank checkout browser claim is invalid")
        if order.status != "PAID" or not order.payment_ref:
            raise ValueError("bank order is not paid yet")
        return order
