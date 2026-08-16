from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from cost_router import PricingRegistry
from studio import validate_package_document

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent
PACKAGE_SCHEMA_FILE = REPO_DIR / "package-schema" / "package.schema.json"
PRICING_FILE = BASE_DIR / "pricing.json"
SENSITIVE_PACKAGE_KEYS = {
    "api_key",
    "provider_api_key",
    "password",
    "passphrase",
    "buyer_passphrase",
    "seller_password",
    "signing_key",
    "seller_signing_key",
    "secret",
    "client_secret",
    "access_token",
    "bearer_token",
    "credential",
    "credential_value",
}
REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _secret_key_paths(value, prefix="") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in SENSITIVE_PACKAGE_KEYS and child not in {None, "", False, 0}:
                found.append(path)
            found.extend(_secret_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_key_paths(child, f"{prefix}[{index}]"))
    return found


def _finding(findings: list[dict], code: str, message: str, *, scope: str = "deployment") -> None:
    findings.append({"code": code, "scope": scope, "message": message})


def _check_storage_path(
    findings: list[dict],
    *,
    env: Mapping[str, str],
    env_name: str,
    runtime_dir: Path,
) -> Path | None:
    raw = (env.get(env_name) or "").strip()
    if not raw:
        _finding(findings, f"{env_name}_MISSING", f"{env_name} must be explicitly configured")
        return None
    path = Path(raw)
    if not path.is_absolute():
        _finding(findings, f"{env_name}_NOT_ABSOLUTE", f"{env_name} must use an absolute path")
        return path
    if _inside(path, runtime_dir):
        _finding(findings, f"{env_name}_INSIDE_RUNTIME", f"{env_name} must live outside the application/runtime tree")
    parent = path.parent
    if not parent.exists():
        _finding(findings, f"{env_name}_PARENT_MISSING", f"Parent directory for {env_name} does not exist: {parent}")
    elif not os.access(parent, os.W_OK):
        _finding(findings, f"{env_name}_PARENT_NOT_WRITABLE", f"Parent directory for {env_name} is not writable by the current service user")
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            _finding(findings, f"{env_name}_PERMISSIONS_TOO_OPEN", f"Existing {env_name} file must not grant group/world permissions")
    return path


