from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from cost_router import BudgetLedger, PricingRegistry, cost_micros
from studio import StudioDraft, StudioValidationError, build_package, validate_package_document

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.getenv("WEB_AI_CONFIG_DIR", BASE_DIR / "apps")).resolve()
STATIC_DIR = BASE_DIR / "static"
STUDIO_DIR = BASE_DIR.parent / "creator-studio"
PACKAGE_SCHEMA_FILE = BASE_DIR.parent / "package-schema" / "package.schema.json"
PRICING_FILE = Path(os.getenv("WEB_AI_PRICING_FILE", BASE_DIR / "pricing.json"))
LEDGER_PATH = Path(os.getenv("WEB_AI_LEDGER_PATH", BASE_DIR / ".runtime" / "webai-ledger.sqlite3"))
SAFETY_KERNEL_FILE = BASE_DIR / "safety_kernel.md"
RUNNABLE_STATUSES = {"dogfood", "active"}

if not SAFETY_KERNEL_FILE.exists():
    raise RuntimeError(f"hosted safety policy is missing: {SAFETY_KERNEL_FILE}")
SAFETY_KERNEL = SAFETY_KERNEL_FILE.read_text(encoding="utf-8").strip()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    message: str = Field(min_length=1, max_length=1_000_000)
    history: list[HistoryMessage] = Field(default_factory=list)
    payer_mode: Literal["BYOK", "PLATFORM_CREDIT"] | None = None


