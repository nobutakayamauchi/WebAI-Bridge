from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from http.cookies import SimpleCookie

from live_acceptance import SLUG_RE, UrllibRequester, normalize_base_url, _require_status


def _require_free_hosted_contract(config: dict, slug: str) -> dict:
    if config.get("slug") != slug:
        raise RuntimeError("free acceptance returned the wrong package slug")
    if config.get("status") not in {"dogfood", "active"}:
        raise RuntimeError("free dogfood package must be dogfood or active")

    access = config.get("access") or {}
    if access.get("mode") != "FREE":
        raise RuntimeError("free acceptance requires access.mode=FREE")
    if int(access.get("price_amount_minor", 0) or 0) != 0:
        raise RuntimeError("free acceptance requires zero access price")

    delivery = config.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise RuntimeError("free dogfood package must use the current Hosted-only runtime")

    payers = config.get("allowed_payer_modes") or []
    if "BYOK" not in payers:
        raise RuntimeError("free external dogfood requires BYOK to be allowed")
    return access


def _opaque_cookie_header(response, slug: str) -> str:
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


def run_free_acceptance(
    requester,
    *,
    base_url: str,
    slug: str,
    provider_call: bool = False,
    provider_key: str | None = None,
    allow_local_http: bool = False,
) -> dict:
    base = normalize_base_url(base_url, allow_local_http=allow_local_http)
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("invalid package slug")
    if provider_call and not provider_key:
        raise ValueError("provider_key is required when provider_call=True")

    evidence: list[dict] = []

    health = requester.request("GET", f"{base}/health")
    _require_status(health, 200, "health")
    health_json = health.json()
    if health_json.get("status") != "ok":
        raise RuntimeError("health response did not report status=ok")
    evidence.append({
        "gate": "health",
        "status": "PASS",
        "pricing_version": health_json.get("pricing_version"),
    })

    page = requester.request("GET", f"{base}/a/{slug}")
    _require_status(page, 200, "free dogfood page")
    evidence.append({"gate": "free_hosted_page", "status": "PASS"})

    config_response = requester.request("GET", f"{base}/apps/{slug}/public-config")
    _require_status(config_response, 200, "free public config")
    config = config_response.json()
    access = _require_free_hosted_contract(config, slug)
    evidence.append({
        "gate": "free_hosted_contract",
        "status": "PASS",
        "display_name": config.get("display_name"),
        "package_status": config.get("status"),
        "access_mode": access.get("mode"),
        "delivery_mode": (config.get("delivery") or {}).get("mode"),
        "byok_allowed": True,
    })

    provider_evidence = {"gate": "live_provider", "status": "SKIPPED"}
    if provider_call:
        session = requester.request(
            "POST",
            f"{base}/api/byok/session",
            json_body={"slug": slug, "api_key": provider_key or ""},
        )
        _require_status(session, 200, "ephemeral BYOK session creation")
        session_payload = session.json()
        if session_payload.get("storage") != "PROCESS_MEMORY_ONLY" or session_payload.get("browser_api_key_retained") is not False:
            raise RuntimeError("BYOK session did not report process-memory-only / no-browser-key retention")
        cookie_header = _opaque_cookie_header(session, slug)
        provider_key = None

        status = requester.request(
            "GET",
            f"{base}/api/byok/session/{slug}",
            headers={"Cookie": cookie_header},
        )
        _require_status(status, 200, "ephemeral BYOK session status")
        if status.json().get("connected") is not True:
            raise RuntimeError("ephemeral BYOK session was not connected after creation")
        evidence.append({"gate": "ephemeral_byok_session", "status": "PASS", "browser_api_key_retained": False})

        chat = requester.request(
            "POST",
            f"{base}/api/chat",
            headers={"Cookie": cookie_header},
            json_body={
                "slug": slug,
                "message": "Reply briefly to confirm this live WebAI Bridge free dogfood request.",
                "history": [],
                "payer_mode": "BYOK",
            },
            timeout=60.0,
        )
        _require_status(chat, 200, "live free BYOK provider call")
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
            headers={"Cookie": cookie_header},
        )
        _require_status(forgotten, 200, "ephemeral BYOK session cleanup")
    evidence.append(provider_evidence)

    return {
        "status": "PASS",
        "profile": "FREE_BYOK_DOGFOOD",
        "base_url": base,
        "slug": slug,
        "provider_call": provider_call,
        "secrets_returned": False,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run external free-BYOK WebAI Bridge dogfood without printing secrets")
    parser.add_argument("--base-url", required=True, help="Public HTTPS origin")
    parser.add_argument("--slug", default="migration-fixture-ai")
    parser.add_argument("--provider-call", action="store_true", help="Make one real BYOK provider request after perimeter checks")
    parser.add_argument("--allow-local-http", action="store_true", help="Allow HTTP only for localhost acceptance")
    args = parser.parse_args()

    provider_key = None
    if args.provider_call:
        provider_key = getpass.getpass("Provider API key for one live BYOK dogfood call (hidden): ").strip()

    try:
        result = run_free_acceptance(
            UrllibRequester(),
            base_url=args.base_url,
            slug=args.slug,
            provider_call=args.provider_call,
            provider_key=provider_key,
            allow_local_http=args.allow_local_http,
        )
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "FAIL", "profile": "FREE_BYOK_DOGFOOD", "error": str(exc), "secrets_returned": False}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