def _check_package(
    findings: list[dict],
    warnings: list[dict],
    *,
    path: Path,
    runtime_dir: Path,
    schema_path: Path,
    pricing: PricingRegistry,
    env: Mapping[str, str],
) -> tuple[bool, bool]:
    scope = f"package:{path.name}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _finding(findings, "PACKAGE_JSON_INVALID", f"Cannot parse package JSON: {exc}", scope=scope)
        return False, False

    schema_errors = validate_package_document(data, schema_path=schema_path)
    for error in schema_errors:
        _finding(findings, "PACKAGE_SCHEMA_INVALID", error, scope=scope)

    slug = str(data.get("slug") or "")
    instructions_file = str(data.get("instructions_file") or "")
    if slug and instructions_file:
        expected = f"apps/{slug}.instructions.md"
        if instructions_file != expected:
            _finding(findings, "INSTRUCTIONS_PATH_NONCANONICAL", f"Expected {expected}, got {instructions_file}", scope=scope)
        instruction_path = runtime_dir / instructions_file
        if not instruction_path.exists():
            _finding(findings, "INSTRUCTIONS_FILE_MISSING", f"Instructions file does not exist: {instruction_path}", scope=scope)

    for secret_path in _secret_key_paths(data):
        _finding(findings, "SECRET_MATERIAL_IN_PACKAGE", f"Secret-like value must not be embedded in Package JSON: {secret_path}", scope=scope)

    routing = data.get("routing") or {}
    for model in routing.get("allowed_models") or []:
        try:
            pricing.get(model)
        except KeyError:
            _finding(findings, "MODEL_PRICE_MISSING", f"Allowed model has no current pricing evidence: {model}", scope=scope)

    knowledge = data.get("knowledge") or {}
    if data.get("status") == "active" and knowledge.get("enabled"):
        vector_env = str(knowledge.get("vector_store_env") or "")
        if not vector_env or not (env.get(vector_env) or "").strip():
            _finding(findings, "ACTIVE_KNOWLEDGE_BINDING_MISSING", f"Active Knowledge package requires configured env: {vector_env or '<missing>'}", scope=scope)

    status = data.get("status")
    access = data.get("access") or {}
    paid = access.get("mode") != "FREE"
    active_paid = status == "active" and paid

    if status == "draft":
        warnings.append({"code": "DRAFT_PACKAGE_PRESENT", "scope": scope, "message": "Draft package is present but must remain non-runnable"})

    if active_paid:
        if access.get("mode") not in {"BUY_ONCE", "SUBSCRIPTION"}:
            _finding(findings, "ACTIVE_PAID_MODE_UNSUPPORTED", "First commercial gateway supports active BUY_ONCE or SUBSCRIPTION only", scope=scope)
        if access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
            _finding(findings, "ACTIVE_PAID_ENTITLEMENT_NOT_ENFORCED", "Active paid package must use ENTITLEMENT_ENFORCED", scope=scope)

        checkout = access.get("checkout") or {}
        if checkout.get("provider") != "STRIPE_PAYMENT_LINK":
            _finding(findings, "ACTIVE_PAID_CHECKOUT_PROVIDER_INVALID", "Active paid package must use Stripe Payment Link metadata", scope=scope)
        if not _https_url(str(checkout.get("payment_link_url") or "")):
            _finding(findings, "ACTIVE_PAID_CHECKOUT_URL_INVALID", "Active paid package must have an HTTPS checkout URL", scope=scope)
        if checkout.get("binding_verification") not in {"CREATOR_ATTESTED", "OPERATOR_REVIEWED", "STRIPE_VERIFIED"}:
            _finding(findings, "ACTIVE_PAID_CHECKOUT_UNVERIFIED", "Checkout product/price/currency/charge basis binding is not verified", scope=scope)

        delivery = data.get("delivery") or {}
        if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
            _finding(findings, "ACTIVE_PAID_DELIVERY_UNSUPPORTED", "First commercial gateway requires active Hosted-only runtime", scope=scope)

        billing = data.get("billing") or {}
        if billing.get("allowed_payer_modes") != ["BYOK"] or billing.get("default_payer_mode") != "BYOK":
            _finding(findings, "ACTIVE_PAID_PAYER_NOT_BYOK_ONLY", "First commercial gateway requires BYOK-only inference", scope=scope)
        if billing.get("platform_credit"):
            _finding(findings, "ACTIVE_PAID_PLATFORM_SUBSIDY_PRESENT", "Active paid v0 must not carry PLATFORM_CREDIT subsidy config", scope=scope)

    return status == "active", active_paid


