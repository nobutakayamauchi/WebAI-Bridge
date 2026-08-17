from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from deployment_preflight import run_preflight
from package_knowledge import PACKAGE_TEXT_BACKEND, validate_package_text_binding

BASE_DIR = Path(__file__).resolve().parent
EXPECTED_SURFACE = "commercial_handoff:app"
CANONICAL_SURFACE = "commercial:app"


def _package_text_findings(source: dict[str, str]) -> tuple[set[str], list[dict]]:
    config_dir = Path(source.get("WEB_AI_CONFIG_DIR") or (BASE_DIR / "apps")).resolve()
    local_scopes: set[str] = set()
    findings: list[dict] = []
    if not config_dir.exists() or not config_dir.is_dir():
        return local_scopes, findings
    for path in sorted(config_dir.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        knowledge = data.get("knowledge") or {}
        if data.get("status") != "active" or not knowledge.get("enabled"):
            continue
        if knowledge.get("backend") != PACKAGE_TEXT_BACKEND:
            continue
        scope = f"package:{path.name}"
        local_scopes.add(scope)
        for error in validate_package_text_binding(config_dir=config_dir, app_config=data):
            findings.append({
                "code": "ACTIVE_PACKAGE_TEXT_KNOWLEDGE_INVALID",
                "scope": scope,
                "message": error,
            })
    return local_scopes, findings


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

    local_scopes, knowledge_findings = _package_text_findings(source)
    base_findings = []
    for item in result.get("findings") or []:
        if (
            item.get("code") == "ACTIVE_KNOWLEDGE_BINDING_MISSING"
            and item.get("scope") in local_scopes
        ):
            continue
        base_findings.append(item)

    combined = base_findings + findings + knowledge_findings
    result["findings"] = combined
    result["ok"] = not combined
    result["validated_route_surface"] = actual_surface
    result["canonical_paid_preflight_surface"] = CANONICAL_SURFACE
    result["package_text_knowledge_packages"] = len(local_scopes)
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
