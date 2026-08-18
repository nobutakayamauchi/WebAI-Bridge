from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from commercial_preflight import commercial_env_file_findings, live_sale_secret_findings
from deployment_preflight import run_preflight

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_SURFACE = "commercial_bound:app"
CANONICAL_SURFACE = "commercial:app"


def run_bound_preflight(*, env: dict[str, str] | None = None) -> dict:
    source = dict(os.environ if env is None else env)
    findings: list[dict] = []
    actual_surface = (source.get("WEB_AI_ROUTE_SURFACE") or "").strip()
    if actual_surface != EXPECTED_SURFACE:
        findings.append({
            "code": "BOUND_ROUTE_SURFACE_INVALID",
            "scope": "deployment",
            "message": f"WEB_AI_ROUTE_SURFACE must be {EXPECTED_SURFACE} for buyer-only browser-bound runtime",
        })
    if not (BASE_DIR / "commercial_bound.py").is_file():
        findings.append({
            "code": "BOUND_ENTRYPOINT_MISSING",
            "scope": "deployment",
            "message": "commercial_bound.py is missing from the runtime directory",
        })

    canonical_env = dict(source)
    canonical_env["WEB_AI_ROUTE_SURFACE"] = CANONICAL_SURFACE
    result = run_preflight(env=canonical_env)
    active_paid_packages = int(result.get("active_paid_packages") or 0)
    findings.extend(
        commercial_env_file_findings(
            source,
            active_paid_packages=active_paid_packages,
            runtime_dir=BASE_DIR,
        )
    )
    findings.extend(live_sale_secret_findings(source, active_paid_packages=active_paid_packages))

    combined = list(result.get("findings") or []) + findings
    result["findings"] = combined
    result["ok"] = not combined
    result["status"] = "PASS" if not combined else "FAIL"
    result["validated_route_surface"] = actual_surface
    result["canonical_paid_preflight_surface"] = CANONICAL_SURFACE
    result["checkout_browser_binding"] = actual_surface == EXPECTED_SURFACE and not findings
    result["commercial_env_file_safe"] = not any(
        item.get("scope") == "commercial-secrets" and str(item.get("code", "")).startswith("COMMERCIAL_ENV_FILE")
        for item in combined
    )
    result["live_sale_secrets_configured"] = not any(
        item.get("scope") == "commercial-secrets" and not str(item.get("code", "")).startswith("COMMERCIAL_ENV_FILE")
        for item in combined
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run buyer-only browser-bound paid deployment preflight")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_bound_preflight()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("WebAI Bridge buyer-only browser-bound deployment preflight: " + ("PASS" if result.get("ok") else "FAIL"))
        for item in result.get("findings") or []:
            print(f"FAIL {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
        for item in result.get("warnings") or []:
            print(f"WARN {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
