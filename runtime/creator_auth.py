from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import stat
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE_NAME = "webai_creator_session"
COOKIE_VERSION = 1
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5


@dataclass(frozen=True)
class CreatorAuthConfig:
    password: str
    session_secret: str
    session_ttl_seconds: int
    auth_id: str


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def creator_auth_enabled(env: dict[str, str] | os._Environ[str] | None = None) -> bool:
    source = os.environ if env is None else env
    return _truthy(source.get("WEB_AI_CREATOR_AUTH_ENABLED"))


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _secret_file_findings(*, env: dict[str, str], env_name: str, label: str, runtime_dir: Path, min_chars: int) -> tuple[list[dict], str | None]:
    findings: list[dict] = []
    raw = (env.get(env_name) or "").strip()
    code = label.upper().replace(" ", "_")
    if not raw:
        findings.append({"code": f"{code}_FILE_MISSING", "scope": "creator-auth", "message": f"{env_name} must point to a private creator-auth secret file"})
        return findings, None
    path = Path(raw)
    if not path.is_absolute():
        findings.append({"code": f"{code}_FILE_NOT_ABSOLUTE", "scope": "creator-auth", "message": f"{env_name} must be an absolute path"})
        return findings, None
    resolved = path.resolve(strict=False)
    if _inside(resolved, runtime_dir):
        findings.append({"code": f"{code}_FILE_INSIDE_RUNTIME", "scope": "creator-auth", "message": f"{env_name} must live outside the Git/runtime tree"})
    if path.is_symlink() or not path.exists() or not path.is_file():
        findings.append({"code": f"{code}_FILE_UNSAFE", "scope": "creator-auth", "message": f"{env_name} must be a regular non-symlink file"})
        return findings, None
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        findings.append({"code": f"{code}_FILE_PERMISSIONS_TOO_OPEN", "scope": "creator-auth", "message": f"{env_name} must be owner-only (0600)"})
    parent = path.parent
    if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o002:
        findings.append({"code": f"{code}_PARENT_WORLD_WRITABLE", "scope": "creator-auth", "message": f"Parent directory for {env_name} must not be world-writable"})
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        findings.append({"code": f"{code}_FILE_UNREADABLE", "scope": "creator-auth", "message": f"Could not read {env_name}: {exc}"})
        return findings, None
    if len(value) < min_chars:
        findings.append({"code": f"{code}_TOO_SHORT", "scope": "creator-auth", "message": f"{label} must contain at least {min_chars} characters"})
    if len(value) > 4096:
        findings.append({"code": f"{code}_TOO_LONG", "scope": "creator-auth", "message": f"{label} is unexpectedly large"})
    return findings, value


def creator_auth_findings(*, env: dict[str, str] | None = None, runtime_dir: Path) -> list[dict]:
    source = dict(os.environ if env is None else env)
    findings: list[dict] = []
    studio_enabled = _truthy(source.get("WEB_AI_STUDIO_ENABLED"))
    auth_enabled = _truthy(source.get("WEB_AI_CREATOR_AUTH_ENABLED"))
    if not studio_enabled:
        return findings
    if not auth_enabled:
        findings.append({
            "code": "CREATOR_AUTH_DISABLED",
            "scope": "creator-auth",
            "message": "Public Creator Studio requires WEB_AI_CREATOR_AUTH_ENABLED=1",
        })
        return findings

    password_findings, _ = _secret_file_findings(
        env=source,
        env_name="WEB_AI_CREATOR_PASSWORD_FILE",
        label="creator password",
        runtime_dir=runtime_dir,
        min_chars=24,
    )
    session_findings, _ = _secret_file_findings(
        env=source,
        env_name="WEB_AI_CREATOR_SESSION_SECRET_FILE",
        label="creator session secret",
        runtime_dir=runtime_dir,
        min_chars=32,
    )
    findings.extend(password_findings)
    findings.extend(session_findings)

    ttl_raw = (source.get("WEB_AI_CREATOR_SESSION_TTL_SECONDS") or str(DEFAULT_SESSION_TTL_SECONDS)).strip()
    try:
        ttl = int(ttl_raw)
    except ValueError:
        ttl = 0
    if ttl < 300 or ttl > MAX_SESSION_TTL_SECONDS:
        findings.append({
            "code": "CREATOR_SESSION_TTL_INVALID",
            "scope": "creator-auth",
            "message": f"WEB_AI_CREATOR_SESSION_TTL_SECONDS must be between 300 and {MAX_SESSION_TTL_SECONDS}",
        })
    return findings


