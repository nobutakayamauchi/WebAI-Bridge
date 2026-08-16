from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ByokSession:
    token: str
    package_id: str
    api_key: str
    expires_at: float


class ByokSessionStore:
    """Short-lived BYOK credentials held only in this Python process memory.

    The opaque token is safe to place in an HttpOnly cookie; the provider API key
    never leaves this store after the initial session-creation request. This is a
    single-process v0 store by design. Restarting the process forgets all sessions.
    """

    def __init__(self, *, ttl_seconds: int = 900, max_sessions: int = 1000):
        if ttl_seconds < 60 or ttl_seconds > 3600:
            raise ValueError("ttl_seconds must be between 60 and 3600")
        if max_sessions < 1 or max_sessions > 100_000:
            raise ValueError("max_sessions must be between 1 and 100000")
        self.ttl_seconds = int(ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._sessions: dict[str, ByokSession] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> None:
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)

    def create(self, *, package_id: str, api_key: str, now: float | None = None) -> ByokSession:
        package_id = package_id.strip()
        api_key = api_key.strip()
        if not package_id:
            raise ValueError("package_id is required")
        if len(api_key) < 8 or len(api_key) > 4096:
            raise ValueError("provider API key length is invalid")
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune_locked(timestamp)
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("BYOK session capacity reached")
            token = "byok_" + secrets.token_urlsafe(32)
            session = ByokSession(
                token=token,
                package_id=package_id,
                api_key=api_key,
                expires_at=timestamp + self.ttl_seconds,
            )
            self._sessions[token] = session
            return session

    def resolve(self, *, package_id: str, token: str | None, now: float | None = None) -> str | None:
        token = (token or "").strip()
        if not token:
            return None
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune_locked(timestamp)
            session = self._sessions.get(token)
            if session is None or session.package_id != package_id:
                return None
            return session.api_key

    def status(self, *, package_id: str, token: str | None, now: float | None = None) -> dict:
        token = (token or "").strip()
        timestamp = time.time() if now is None else float(now)
        with self._lock:
            self._prune_locked(timestamp)
            session = self._sessions.get(token) if token else None
            if session is None or session.package_id != package_id:
                return {"connected": False, "expires_in_seconds": 0}
            return {
                "connected": True,
                "expires_in_seconds": max(0, int(session.expires_at - timestamp)),
            }

    def forget(self, token: str | None) -> bool:
        token = (token or "").strip()
        if not token:
            return False
        with self._lock:
            return self._sessions.pop(token, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
