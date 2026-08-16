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

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.getenv("WEB_AI_CONFIG_DIR", BASE_DIR / "apps"))
STATIC_DIR = BASE_DIR / "static"
PRICING_FILE = Path(os.getenv("WEB_AI_PRICING_FILE", BASE_DIR / "pricing.json"))
LEDGER_PATH = Path(os.getenv("WEB_AI_LEDGER_PATH", BASE_DIR / ".runtime" / "webai-ledger.sqlite3"))


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    message: str = Field(min_length=1)
    history: list[HistoryMessage] = Field(default_factory=list)
    payer_mode: Literal["BYOK", "PLATFORM_CREDIT"] | None = None


class AppRegistry:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.apps: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        apps: dict[str, dict] = {}
        if not self.config_dir.exists():
            self.apps = apps
            return
        for path in sorted(self.config_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            slug = data.get("slug")
            if not isinstance(slug, str) or not slug:
                raise ValueError(f"missing slug: {path}")
            if slug in apps:
                raise ValueError(f"duplicate slug: {slug}")
            instructions_file = data.get("instructions_file")
            if not instructions_file:
                raise ValueError(f"missing instructions_file: {slug}")
            instruction_path = BASE_DIR / instructions_file
            if not instruction_path.exists():
                raise ValueError(f"instructions file not found: {instruction_path}")
            billing = data.get("billing") or {}
            allowed_payers = billing.get("allowed_payer_modes") or []
            default_payer = billing.get("default_payer_mode")
            if not allowed_payers or default_payer not in allowed_payers:
                raise ValueError(f"invalid billing payer policy: {slug}")
            routing = data.get("routing") or {}
            default_model = routing.get("default_model")
            allowed_models = routing.get("allowed_models") or []
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
app = FastAPI(title="WebAI Bridge", version="0.1.0-dogfood")
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


def public_config(app_config: dict) -> dict:
    billing = app_config["billing"]
    return {"slug": app_config["slug"], "display_name": app_config.get("display_name", app_config["slug"]), "description": app_config.get("description", ""), "status": app_config.get("status", "unknown"), "welcome": app_config.get("ui", {}).get("welcome", "Ask me anything."), "allowed_payer_modes": billing["allowed_payer_modes"], "default_payer_mode": billing["default_payer_mode"], "access": app_config.get("access", {}), "delivery": app_config.get("delivery", {})}


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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app_count": len(registry.apps), "pricing_version": pricing.version}


@app.get("/runtime")
def runtime_identity() -> dict:
    return {"service_unit": os.getenv("WEB_AI_SERVICE_UNIT", "UNSET"), "working_directory": os.getenv("WEB_AI_WORKING_DIRECTORY", str(BASE_DIR)), "entrypoint": "app:app", "route_surface": os.getenv("WEB_AI_ROUTE_SURFACE", "UNSET"), "deployed_revision": os.getenv("DEPLOYED_REVISION", "UNSET"), "pricing_version": pricing.version, "ledger_path": str(LEDGER_PATH)}


@app.get("/apps/{slug}/public-config")
def get_public_config(slug: str) -> dict:
    try:
        return public_config(registry.get(slug))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None


@app.get("/a/{slug}")
def app_page(slug: str):
    try:
        registry.get(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(payload: ChatRequest, request: Request, byok_api_key: str | None = Header(default=None, alias="X-Provider-API-Key")) -> dict:
    enforce_rate_limit(request)
    try:
        app_config = registry.get(payload.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown app") from None
    usage_policy = app_config.get("usage", {})
    max_input_chars = int(usage_policy.get("max_input_chars", 12000))
    max_history_messages = int(usage_policy.get("max_history_messages", 12))
    max_output_tokens = int(usage_policy.get("max_output_tokens", 2048))
    if len(payload.message) > max_input_chars:
        raise HTTPException(status_code=413, detail="Message too large")
    if len(payload.history) > max_history_messages:
        raise HTTPException(status_code=413, detail="Conversation history too large")

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
    kwargs: dict = {"model": model, "instructions": app_config["_instructions"], "input": input_messages, "max_output_tokens": max_output_tokens, "store": False}
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
        input_upper = request_input_token_upper_bound(payload, app_config["_instructions"], knowledge_reserve_tokens)
        reserved_micros = cost_micros(input_tokens=input_upper, output_tokens=max_output_tokens, price=price) + tool_reserve_micros
        if not ledger.reserve(budget_id, hard_limit_micros, reserved_micros):
            raise HTTPException(status_code=402, detail="Platform credit exhausted")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    try:
        response = client.responses.create(**kwargs)
    except Exception as exc:
        if payer_mode == "PLATFORM_CREDIT" and budget_id:
            ledger.release_failed(budget_id=budget_id, reserved_micros=reserved_micros, package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version, result="PROVIDER_ERROR")
        else:
            ledger.record_byok(package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version, input_tokens=None, output_tokens=None, actual_cost_micros=None, result="PROVIDER_ERROR")
        raise HTTPException(status_code=502, detail="Upstream AI request failed") from exc

    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        if payer_mode == "PLATFORM_CREDIT" and budget_id:
            ledger.release_failed(budget_id=budget_id, reserved_micros=reserved_micros, package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version, result="NO_TEXT")
        raise HTTPException(status_code=502, detail="AI returned no text")

    input_tokens, output_tokens = extract_usage(response)
    actual_cost = None
    if input_tokens is not None and output_tokens is not None:
        actual_cost = cost_micros(input_tokens=input_tokens, output_tokens=output_tokens, price=price)
        if knowledge_enabled:
            actual_cost += tool_reserve_micros

    if payer_mode == "PLATFORM_CREDIT" and budget_id:
        charged = min(actual_cost, reserved_micros) if actual_cost is not None else reserved_micros
        ledger.settle_platform(budget_id=budget_id, reserved_micros=reserved_micros, charged_micros=charged, package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version, input_tokens=input_tokens, output_tokens=output_tokens, actual_cost_micros=actual_cost, result="SUCCESS" if actual_cost is not None else "SUCCESS_COST_UNOBSERVED")
    else:
        ledger.record_byok(package_id=app_config["slug"], provider="openai", model=model, pricing_version=pricing.version, input_tokens=input_tokens, output_tokens=output_tokens, actual_cost_micros=actual_cost, result="SUCCESS" if actual_cost is not None else "SUCCESS_COST_UNOBSERVED")

    return {"text": text, "model": model, "payer_mode": payer_mode}
