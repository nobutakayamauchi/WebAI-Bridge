from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Mapping
from urllib.parse import urlparse

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_RESPONSE_BYTES = 2_000_000


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict:
        try:
            value = json.loads(self.body.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Response is not valid UTF-8 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Expected a JSON object response")
        return value


class UrllibRequester:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: dict | None = None,
        timeout: float = 30.0,
    ) -> Response:
        body = None
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url=url, data=body, headers=request_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as raw:
                payload = raw.read(MAX_RESPONSE_BYTES + 1)
                status = int(raw.status)
                response_headers = {key.lower(): value for key, value in raw.headers.items()}
        except urllib.error.HTTPError as exc:
            payload = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
            response_headers = {key.lower(): value for key, value in (exc.headers.items() if exc.headers else [])}
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Response exceeded acceptance body limit")
        return Response(status=status, headers=response_headers, body=payload)


def normalize_base_url(value: str, *, allow_local_http: bool = False) -> str:
    parsed = urlparse(value.strip())
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("base URL must not contain params, query, or fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base URL contains an invalid port") from exc
    host = (parsed.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https":
        if not (allow_local_http and local and parsed.scheme == "http"):
            raise ValueError("live acceptance requires HTTPS; HTTP override is localhost-only")
    if not host:
        raise ValueError("base URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("base URL must not embed credentials")
    path = parsed.path.rstrip("/")
    if path:
        raise ValueError("base URL must be an origin without a path")
    netloc = parsed.netloc
    return f"{parsed.scheme}://{netloc}"


def _require_status(response: Response, expected: int, label: str) -> None:
    if response.status != expected:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("detail") or "")[:200]
        except Exception:
            detail = response.body[:200].decode("utf-8", errors="replace")
        raise RuntimeError(f"{label}: expected HTTP {expected}, got {response.status}: {detail}")


def _require_paid_page_headers(response: Response) -> None:
    required_exact = {
        "referrer-policy": "no-referrer",
        "x-frame-options": "DENY",
        "x-content-type-options": "nosniff",
    }
    for key, expected in required_exact.items():
        actual = response.headers.get(key, "")
        if actual.lower() != expected.lower():
            raise RuntimeError(f"paid buyer page missing/invalid {key}: {actual!r}")
    cache_control = response.headers.get("cache-control", "").lower()
    if "no-store" not in cache_control:
        raise RuntimeError("paid buyer page must send Cache-Control: no-store")
    csp = response.headers.get("content-security-policy", "")
    for required in ["default-src 'none'", "connect-src 'self'", "frame-ancestors 'none'"]:
        if required not in csp:
            raise RuntimeError(f"paid buyer page CSP missing: {required}")


def _require_paid_hosted_contract(config: dict, slug: str) -> dict:
    if config.get("slug") != slug:
        raise RuntimeError("authorized config returned the wrong package slug")
    if config.get("status") != "active":
        raise RuntimeError("live paid package must report status=active")

    access = config.get("access") or {}
    if access.get("mode") not in {"BUY_ONCE", "SUBSCRIPTION"}:
        raise RuntimeError("live acceptance only supports BUY_ONCE/SUBSCRIPTION paid packages")
    if access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise RuntimeError("live paid package must report ENTITLEMENT_ENFORCED")

    delivery = config.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise RuntimeError("live paid package must be current Hosted-only runtime")

    if config.get("allowed_payer_modes") != ["BYOK"] or config.get("default_payer_mode") != "BYOK":
        raise RuntimeError("live paid v0 package must be BYOK-only")
    return access


def _opaque_cookie_header(response: Response, slug: str) -> str:
    raw = response.headers.get("set-cookie", "")
    cookie = SimpleCookie()
    cookie.load(raw)
    name = f"webai_byok_{slug}"
    morsel = cookie.get(name)
    if morsel is None or not morsel.value.startswith("byok_"):
        raise RuntimeError("BYOK session did not return the expected opaque HttpOnly cookie")
    lower = raw.lower()
    if "httponly" not in lower or "secure" not in lower or "samesite=strict" not in lower:
        raise RuntimeError("BYOK session cookie is missing Secure/HttpOnly/SameSite=Strict")
    return f"{name}={morsel.value}"


def run_acceptance(
    requester,
    *,
    base_url: str,
    slug: str,
    entitlement: str,
    provider_call: bool = False,
    provider_key: str | None = None,
    allow_local_http: bool = False,
) -> dict:
    base = normalize_base_url(base_url, allow_local_http=allow_local_http)
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("invalid package slug")
    if not entitlement.startswith("webai_") or len(entitlement) < 24:
        raise ValueError("entitlement does not look like a WebAI buyer bearer token")
    if provider_call and not provider_key:
        raise ValueError("provider_key is required when provider_call=True")

    evidence: list[dict] = []

    health = requester.request("GET", f"{base}/health")
    _require_status(health, 200, "health")
    health_json = health.json()
    if health_json.get("status") != "ok":
        raise RuntimeError("health response did not report status=ok")
    evidence.append({"gate": "health", "status": "PASS", "pricing_version": health_json.get("pricing_version")})

    page = requester.request("GET", f"{base}/a/{slug}")
    _require_status(page, 200, "paid buyer page")
    _require_paid_page_headers(page)
    evidence.append({"gate": "paid_page_https_headers", "status": "PASS"})

    denied = requester.request("GET", f"{base}/apps/{slug}/public-config")
    _require_status(denied, 401, "unauthorized paid config")
    evidence.append({"gate": "missing_entitlement_denied", "status": "PASS"})

    authorized = requester.request(
        "GET",
        f"{base}/apps/{slug}/public-config",
        headers={"X-WebAI-Entitlement": entitlement},
    )
    _require_status(authorized, 200, "authorized paid config")
    config = authorized.json()
    access = _require_paid_hosted_contract(config, slug)
    evidence.append({
        "gate": "buyer_entitlement_contract", "status": "PASS",
        "display_name": config.get("display_name"),
        "access_mode": access.get("mode"),
        "commercial_enforcement": access.get("commercial_enforcement"),
        "delivery_mode": (config.get("delivery") or {}).get("mode"),
        "payer_mode": config.get("default_payer_mode"),
    })

    provider_evidence = {"gate": "live_provider", "status": "SKIPPED"}
    if provider_call:
        session = requester.request(
            "POST",
            f"{base}/api/byok/session",
            headers={"X-WebAI-Entitlement": entitlement},
            json_body={"slug": slug, "api_key": provider_key or ""},
        )
        _require_status(session, 200, "paid ephemeral BYOK session creation")
        session_payload = session.json()
        if session_payload.get("storage") != "PROCESS_MEMORY_ONLY" or session_payload.get("browser_api_key_retained") is not False:
            raise RuntimeError("paid BYOK session did not report process-memory-only / no-browser-key retention")
        cookie_header = _opaque_cookie_header(session, slug)
        provider_key = None

        status = requester.request(
            "GET",
            f"{base}/api/byok/session/{slug}",
            headers={"X-WebAI-Entitlement": entitlement, "Cookie": cookie_header},
        )
        _require_status(status, 200, "paid ephemeral BYOK session status")
        if status.json().get("connected") is not True:
            raise RuntimeError("paid ephemeral BYOK session was not connected after creation")
        evidence.append({"gate": "ephemeral_byok_session", "status": "PASS", "browser_api_key_retained": False})

        chat = requester.request(
            "POST",
            f"{base}/api/chat",
            headers={
                "X-WebAI-Entitlement": entitlement,
                "Cookie": cookie_header,
            },
            json_body={
                "slug": slug,
                "message": "Reply briefly to confirm this live WebAI Bridge request.",
                "history": [],
                "payer_mode": "BYOK",
            },
            timeout=60.0,
        )
        _require_status(chat, 200, "live BYOK provider call")
        payload = chat.json()
        text = str(payload.get("text") or "")
        if not text.strip():
            raise RuntimeError("live provider returned empty text")
        if payload.get("payer_mode") != "BYOK":
            raise RuntimeError("live provider response did not preserve BYOK payer mode")
        provider_evidence = {
            "gate": "live_provider",
            "status": "PASS",
            "model": payload.get("model"),
            "payer_mode": payload.get("payer_mode"),
            "response_chars": len(text),
            "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

        forgotten = requester.request(
            "DELETE",
            f"{base}/api/byok/session/{slug}",
            headers={"X-WebAI-Entitlement": entitlement, "Cookie": cookie_header},
        )
        _require_status(forgotten, 200, "paid ephemeral BYOK session cleanup")
    evidence.append(provider_evidence)

    return {
        "status": "PASS",
        "base_url": base,
        "slug": slug,
        "provider_call": provider_call,
        "secrets_returned": False,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live WebAI Bridge paid-hosted acceptance without printing secrets")
    parser.add_argument("--base-url", required=True, help="Public HTTPS origin, e.g. https://ai.example.com")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--provider-call", action="store_true", help="Make one real BYOK provider request after perimeter checks")
    parser.add_argument("--allow-local-http", action="store_true", help="Allow HTTP only for localhost acceptance")
    args = parser.parse_args()

    entitlement = getpass.getpass("Buyer entitlement (hidden): ").strip()
    provider_key = None
    if args.provider_call:
        provider_key = getpass.getpass("Provider API key for one live BYOK call (hidden): ").strip()

    try:
        result = run_acceptance(
            UrllibRequester(),
            base_url=args.base_url,
            slug=args.slug,
            entitlement=entitlement,
            provider_call=args.provider_call,
            provider_key=provider_key,
            allow_local_http=args.allow_local_http,
        )
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_returned": False}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
