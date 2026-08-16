from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path


class HandoffTicketStore:
    """Persistent one-time browser handoff tickets."""

    def __init__(self, path: Path, *, ttl_seconds: int = 600):
        if ttl_seconds < 60 or ttl_seconds > 3600:
            raise ValueError("handoff ttl must be between 60 and 3600 seconds")
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS handoff_tickets (
                    ticket_hash TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    payment_ref TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_handoff_payment ON handoff_tickets(package_id, payment_ref)"
            )

    @staticmethod
    def _hash(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    def issue(self, *, package_id: str, payment_ref: str, now: int | None = None) -> str:
        if not package_id or not payment_ref:
            raise ValueError("package_id and payment_ref are required")
        current = int(time.time()) if now is None else int(now)
        ticket = "handoff_" + secrets.token_urlsafe(32)
        digest = self._hash(ticket)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO handoff_tickets
                (ticket_hash, package_id, payment_ref, issued_at, expires_at, consumed_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (digest, package_id, payment_ref, current, current + self.ttl_seconds),
            )
        return ticket

    def consume(
        self,
        *,
        package_id: str,
        ticket: str | None,
        now: int | None = None,
    ) -> str | None:
        if not package_id or not ticket or not ticket.startswith("handoff_"):
            return None
        current = int(time.time()) if now is None else int(now)
        digest = self._hash(ticket)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT payment_ref, expires_at, consumed_at
                FROM handoff_tickets
                WHERE ticket_hash=? AND package_id=?
                """,
                (digest, package_id),
            ).fetchone()
            if row is None or row["consumed_at"] is not None or int(row["expires_at"]) <= current:
                conn.execute("ROLLBACK")
                return None
            updated = conn.execute(
                """
                UPDATE handoff_tickets
                SET consumed_at=?
                WHERE ticket_hash=? AND package_id=? AND consumed_at IS NULL AND expires_at>?
                """,
                (current, digest, package_id, current),
            )
            if updated.rowcount != 1:
                conn.execute("ROLLBACK")
                return None
            conn.execute("COMMIT")
            return str(row["payment_ref"])
