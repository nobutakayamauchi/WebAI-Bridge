from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from deployment_preflight import run_preflight

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_SURFACE = "commercial_handoff:app"
CANONICAL_SURFACE = "commercial:app"


def run_handoff_preflight(*, env: dict[str, str] | None = None) -> dict:
    source = dict(os.environ if env is None else env)
    findings: list[dict] = []

    actual_surface = (source.get("WEB_AI_ROUTE_SURFACE") or "").strip()
    if actual_surface != EXPECTED_SURFACE:
        findings.append({
            "code": "HANDOFF_ROUTE_SURFACE_INVALID",
            "scope": "deployment",
            "message": f"WEB_AI_ROUTE_SURFACE must be {EXPECTED_SURFACE} for browser-handoff dogfood",
        })

    if not (BASE_DIR / "commercial_handoff.py").is_file():
        findings.append({
            "code": "HANDOFF_ENTRYPOINT_MISSING",
            "scope": "deployment",
            "message": "commercial_handoff.py is missing from the runtime directory",
        })

    canonical_env = dict(source)
    canonical_env["WEB_AI_ROUTE_SURFACE"] = CANONICAL_SURFACE
    result = run_preflight(env=canonical_env)

    if findings:
        result["findings"] = list(result.get("findings") or []) + findings
        result["ok"] = False

    result["validated_route_surface"] = actual_surface
    result["canonical_paid_preflight_surface"] = CANONICAL_SURFACE
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paid browser-handoff deployment preflight")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_handoff_preflight()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("WebAI Bridge browser-handoff deployment preflight: " + ("PASS" if result.get("ok") else "FAIL"))
        for item in result.get("findings") or []:
            print(f"FAIL {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
        for item in result.get("warnings") or []:
            print(f"WARN {item.get('code')} [{item.get('scope')}]: {item.get('message')}")
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