class AppRegistry:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir.resolve()
        self.apps: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        apps: dict[str, dict] = {}
        if not self.config_dir.exists():
            self.apps = apps
            return
        instructions_root = self.config_dir.resolve()
        for path in sorted(self.config_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"package config must be a regular non-symlink file: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            schema_errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
            if schema_errors:
                raise ValueError(f"invalid package schema: {path}: {'; '.join(schema_errors)}")

            slug = data["slug"]
            if slug in apps:
                raise ValueError(f"duplicate slug: {slug}")
            instructions_file = data["instructions_file"]
            expected_instructions_file = f"apps/{slug}.instructions.md"
            if instructions_file != expected_instructions_file:
                raise ValueError(f"non-canonical instructions_file for {slug}: {instructions_file}")
            # `instructions_file` is the portable logical package path. At runtime,
            # WEB_AI_CONFIG_DIR is the deployed `apps` authority root, so the file
            # must resolve from that root rather than from a hard-coded repository path.
            instruction_path = (instructions_root / f"{slug}.instructions.md").resolve()
            if instruction_path.parent != instructions_root:
                raise ValueError(f"instructions path escapes configured app directory: {slug}")
            if instruction_path.is_symlink() or not instruction_path.exists() or not instruction_path.is_file():
                raise ValueError(f"instructions file not found as regular non-symlink file: {instruction_path}")

            billing = data["billing"]
            allowed_payers = billing["allowed_payer_modes"]
            default_payer = billing["default_payer_mode"]
            if not allowed_payers or default_payer not in allowed_payers:
                raise ValueError(f"invalid billing payer policy: {slug}")
            routing = data["routing"]
            default_model = routing["default_model"]
            allowed_models = routing["allowed_models"]
            if not default_model or default_model not in allowed_models:
                raise ValueError(f"invalid routing policy: {slug}")
            data["_instructions"] = instruction_path.read_text(encoding="utf-8")
            apps[slug] = data
        self.apps = apps

    def get(self, slug: str) -> dict:
        app_config = self.apps.get(slug)
        if not app_config:
            raise KeyError(slug)
        return app_config


registry = AppRegistry(CONFIG_DIR)
pricing = PricingRegistry(PRICING_FILE)
ledger = BudgetLedger(LEDGER_PATH)
app = FastAPI(title="WebAI Bridge", version="0.2.0-dogfood")
_request_times: dict[str, deque[float]] = defaultdict(deque)


def enforce_rate_limit(request: Request) -> None:
    limit = int(os.getenv("WEB_AI_REQUESTS_PER_MINUTE", "20"))
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    q = _request_times[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    q.append(now)


def studio_enabled() -> bool:
    return os.getenv("WEB_AI_STUDIO_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def diagnostics_enabled() -> bool:
    return os.getenv("WEB_AI_DIAGNOSTICS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def require_studio_enabled() -> None:
    if not studio_enabled():
        raise HTTPException(status_code=404, detail="Creator Studio is disabled")


def public_config(app_config: dict) -> dict:
    billing = app_config["billing"]
    return {
        "slug": app_config["slug"],
        "display_name": app_config.get("display_name", app_config["slug"]),
        "description": app_config.get("description", ""),
        "status": app_config.get("status", "unknown"),
        "welcome": app_config.get("ui", {}).get("welcome", "Ask me anything."),
        "allowed_payer_modes": billing["allowed_payer_modes"],
        "default_payer_mode": billing["default_payer_mode"],
        "byok_transport": billing.get("byok_transport", "NOT_APPLICABLE"),
        "access": app_config.get("access", {}),
        "delivery": app_config.get("delivery", {}),
        "safety": app_config.get("safety", {}),
        "readiness": app_config.get("readiness", {}),
    }


def resolve_payer_mode(payload: ChatRequest, app_config: dict) -> str:
    billing = app_config["billing"]
    payer_mode = payload.payer_mode or billing["default_payer_mode"]
    if payer_mode not in billing["allowed_payer_modes"]:
        raise HTTPException(status_code=403, detail="Payer mode is not allowed")
    return payer_mode


def resolve_model(app_config: dict) -> str:
    routing = app_config["routing"]
    model = routing["default_model"]
    if model not in routing["allowed_models"]:
        raise HTTPException(status_code=503, detail="Model routing policy is invalid")
    return model


def ensure_hosted_runnable(app_config: dict) -> None:
    status = app_config.get("status")
    if status not in RUNNABLE_STATUSES:
        raise HTTPException(status_code=409, detail="AI Package is not activated for runtime use")
    delivery = app_config.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise HTTPException(status_code=503, detail="Portable runtime execution is not implemented")
    access = app_config.get("access") or {}
    if access.get("mode") != "FREE" and access.get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise HTTPException(status_code=503, detail="Paid hosted entitlement enforcement is not implemented")


def token_upper_bound(text: str) -> int:
    return len(text.encode("utf-8")) + 8


def request_input_token_upper_bound(payload: ChatRequest, instructions: str, knowledge_reserve_tokens: int) -> int:
    total = token_upper_bound(instructions) + token_upper_bound(payload.message)
    for item in payload.history:
        total += token_upper_bound(item.content) + 8
    return total + max(0, knowledge_reserve_tokens)


def extract_usage(response) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None, None
    return input_tokens, output_tokens


def build_hosted_instructions(app_config: dict) -> str:
    creator = app_config["_instructions"].strip()
    return f"{SAFETY_KERNEL}\n\n--- Creator Instructions ---\n{creator}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app_count": len(registry.apps), "pricing_version": pricing.version}


@app.get("/runtime")
def runtime_identity() -> dict:
    if not diagnostics_enabled():
        raise HTTPException(status_code=404, detail="Runtime diagnostics are disabled")
    return {
        "service_unit": os.getenv("WEB_AI_SERVICE_UNIT", "UNSET"),
        "working_directory": os.getenv("WEB_AI_WORKING_DIRECTORY", str(BASE_DIR)),
        "entrypoint": "app:app",
        "route_surface": os.getenv("WEB_AI_ROUTE_SURFACE", "UNSET"),
        "deployed_revision": os.getenv("DEPLOYED_REVISION", "UNSET"),
        "pricing_version": pricing.version,
        "ledger_path": str(LEDGER_PATH),
    }


@app.get("/studio")
def creator_studio_page():
    require_studio_enabled()
    page = STUDIO_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=503, detail="Creator Studio UI is missing")
    return FileResponse(page)


@app.get("/api/studio/options")
def creator_studio_options() -> dict:
    require_studio_enabled()
    return {
        "models": list(pricing.models.keys()),
        "pricing_version": pricing.version,
        "payer_modes": ["BYOK", "PLATFORM_CREDIT"],
        "access_modes": ["FREE", "ALLOWANCE_THEN_PAID", "PAID", "BUY_ONCE", "SUBSCRIPTION", "PER_USE"],
        "delivery_modes": ["HOSTED_ONLY", "PORTABLE_LICENSE", "HOSTED_AND_PORTABLE"],
        "commercial_enforcement": "NOT_IMPLEMENTED",
        "portable_runtime": "NOT_IMPLEMENTED",
        "persistence": "NONE",
    }


@app.post("/api/studio/validate")
def creator_studio_validate(payload: StudioDraft, request: Request) -> dict:
    require_studio_enabled()
    enforce_rate_limit(request)
    try:
        return build_package(payload, schema_path=PACKAGE_SCHEMA_FILE, available_models=set(pricing.models.keys()))
    except StudioValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors, "warnings": exc.warnings}) from None


@app.get("/apps/{slug}/public-config")
def get_public_config(slug: str) -> dict:
    try:
        app_config = registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_hosted_runnable(app_config)
    return public_config(app_config)