def run_preflight(
    *,
    env: Mapping[str, str] | None = None,
    runtime_dir: Path = BASE_DIR,
    config_dir: Path | None = None,
    schema_path: Path = PACKAGE_SCHEMA_FILE,
    pricing_file: Path = PRICING_FILE,
) -> dict:
    env = os.environ if env is None else env
    runtime_dir = runtime_dir.resolve()
    config_dir = Path(env.get("WEB_AI_CONFIG_DIR") or config_dir or (runtime_dir / "apps")).resolve()
    findings: list[dict] = []
    warnings: list[dict] = []

    service_unit = (env.get("WEB_AI_SERVICE_UNIT") or "").strip()
    if not service_unit or service_unit == "UNSET":
        _finding(findings, "DEPLOYMENT_SERVICE_UNIT_UNSET", "WEB_AI_SERVICE_UNIT must identify the real deployed service")

    working_raw = (env.get("WEB_AI_WORKING_DIRECTORY") or "").strip()
    if not working_raw:
        _finding(findings, "DEPLOYMENT_WORKING_DIRECTORY_UNSET", "WEB_AI_WORKING_DIRECTORY must be explicit")
    else:
        working = Path(working_raw)
        if not working.is_absolute() or working.resolve() != runtime_dir:
            _finding(findings, "DEPLOYMENT_WORKING_DIRECTORY_MISMATCH", f"Configured working directory must equal actual runtime directory: {runtime_dir}")

    if (env.get("WEB_AI_ROUTE_SURFACE") or "").strip() != "commercial:app":
        _finding(findings, "DEPLOYMENT_ROUTE_SURFACE_INVALID", "WEB_AI_ROUTE_SURFACE must be commercial:app for the paid gateway")

    revision = (env.get("DEPLOYED_REVISION") or "").strip()
    if not REVISION_RE.fullmatch(revision):
        _finding(findings, "DEPLOYED_REVISION_UNESTABLISHED", "DEPLOYED_REVISION must be an explicit Git commit SHA")

    if _truthy(env.get("WEB_AI_DIAGNOSTICS_ENABLED")):
        _finding(findings, "PUBLIC_DIAGNOSTICS_ENABLED", "WEB_AI_DIAGNOSTICS_ENABLED must be off for public deployment")
    if _truthy(env.get("WEB_AI_STUDIO_ENABLED")):
        _finding(findings, "PUBLIC_STUDIO_ENABLED", "Creator Studio must remain off on the public commercial runtime")
    if _truthy(env.get("WEB_AI_ALLOW_INSECURE_HTTP")):
        _finding(findings, "INSECURE_HTTP_OVERRIDE_ENABLED", "WEB_AI_ALLOW_INSECURE_HTTP must be off outside explicit local development")

    entitlement_path = _check_storage_path(
        findings, env=env, env_name="WEB_AI_ENTITLEMENT_DB", runtime_dir=runtime_dir
    )
    ledger_path = _check_storage_path(
        findings, env=env, env_name="WEB_AI_LEDGER_PATH", runtime_dir=runtime_dir
    )
    if entitlement_path is not None and ledger_path is not None and entitlement_path.resolve() == ledger_path.resolve():
        _finding(findings, "STATE_DATABASE_PATH_COLLISION", "Entitlement DB and ledger DB must use different files")

    if not (runtime_dir / "commercial.py").exists():
        _finding(findings, "COMMERCIAL_ENTRYPOINT_MISSING", "commercial.py is missing from the runtime directory")
    if not (runtime_dir / "safety_kernel.md").exists():
        _finding(findings, "SAFETY_KERNEL_MISSING", "Hosted Safety policy file is missing")

    try:
        pricing = PricingRegistry(pricing_file)
    except Exception as exc:
        _finding(findings, "PRICING_REGISTRY_INVALID", f"Pricing registry could not be loaded: {exc}")
        pricing = PricingRegistry(Path("/__webai_missing_pricing__"))
    if not pricing.models:
        _finding(findings, "PRICING_REGISTRY_EMPTY", "Pricing registry has no usable model entries")

    active_packages = 0
    active_paid_packages = 0
    if not config_dir.exists():
        _finding(findings, "CONFIG_DIR_MISSING", f"Package config directory does not exist: {config_dir}")
    else:
        package_files = sorted(config_dir.glob("*.json"))
        if not package_files:
            _finding(findings, "NO_PACKAGE_CONFIGS", f"No package JSON files found in {config_dir}")
        for path in package_files:
            active, active_paid = _check_package(
                findings,
                warnings,
                path=path,
                runtime_dir=runtime_dir,
                schema_path=schema_path,
                pricing=pricing,
                env=env,
            )
            active_packages += int(active)
            active_paid_packages += int(active_paid)

    if active_packages == 0:
        warnings.append({"code": "NO_ACTIVE_PACKAGES", "scope": "deployment", "message": "No active package is currently configured"})
    if active_paid_packages == 0:
        warnings.append({"code": "NO_ACTIVE_PAID_PACKAGES", "scope": "deployment", "message": "No active paid package is currently configured"})

    return {
        "ok": not findings,
        "status": "PASS" if not findings else "FAIL",
        "runtime_dir": str(runtime_dir),
        "config_dir": str(config_dir),
        "active_packages": active_packages,
        "active_paid_packages": active_paid_packages,
        "findings": findings,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed WebAI Bridge deployment preflight")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    args = parser.parse_args()

    result = run_preflight()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"WebAI Bridge deployment preflight: {result['status']}")
        for item in result["findings"]:
            print(f"FAIL {item['code']} [{item['scope']}]: {item['message']}")
        for item in result["warnings"]:
            print(f"WARN {item['code']} [{item['scope']}]: {item['message']}")
        print(f"active_packages={result['active_packages']} active_paid_packages={result['active_paid_packages']}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
