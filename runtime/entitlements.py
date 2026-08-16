from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path


TOKEN_PREFIX = "webai_"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class EntitlementStore:
    """Minimal persistent bearer-entitlement store for manual paid-hosted v0.

    Only a SHA-256 digest of the high-entropy bearer token is stored. The plaintext
    token is returned exactly once at issuance time and must be handed to the buyer
    out-of-band after the operator verifies payment.
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
                CREATE TABLE IF NOT EXISTS entitlements (
                    token_hash TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL,
                    buyer_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    revoked_at INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entitlements_package ON entitlements(package_id, status)"
            )

    def issue(self, *, package_id: str, buyer_ref: str = "", expires_at: int | None = None) -> str:
        if not package_id:
            raise ValueError("package_id is required")
        now = int(time.time())
        if expires_at is not None and expires_at <= now:
            raise ValueError("expires_at must be in the future")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        digest = token_hash(token)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO entitlements
                (token_hash, package_id, buyer_ref, status, issued_at, expires_at, revoked_at)
                VALUES (?, ?, ?, 'active', ?, ?, NULL)
                """,
                (digest, package_id, buyer_ref, now, expires_at),
            )
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

    def list_for_package(self, package_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT package_id, buyer_ref, status, issued_at, expires_at, revoked_at,
                       substr(token_hash, 1, 12) AS token_hash_prefix
                FROM entitlements
                WHERE package_id=?
                ORDER BY issued_at DESC
                """,
                (package_id,),
            ).fetchall()
        return [dict(row) for row in rows]