@app.get("/a/{slug}")
def app_page(slug: str):
    try:
        app_config = registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_hosted_runnable(app_config)
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request, byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key")) -> dict:
    enforce_rate_limit(request)
    try:
        app_config = registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    ensure_hosted_runnable(app_config)

    usage_policy = app_config.get("usage", {})
    max_input_chars = int(usage_policy.get("max_input_chars", 12000))
    max_history_messages = int(usage_policy.get("max_history_messages", 12))
    max_history_chars = int(usage_policy.get("max_history_chars", max_input_chars * max_history_messages))
    max_output_tokens = int(usage_policy.get("max_output_tokens", 2048))
    if len(payload.message) > max_input_chars:
        raise HTTPException(status_code=413, detail="Message too large")
    if len(payload.history) > max_history_messages:
        raise HTTPException(status_code=413, detail="Conversation history too large")
    if sum(len(item.content) for item in payload.history) > max_history_chars:
        raise HTTPException(status_code=413, detail="Conversation history content too large")

    payer_mode = resolve_payer_mode(payload, app_config)
    model = resolve_model(app_config)
    try:
        price = pricing.get(model)
    except KeyError:
        raise HTTPException(status_code=503, detail="Model price is not configured") from None

    knowledge = app_config.get("knowledge", {})
    knowledge_enabled = bool(knowledge.get("enabled"))
    knowledge_reserve_tokens = int(knowledge.get("reserve_tokens", 0) or 0)
    tool_reserve_micros = int(knowledge.get("platform_tool_reserve_usd_micros", 0) or 0)
    if payer_mode == "PLATFORM_CREDIT" and knowledge_enabled and tool_reserve_micros <= 0:
        raise HTTPException(status_code=503, detail="Knowledge cost policy is not configured")

    input_messages = [m.model_dump() for m in payload.history]
    input_messages.append({"role": "user", "content": payload.message})
    kwargs: dict = {
        "model": model,
        "instructions": build_hosted_instructions(app_config),
        "input": input_messages,
        "max_output_tokens": max_output_tokens,
        "store": False,
    }
    if knowledge_enabled:
        vector_env = knowledge.get("vector_store_env")
        vector_store_id = os.getenv(vector_env or "") if vector_env else None
        if not vector_store_id:
            raise HTTPException(status_code=503, detail="Knowledge store is not configured")
        kwargs["tools"] = [{"type": "file_search", "vector_store_ids": [vector_store_id]}]

    reserved_micros = 0
    budget_id: str | None = None
    if payer_mode == "BYOK":
        api_key = (byok_api_key or "").strip()
        if not api_key:
            raise HTTPException(status_code=402, detail="BYOK API key is required")
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="Platform AI service is not configured")
        platform_policy = app_config["billing"].get("platform_credit") or {}
        if not platform_policy.get("enabled"):
            raise HTTPException(status_code=403, detail="Platform credit is disabled")
        budget_env = platform_policy.get("budget_id_env")
        budget_id = os.getenv(budget_env or "") if budget_env else None
        if not budget_id:
            raise HTTPException(status_code=503, detail="Platform budget is not configured")
        hard_limit_micros = int(platform_policy.get("hard_limit_usd_micros", 0))
        if hard_limit_micros <= 0:
            raise HTTPException(status_code=503, detail="Platform budget limit is invalid")
        input_upper = request_input_token_upper_bound(payload, build_hosted_instructions(app_config), knowledge_reserve_tokens)
        reserved_micros = cost_micros(input_tokens=input_upper, output_tokens=max_output_tokens, price=price) + tool_reserve_micros
        if not ledger.reserve(budget_id, hard_limit_micros, reserved_micros):
            raise HTTPException(status_code=402, detail="Platform credit exhausted")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    try:
        response = client.responses.create(**kwargs)
    except Exception as exc:
        if payer_mode == "PLATFORM_CREDIT" and budget_id:
            ledger.release_failed(
                budget_id=budget_id, reserved_micros=reserved_micros, package_id=app_config["slug"],
                provider="openai", model=model, pricing_version=pricing.version, result="PROVIDER_ERROR"
            )
        else:
            ledger.record_byok(
                package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version,
                input_tokens=None, output_tokens=None, actual_cost_micros=None, result="PROVIDER_ERROR"
            )
        raise HTTPException(status_code=502, detail="Upstream AI request failed") from exc

    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        if payer_mode == "PLATFORM_CREDIT" and budget_id:
            ledger.release_failed(
                budget_id=budget_id, reserved_micros=reserved_micros, package_id=app_config["slug"],
                provider="openai", model=model, pricing_version=pricing.version, result="NO_TEXT"
            )
        else:
            ledger.record_byok(
                package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version,
                input_tokens=None, output_tokens=None, actual_cost_micros=None, result="NO_TEXT"
            )
        raise HTTPException(status_code=502, detail="AI returned no text")

    input_tokens, output_tokens = extract_usage(response)
    actual_cost = None
    if input_tokens is not None and output_tokens is not None:
        actual_cost = cost_micros(input_tokens=input_tokens, output_tokens=output_tokens, price=price)
        if knowledge_enabled:
            actual_cost += tool_reserve_micros

    if payer_mode == "PLATFORM_CREDIT" and budget_id:
        charged = actual_cost if actual_cost is not None else reserved_micros
        result = "SUCCESS" if actual_cost is not None else "SUCCESS_COST_UNOBSERVED"
        if actual_cost is not None and actual_cost > reserved_micros:
            result = "SUCCESS_RESERVATION_OVERRUN"
        ledger.settle_platform(
            budget_id=budget_id, reserved_micros=reserved_micros, charged_micros=charged,
            package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version,
            input_tokens=input_tokens, output_tokens=output_tokens, actual_cost_micros=actual_cost,
            result=result,
        )
    else:
        ledger.record_byok(
            package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version,
            input_tokens=input_tokens, output_tokens=output_tokens, actual_cost_micros=actual_cost,
            result="SUCCESS" if actual_cost is not None else "SUCCESS_COST_UNOBSERVED"
        )

    return {"text": text, "model": model, "payer_mode": payer_mode}
