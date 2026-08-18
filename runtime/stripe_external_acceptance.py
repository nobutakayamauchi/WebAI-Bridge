from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from stripe_checkout import StripeCheckoutError, validate_payment_link_binding

REQUIRED_WEBHOOK_EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
}
RUNNABLE_STATUSES = {"dogfood", "active"}


class StripeExternalAcceptanceError(RuntimeError):
    pass


def expected_completion_url(*, domain: str, slug: str) -> str:
    clean_domain = domain.strip().lower().rstrip(".")
    if not clean_domain or "/" in clean_domain or ":" in clean_domain:
        raise StripeExternalAcceptanceError("domain must be a bare public hostname")
    return f"https://{clean_domain}/checkout/complete/{slug}?session_id={{CHECKOUT_SESSION_ID}}"


def expected_webhook_url(*, domain: str) -> str:
    clean_domain = domain.strip().lower().rstrip(".")
    if not clean_domain or "/" in clean_domain or ":" in clean_domain:
        raise StripeExternalAcceptanceError("domain must be a bare public hostname")
    return f"https://{clean_domain}/webhooks/stripe"


def _stripe_get(*, secret_key: str, path: str, label: str, timeout: float = 10.0) -> dict:
    if not secret_key.startswith(("sk_", "rk_")):
        raise StripeExternalAcceptanceError("Stripe server/restricted API key is not configured")
    request = Request(
        "https://api.stripe.com" + path,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "User-Agent": "WebAI-Bridge/fixed-domain-external-acceptance-v1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise StripeExternalAcceptanceError(f"{label} lookup failed: HTTP {exc.code}") from None
    except URLError as exc:
        raise StripeExternalAcceptanceError(f"{label} lookup failed: {exc.reason}") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StripeExternalAcceptanceError(f"{label} response was not valid JSON") from None
    if not isinstance(payload, dict):
        raise StripeExternalAcceptanceError(f"{label} response was not an object")
    return payload


def _list_all(*, secret_key: str, path: str, label: str, timeout: float = 10.0) -> list[dict]:
    items: list[dict] = []
    starting_after: str | None = None
    while True:
        query = {"limit": 100}
        if starting_after:
            query["starting_after"] = starting_after
        payload = _stripe_get(
            secret_key=secret_key,
            path=path + "?" + urlencode(query),
            label=label,
            timeout=timeout,
        )
        page = payload.get("data")
        if not isinstance(page, list):
            raise StripeExternalAcceptanceError(f"{label} response has no data list")
        dict_page = [item for item in page if isinstance(item, dict)]
        items.extend(dict_page)
        if not payload.get("has_more"):
            return items
        if not dict_page or not isinstance(dict_page[-1].get("id"), str):
            raise StripeExternalAcceptanceError(f"{label} pagination could not advance")
        starting_after = dict_page[-1]["id"]


def list_payment_links(*, secret_key: str, timeout: float = 10.0) -> list[dict]:
    return _list_all(secret_key=secret_key, path="/v1/payment_links", label="Stripe Payment Links", timeout=timeout)


def list_webhook_endpoints(*, secret_key: str, timeout: float = 10.0) -> list[dict]:
    return _list_all(secret_key=secret_key, path="/v1/webhook_endpoints", label="Stripe webhook endpoints", timeout=timeout)


def retrieve_payment_link_line_items(*, secret_key: str, payment_link_id: str, timeout: float = 10.0) -> list[dict]:
    if not payment_link_id.startswith("plink_"):
        raise StripeExternalAcceptanceError("Stripe Payment Link id is invalid")
    payload = _stripe_get(
        secret_key=secret_key,
        path="/v1/payment_links/" + quote(payment_link_id, safe="") + "/line_items?limit=100",
        label="Stripe Payment Link line items",
        timeout=timeout,
    )
    data = payload.get("data")
    if not isinstance(data, list):
        raise StripeExternalAcceptanceError("Stripe Payment Link line items response has no data list")
    return [item for item in data if isinstance(item, dict)]


def validate_payment_link_external_contract(
    *,
    payment_link: dict,
    line_items: list[dict],
    app_config: dict,
    domain: str,
    require_live: bool,
) -> list[str]:
    findings: list[str] = []
    try:
        validate_payment_link_binding(payment_link=payment_link, app_config=app_config)
    except StripeCheckoutError as exc:
        findings.append("PAYMENT_LINK_BINDING: " + str(exc))

    if payment_link.get("active") is not True:
        findings.append("PAYMENT_LINK_INACTIVE")
    if require_live and payment_link.get("livemode") is not True:
        findings.append("PAYMENT_LINK_NOT_LIVE")

    slug = str(app_config.get("slug") or "")
    expected_redirect = expected_completion_url(domain=domain, slug=slug)
    after_completion = payment_link.get("after_completion") or {}
    redirect = after_completion.get("redirect") or {}
    if after_completion.get("type") != "redirect" or redirect.get("url") != expected_redirect:
        findings.append("PAYMENT_LINK_REDIRECT_MISMATCH")

    access = app_config.get("access") or {}
    expected_currency = str(access.get("currency") or "").lower()
    expected_amount = int(access.get("price_amount_minor") or 0)
    actual_amount = 0
    saw_line_item = False
    for item in line_items:
        price = item.get("price") or {}
        quantity = int(item.get("quantity") or 0)
        unit_amount = price.get("unit_amount")
        if not isinstance(unit_amount, int) or quantity <= 0:
            findings.append("PAYMENT_LINK_LINE_ITEM_AMOUNT_INVALID")
            continue
        saw_line_item = True
        if str(price.get("currency") or "").lower() != expected_currency:
            findings.append("PAYMENT_LINK_CURRENCY_MISMATCH")
        if price.get("type") not in {None, "one_time"}:
            findings.append("PAYMENT_LINK_RECURRING_PRICE_FOR_BUY_ONCE")
        actual_amount += unit_amount * quantity
    if not saw_line_item:
        findings.append("PAYMENT_LINK_HAS_NO_USABLE_LINE_ITEMS")
    elif actual_amount != expected_amount:
        findings.append("PAYMENT_LINK_AMOUNT_MISMATCH")
    return findings


def validate_webhook_external_contract(*, endpoints: list[dict], domain: str, require_live: bool) -> list[str]:
    target = expected_webhook_url(domain=domain)
    matches = [endpoint for endpoint in endpoints if endpoint.get("url") == target]
    if not matches:
        return ["FIXED_DOMAIN_WEBHOOK_ENDPOINT_MISSING"]
    findings: list[str] = []
    acceptable = False
    for endpoint in matches:
        events = set(endpoint.get("enabled_events") or [])
        status_ok = endpoint.get("status") == "enabled"
        live_ok = not require_live or endpoint.get("livemode") is True
        events_ok = REQUIRED_WEBHOOK_EVENTS.issubset(events) or "*" in events
        if status_ok and live_ok and events_ok:
            acceptable = True
            break
        if not status_ok:
            findings.append("FIXED_DOMAIN_WEBHOOK_DISABLED")
        if not live_ok:
            findings.append("FIXED_DOMAIN_WEBHOOK_NOT_LIVE")
        if not events_ok:
            findings.append("FIXED_DOMAIN_WEBHOOK_EVENTS_INCOMPLETE")
    if not acceptable and not findings:
        findings.append("FIXED_DOMAIN_WEBHOOK_INVALID")
    return sorted(set(findings))


def load_active_buy_once_packages(config_dir: Path) -> list[dict]:
    packages: list[dict] = []
    for path in sorted(config_dir.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise StripeExternalAcceptanceError(f"package config is not a regular file: {path}")
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StripeExternalAcceptanceError(f"cannot read package config {path.name}: {exc}") from None
        if package.get("status") not in RUNNABLE_STATUSES:
            continue
        if (package.get("access") or {}).get("mode") != "BUY_ONCE":
            continue
        packages.append(package)
    return packages


def run_external_acceptance(
    *,
    domain: str,
    config_dir: Path,
    secret_key: str,
    require_live: bool = True,
    timeout: float = 10.0,
) -> dict:
    packages = load_active_buy_once_packages(config_dir)
    findings: list[dict] = []
    if not packages:
        findings.append({"code": "NO_ACTIVE_BUY_ONCE_PACKAGES"})

    links = list_payment_links(secret_key=secret_key, timeout=timeout)
    links_by_url = {str(link.get("url") or ""): link for link in links if link.get("url")}
    checked: list[str] = []
    for package in packages:
        slug = str(package.get("slug") or "")
        checked.append(slug)
        expected_url = str((((package.get("access") or {}).get("checkout") or {}).get("payment_link_url") or ""))
        payment_link = links_by_url.get(expected_url)
        if not payment_link:
            findings.append({"code": "PAYMENT_LINK_URL_NOT_FOUND", "package_id": slug})
            continue
        try:
            line_items = retrieve_payment_link_line_items(
                secret_key=secret_key,
                payment_link_id=str(payment_link.get("id") or ""),
                timeout=timeout,
            )
            package_findings = validate_payment_link_external_contract(
                payment_link=payment_link,
                line_items=line_items,
                app_config=package,
                domain=domain,
                require_live=require_live,
            )
        except StripeExternalAcceptanceError as exc:
            package_findings = ["PAYMENT_LINK_LOOKUP: " + str(exc)]
        findings.extend({"code": finding, "package_id": slug} for finding in package_findings)

    endpoints = list_webhook_endpoints(secret_key=secret_key, timeout=timeout)
    findings.extend(
        {"code": finding}
        for finding in validate_webhook_external_contract(
            endpoints=endpoints,
            domain=domain,
            require_live=require_live,
        )
    )
    return {
        "ok": not findings,
        "status": "PASS" if not findings else "FAIL",
        "domain": domain.strip().lower().rstrip("."),
        "checked_packages": checked,
        "required_webhook_url": expected_webhook_url(domain=domain),
        "required_webhook_events": sorted(REQUIRED_WEBHOOK_EVENTS),
        "findings": findings,
        "secrets_in_output": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate live Stripe bindings for the fixed-domain Hosted v1 acceptance gate without coupling service restart to Stripe availability"
    )
    parser.add_argument("--domain", required=True)
    parser.add_argument("--config-dir", default=os.getenv("WEB_AI_CONFIG_DIR", "/var/lib/webai-bridge/apps"))
    parser.add_argument("--allow-test-mode", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    secret_key = os.getenv("WEB_AI_STRIPE_SECRET_KEY", "")
    try:
        result = run_external_acceptance(
            domain=args.domain,
            config_dir=Path(args.config_dir),
            secret_key=secret_key,
            require_live=not args.allow_test_mode,
            timeout=args.timeout,
        )
    except StripeExternalAcceptanceError as exc:
        result = {
            "ok": False,
            "status": "FAIL",
            "domain": args.domain.strip().lower().rstrip("."),
            "checked_packages": [],
            "findings": [{"code": "STRIPE_EXTERNAL_ACCEPTANCE_ERROR", "detail": str(exc)}],
            "secrets_in_output": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