def load_creator_auth_config(*, env: dict[str, str] | None = None, runtime_dir: Path) -> CreatorAuthConfig:
    source = dict(os.environ if env is None else env)
    findings = creator_auth_findings(env=source, runtime_dir=runtime_dir)
    if findings:
        raise RuntimeError("Creator Studio authentication is not safely configured: " + "; ".join(item["code"] for item in findings))
    _, password = _secret_file_findings(
        env=source,
        env_name="WEB_AI_CREATOR_PASSWORD_FILE",
        label="creator password",
        runtime_dir=runtime_dir,
        min_chars=24,
    )
    _, session_secret = _secret_file_findings(
        env=source,
        env_name="WEB_AI_CREATOR_SESSION_SECRET_FILE",
        label="creator session secret",
        runtime_dir=runtime_dir,
        min_chars=32,
    )
    ttl = int(source.get("WEB_AI_CREATOR_SESSION_TTL_SECONDS") or DEFAULT_SESSION_TTL_SECONDS)
    assert password is not None and session_secret is not None
    auth_id = hashlib.sha256(password.encode("utf-8")).hexdigest()[:24]
    return CreatorAuthConfig(password=password, session_secret=session_secret, session_ttl_seconds=ttl, auth_id=auth_id)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_creator_session(*, config: CreatorAuthConfig, now: int | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = json.dumps(
        {"v": COOKIE_VERSION, "iat": issued, "exp": issued + config.session_ttl_seconds, "auth_id": config.auth_id},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64url(payload)
    signature = hmac.new(config.session_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return encoded + "." + _b64url(signature)


def verify_creator_session(*, config: CreatorAuthConfig, cookie: str | None, now: int | None = None) -> bool:
    if not cookie or "." not in cookie:
        return False
    encoded, supplied_sig = cookie.split(".", 1)
    expected_sig = _b64url(hmac.new(config.session_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected_sig, supplied_sig):
        return False
    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    current = int(time.time() if now is None else now)
    if payload.get("v") != COOKIE_VERSION or payload.get("auth_id") != config.auth_id:
        return False
    issued = payload.get("iat")
    expires = payload.get("exp")
    if not isinstance(issued, int) or not isinstance(expires, int):
        return False
    if issued > current + 60 or expires <= current or expires - issued > MAX_SESSION_TTL_SECONDS:
        return False
    return True


def password_matches(*, config: CreatorAuthConfig, supplied: str) -> bool:
    supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(config.password.encode("utf-8")).digest()
    return hmac.compare_digest(supplied_digest, expected_digest)


def _secure_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    return response


def _login_html(*, error: str = "", next_path: str = "/studio") -> str:
    message = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Creator Login</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f5f5f7;color:#111}}main{{max-width:520px;margin:auto;padding:48px 24px}}.card{{background:#fff;border:1px solid #ddd;border-radius:20px;padding:26px;box-shadow:0 12px 40px rgba(0,0,0,.06)}}h1{{font-size:30px;margin:0 0 10px}}p{{line-height:1.6;color:#666}}label{{display:block;font-weight:700;margin:22px 0 8px}}input{{box-sizing:border-box;width:100%;font-size:18px;padding:15px 14px;border:1px solid #bbb;border-radius:12px}}button{{width:100%;margin-top:18px;border:0;border-radius:12px;padding:16px;background:#111;color:white;font-size:18px;font-weight:800}}.error{{color:#b42318;background:#fef3f2;border-radius:10px;padding:12px}}small{{display:block;margin-top:18px;color:#777;line-height:1.5}}</style></head><body><main><div class="card"><h1>Creator Studio</h1><p>作成者専用です。Creator access key を入力してください。</p>{message}<form method="post" action="/creator/login"><input type="hidden" name="next" value="{html.escape(next_path, quote=True)}"><label for="password">Creator access key</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus><button type="submit">Studioを開く</button></form><small>認証情報はURLへ入れません。HTTPS + HttpOnly session cookie でStudioだけを保護します。</small></div></main></body></html>"""


def _safe_next(value: str | None) -> str:
    return "/studio" if value != "/studio" else value


def install_creator_auth(base) -> dict:
    """Protect the Creator Studio on the public commercial_handoff surface.

    Buyer routes remain unchanged. Studio startup fails closed when Studio is
    enabled without private creator-auth material.
    """
    if not base.core.studio_enabled():
        return {"enabled": False, "mode": "STUDIO_DISABLED"}

    config = load_creator_auth_config(runtime_dir=base.core.BASE_DIR)
    failures: dict[str, deque[float]] = defaultdict(deque)

    def authenticated(request: Request) -> bool:
        return verify_creator_session(config=config, cookie=request.cookies.get(COOKIE_NAME))

    def enforce_login_rate_limit(request: Request) -> None:
        now = time.monotonic()
        key = request.client.host if request.client else "unknown"
        q = failures[key]
        while q and now - q[0] > LOGIN_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="Too many creator login failures; try again later")

    @base.app.middleware("http")
    async def creator_studio_auth_gate(request: Request, call_next):
        path = request.url.path
        protected = path == "/studio" or path.startswith("/api/studio/")
        if not protected:
            return await call_next(request)
        base.require_secure_transport(request)
        if not authenticated(request):
            if request.method == "GET" and path == "/studio":
                response = RedirectResponse(url="/creator/login?next=%2Fstudio", status_code=303)
                return _secure_headers(response)
            return _secure_headers(JSONResponse({"detail": "Creator authentication required"}, status_code=401))
        response = await call_next(request)
        return _secure_headers(response)

    @base.app.get("/creator/login")
    def creator_login_page(request: Request, next: str = "/studio"):
        base.require_secure_transport(request)
        target = _safe_next(next)
        if authenticated(request):
            return _secure_headers(RedirectResponse(url=target, status_code=303))
        return _secure_headers(HTMLResponse(_login_html(next_path=target)))

    @base.app.post("/creator/login")
    async def creator_login(request: Request):
        base.require_secure_transport(request)
        enforce_login_rate_limit(request)
        raw = await request.body()
        if len(raw) > 8192:
            raise HTTPException(status_code=413, detail="Creator login payload too large")
        content_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            raise HTTPException(status_code=415, detail="Creator login requires form encoding")
        parsed = parse_qs(raw.decode("utf-8", errors="strict"), keep_blank_values=True)
        supplied = (parsed.get("password") or [""])[0]
        target = _safe_next((parsed.get("next") or ["/studio"])[0])
        if not password_matches(config=config, supplied=supplied):
            key = request.client.host if request.client else "unknown"
            failures[key].append(time.monotonic())
            return _secure_headers(HTMLResponse(_login_html(error="Creator access key が違います。", next_path=target), status_code=401))
        key = request.client.host if request.client else "unknown"
        failures.pop(key, None)
        response = RedirectResponse(url=target, status_code=303)
        response.set_cookie(
            key=COOKIE_NAME,
            value=sign_creator_session(config=config),
            max_age=config.session_ttl_seconds,
            httponly=True,
            secure=not base.insecure_http_allowed(),
            samesite="strict",
            path="/",
        )
        return _secure_headers(response)

    @base.app.post("/creator/logout")
    def creator_logout(request: Request):
        base.require_secure_transport(request)
        response = RedirectResponse(url="/creator/login", status_code=303)
        response.delete_cookie(
            key=COOKIE_NAME,
            httponly=True,
            secure=not base.insecure_http_allowed(),
            samesite="strict",
            path="/",
        )
        return _secure_headers(response)

    return {
        "enabled": True,
        "mode": "SINGLE_CREATOR_PASSWORD_FILE_SIGNED_SESSION_V1",
        "session_ttl_seconds": config.session_ttl_seconds,
        "login_path": "/creator/login",
        "studio_path": "/studio",
        "cookie": "HTTPONLY_SECURE_SAMESITE_STRICT",
    }
