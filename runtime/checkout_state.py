from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path


class CheckoutStateStore:
    """Persistent idempotency state independent from entitlement lifecycle.

    Entitlement ACTIVE means the payment currently authorizes the package.
    A checkout claim means one browser redirect has already received authority
    to mint a one-time browser handoff ticket. Keeping these separate allows a
    Stripe webhook to activate entitlement before the browser redirect arrives.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkout_claims (
                    session_id TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    payment_ref TEXT NOT NULL,
                    claimed_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at INTEGER NOT NULL
                )
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def claim_checkout(self, *, session_id: str, package_id: str, payment_ref: str) -> bool:
        if not session_id or not package_id or not payment_ref:
            return False
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO checkout_claims(session_id, package_id, payment_ref, claimed_at) VALUES (?, ?, ?, ?)",
                    (session_id, package_id, payment_ref, int(time.time())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def event_processed(self, event_id: str) -> bool:
        if not event_id:
            return False
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM webhook_events WHERE event_id=?", (event_id,)
            ).fetchone() is not None

    def mark_event_processed(self, *, event_id: str, event_type: str) -> bool:
        if not event_id or not event_type:
            return False
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO webhook_events(event_id, event_type, processed_at) VALUES (?, ?, ?)",
                    (event_id, event_type, int(time.time())),
                )
            return True
        except sqlite3.IntegrityError:
            return False
