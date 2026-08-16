from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal, ROUND_CEILING
from pathlib import Path


class PricingRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.version = "UNSET"
        self.source = "UNSET"
        self.models: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.version = "UNSET"
            self.source = "UNSET"
            self.models = {}
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = str(data.get("version") or "UNSET")
        self.source = str(data.get("source") or "UNSET")
        self.models = dict(data.get("models") or {})

    def get(self, model: str) -> dict:
        price = self.models.get(model)
        if not price:
            raise KeyError(model)
        return price


def cost_micros(*, input_tokens: int, output_tokens: int, price: dict) -> int:
    """Calculate USD microdollars using fixed-point rounding upward.

    Rates are USD / 1M tokens and 1 USD = 1M microdollars, so
    tokens * rate == microdollars.
    """
    input_rate = Decimal(str(price["input_usd_per_1m"]))
    output_rate = Decimal(str(price["output_usd_per_1m"]))
    value = Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    return int(value.to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    """Bounded persistent v0 budget + usage ledger.

    Reservation prevents normal concurrent callers from authorizing the same remaining
    budget twice. If observed provider cost exceeds the reservation, settlement records
    the observed cost even when that makes spent exceed the hard limit. The provider
    charge has already happened at that point; hiding the overrun would make the ledger
    false. A spent value at/above the hard limit blocks later reservations.

    Reservation identity/idempotent retry and crash leases remain a production gate.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budgets (
                    budget_id TEXT PRIMARY KEY,
                    hard_limit_micros INTEGER NOT NULL,
                    spent_micros INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    package_id TEXT NOT NULL,
                    payer_mode TEXT NOT NULL,
                    budget_id TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    pricing_version TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    reserved_cost_micros INTEGER NOT NULL DEFAULT 0,
                    actual_cost_micros INTEGER,
                    charged_cost_micros INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL
                )
                """
            )

    def reserve(self, budget_id: str, hard_limit_micros: int, amount_micros: int) -> bool:
        if amount_micros <= 0:
            raise ValueError("reservation must be positive")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT hard_limit_micros, spent_micros, reserved_micros FROM budgets WHERE budget_id=?",
                (budget_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO budgets (budget_id, hard_limit_micros, spent_micros, reserved_micros) VALUES (?, ?, 0, 0)",
                    (budget_id, hard_limit_micros),
                )
                effective_limit, spent, reserved = hard_limit_micros, 0, 0
            else:
                effective_limit = min(int(row["hard_limit_micros"]), hard_limit_micros)
                spent = int(row["spent_micros"])
                reserved = int(row["reserved_micros"])

            if spent + reserved + amount_micros > effective_limit:
                conn.execute("ROLLBACK")
                return False

            conn.execute(
                "UPDATE budgets SET reserved_micros=reserved_micros+?, hard_limit_micros=? WHERE budget_id=?",
                (amount_micros, effective_limit, budget_id),
            )
            conn.execute("COMMIT")
            return True

    def settle_platform(self, *, budget_id: str, reserved_micros: int, charged_micros: int, package_id: str, provider: str, model: str, pricing_version: str, input_tokens: int | None, output_tokens: int | None, actual_cost_micros: int | None, result: str) -> None:
        if charged_micros < 0:
            raise ValueError("charged cost must be non-negative")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT reserved_micros FROM budgets WHERE budget_id=?", (budget_id,)).fetchone()
            if row is None or int(row["reserved_micros"]) < reserved_micros:
                conn.execute("ROLLBACK")
                raise RuntimeError("budget reservation missing")
            conn.execute(
                "UPDATE budgets SET reserved_micros=reserved_micros-?, spent_micros=spent_micros+? WHERE budget_id=?",
                (reserved_micros, charged_micros, budget_id),
            )
            self._insert_event(
                conn,
                package_id=package_id,
                payer_mode="PLATFORM_CREDIT",
                budget_id=budget_id,
                provider=provider,
                model=model,
                pricing_version=pricing_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reserved_cost_micros=reserved_micros,
                actual_cost_micros=actual_cost_micros,
                charged_cost_micros=charged_micros,
                result=result,
            )
            conn.execute("COMMIT")

    def release_failed(self, *, budget_id: str, reserved_micros: int, package_id: str, provider: str, model: str, pricing_version: str, result: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE budgets SET reserved_micros=MAX(0, reserved_micros-?) WHERE budget_id=?", (reserved_micros, budget_id))
            self._insert_event(conn, package_id=package_id, payer_mode="PLATFORM_CREDIT", budget_id=budget_id, provider=provider, model=model, pricing_version=pricing_version, input_tokens=None, output_tokens=None, reserved_cost_micros=reserved_micros, actual_cost_micros=None, charged_cost_micros=0, result=result)
            conn.execute("COMMIT")

    def record_byok(self, *, package_id: str, provider: str, model: str, pricing_version: str, input_tokens: int | None, output_tokens: int | None, actual_cost_micros: int | None, result: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._insert_event(conn, package_id=package_id, payer_mode="BYOK", budget_id=None, provider=provider, model=model, pricing_version=pricing_version, input_tokens=input_tokens, output_tokens=output_tokens, reserved_cost_micros=0, actual_cost_micros=actual_cost_micros, charged_cost_micros=0, result=result)
            conn.execute("COMMIT")

    @staticmethod
    def _insert_event(conn, **event) -> None:
        conn.execute(
            """
            INSERT INTO usage_events
            (created_at, package_id, payer_mode, budget_id, provider, model, pricing_version,
             input_tokens, output_tokens, reserved_cost_micros, actual_cost_micros,
             charged_cost_micros, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (int(time.time()), event["package_id"], event["payer_mode"], event["budget_id"], event["provider"], event["model"], event["pricing_version"], event["input_tokens"], event["output_tokens"], event["reserved_cost_micros"], event["actual_cost_micros"], event["charged_cost_micros"], event["result"]),
        )

    def budget_snapshot(self, budget_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT budget_id, hard_limit_micros, spent_micros, reserved_micros FROM budgets WHERE budget_id=?", (budget_id,)).fetchone()
        return dict(row) if row else None
