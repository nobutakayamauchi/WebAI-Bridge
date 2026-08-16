from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path


TOKEN_PREFIX = "webai_"
PAYMENT_MISSING = "MISSING"
PAYMENT_ACTIVE = "ACTIVE"
PAYMENT_REVOKED = "REVOKED"
PAYMENT_EXPIRED = "EXPIRED"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class EntitlementStore:
    """Persistent paid-hosted entitlement authority.

    Legacy/manual flow stores only a SHA-256 digest of a high-entropy bearer token.
    Automatic Stripe handoff can authorize the same entitlement by its verified
    package/payment_ref pair through a signed HttpOnly browser cookie. Revocation
    therefore remains authoritative for both transport modes.
    """

    def __init__(self, path: Path):
        self.path = path
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
                CREATE TABLE IF NOT EXISTS entitlements (
                    token_hash TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    buyer_ref TEXT NOT NULL DEFAULT '',
                    payment_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    revoked_at INTEGER
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(entitlements)").fetchall()}
            if "payment_ref" not in columns:
                conn.execute("ALTER TABLE entitlements ADD COLUMN payment_ref TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entitlements_package ON entitlements(package_id, status)"
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_entitlements_active_payment
                ON entitlements(package_id, payment_ref)
                WHERE status='active' AND payment_ref <> ''
                """
            )

    def issue(
        self,
        *,
        package_id: str,
        buyer_ref: str = "",
        payment_ref: str = "",
        expires_at: int | None = None,
    ) -> str:
        if not package_id:
            raise ValueError("package_id is required")
        if not payment_ref:
            raise ValueError("payment_ref is required")
        now = int(time.time())
        if expires_at is not None and expires_at <= now:
            raise ValueError("expires_at must be in the future")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        digest = token_hash(token)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO entitlements
                    (token_hash, package_id, buyer_ref, payment_ref, status, issued_at, expires_at, revoked_at)
                    VALUES (?, ?, ?, ?, 'active', ?, ?, NULL)
                    """,
                    (digest, package_id, buyer_ref, payment_ref, now, expires_at),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("an active entitlement already exists for this package/payment_ref") from exc
        return token

    def authorize(self, *, package_id: str, token: str | None, now: int | None = None) -> bool:
        if not token or not token.startswith(TOKEN_PREFIX):
            return False
        current = int(time.time()) if now is None else int(now)
        digest = token_hash(token)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT package_id, status, expires_at
                FROM entitlements
                WHERE token_hash=?
                """,
                (digest,),
            ).fetchone()
        if row is None or row["package_id"] != package_id or row["status"] != "active":
            return False
        expires_at = row["expires_at"]
        return expires_at is None or int(expires_at) > current

    def payment_state(
        self,
        *,
        package_id: str,
        payment_ref: str | None,
        now: int | None = None,
    ) -> str:
        """Return the latest lifecycle state for one package/payment pair.

        MISSING is the only state that automatic checkout fulfillment may create.
        REVOKED and EXPIRED are terminal for automatic handoff so replaying an old
        Checkout Session cannot resurrect operator-revoked or expired access.
        """
        if not package_id or not payment_ref:
            return PAYMENT_MISSING
        current = int(time.time()) if now is None else int(now)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT status, expires_at
                FROM entitlements
                WHERE package_id=? AND payment_ref=?
                ORDER BY issued_at DESC, rowid DESC
                LIMIT 1
                """,
                (package_id, payment_ref),
            ).fetchone()
        if row is None:
            return PAYMENT_MISSING
        if row["status"] != "active":
            return PAYMENT_REVOKED
        expires_at = row["expires_at"]
        if expires_at is not None and int(expires_at) <= current:
            return PAYMENT_EXPIRED
        return PAYMENT_ACTIVE

    def authorize_payment(
        self,
        *,
        package_id: str,
        payment_ref: str | None,
        now: int | None = None,
    ) -> bool:
        return self.payment_state(package_id=package_id, payment_ref=payment_ref, now=now) == PAYMENT_ACTIVE

    def revoke(self, token: str) -> bool:
        digest = token_hash(token)
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE entitlements
                SET status='revoked', revoked_at=?
                WHERE token_hash=? AND status='active'
                """,
                (now, digest),
            )
        return cursor.rowcount == 1

    def revoke_payment(self, *, package_id: str, payment_ref: str) -> int:
        if not package_id or not payment_ref:
            return 0
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE entitlements
                SET status='revoked', revoked_at=?
                WHERE package_id=? AND payment_ref=? AND status='active'
                """,
                (now, package_id, payment_ref),
            )
        return int(cursor.rowcount)

    def list_for_package(self, package_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT package_id, buyer_ref, payment_ref, status, issued_at, expires_at, revoked_at,
                       substr(token_hash, 1, 12) AS token_hash_prefix
                FROM entitlements
                WHERE package_id=?
                ORDER BY issued_at DESC
                """,
                (package_id,),
            ).fetchall()
        return [dict(row) for row in rows]
