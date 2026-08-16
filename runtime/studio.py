from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_CEILING
from functools import lru_cache
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, field_validator

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

AccessMode = Literal["FREE", "ALLOWANCE_THEN_PAID", "PAID", "BUY_ONCE", "SUBSCRIPTION", "PER_USE"]
PayerMode = Literal["BYOK", "PLATFORM_CREDIT"]
DeliveryMode = Literal["HOSTED_ONLY", "PORTABLE_LICENSE", "HOSTED_AND_PORTABLE"]


class StudioValidationError(ValueError):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


class StudioDraft(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=100_000)

    knowledge_enabled: bool = False
    knowledge_vector_store_env: str = Field(default="", max_length=120)
    knowledge_reserve_tokens: int = Field(default=0, ge=0, le=1_000_000)
    knowledge_platform_tool_reserve_usd: Decimal = Field(default=Decimal("0"), ge=0, le=1000)

    access_mode: AccessMode = "FREE"
    included_runs: int = Field(default=0, ge=0, le=1_000_000)

    allowed_payer_modes: list[PayerMode] = Field(default_factory=lambda: ["BYOK"])
    default_payer_mode: PayerMode = "BYOK"
    platform_budget_id_env: str = Field(default="", max_length=120)
    platform_hard_limit_usd: Decimal = Field(default=Decimal("0"), ge=0, le=1_000_000)

    default_model: str = Field(min_length=1, max_length=200)
    allowed_models: list[str] = Field(min_length=1, max_length=32)
    delivery_mode: DeliveryMode = "HOSTED_ONLY"
    welcome: str = Field(default="", max_length=500)

    max_input_chars: int = Field(default=12_000, ge=1, le=1_000_000)
    max_history_messages: int = Field(default=12, ge=0, le=1000)
    max_output_tokens: int = Field(default=2048, ge=1, le=1_000_000)

    @field_validator("allowed_payer_modes", "allowed_models")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate values are not allowed")
        return value


def usd_to_micros(value: Decimal) -> int:
    return int((value * Decimal(1_000_000)).to_integral_value(rounding=ROUND_CEILING))


@lru_cache(maxsize=8)
def _schema_validator(schema_path: str) -> Draft202012Validator:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def build_package(
    draft: StudioDraft,
    *,
    schema_path: Path,
    available_models: set[str],
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not draft.allowed_payer_modes:
        errors.append("At least one inference payer mode is required.")
    if draft.default_payer_mode not in draft.allowed_payer_modes:
        errors.append("Default payer mode must be included in allowed payer modes.")

    platform_enabled = "PLATFORM_CREDIT" in draft.allowed_payer_modes
    if platform_enabled:
        if not ENV_NAME_RE.fullmatch(draft.platform_budget_id_env):
            errors.append("Platform credit requires a valid budget environment variable name.")
        if draft.platform_hard_limit_usd <= 0:
            errors.append("Platform credit requires a positive hard limit.")

    if draft.knowledge_enabled:
        if not ENV_NAME_RE.fullmatch(draft.knowledge_vector_store_env):
            errors.append("Knowledge requires a valid vector-store environment variable name.")
        if platform_enabled and draft.knowledge_platform_tool_reserve_usd <= 0:
            errors.append("Platform-funded Knowledge requires an explicit positive tool-cost reserve.")
        warnings.append("Knowledge is a server binding in thin v0; file upload/indexing remains operator-assisted.")

    if draft.access_mode == "ALLOWANCE_THEN_PAID" and draft.included_runs <= 0:
        errors.append("ALLOWANCE_THEN_PAID requires included_runs > 0.")
    if draft.access_mode != "ALLOWANCE_THEN_PAID" and draft.included_runs > 0:
        warnings.append("included_runs is only descriptive outside ALLOWANCE_THEN_PAID in thin v0.")
    if draft.access_mode != "FREE":
        warnings.append("Commercial access enforcement is not implemented in thin v0; this is pricing intent only.")

    if draft.default_model not in draft.allowed_models:
        errors.append("Default model must be included in allowed models.")
    unknown_models = [model for model in draft.allowed_models if model not in available_models]
    if unknown_models:
        errors.append(f"Models missing from the current pricing registry: {', '.join(unknown_models)}")

    if draft.delivery_mode != "HOSTED_ONLY":
        warnings.append("Portable delivery exposes the exported Instructions and any bundled Knowledge to the recipient.")

    if errors:
        raise StudioValidationError(errors, warnings)

    package = {
        "id": draft.slug,
        "slug": draft.slug,
        "display_name": draft.display_name,
        "description": draft.description,
        "status": "draft",
        "instructions_file": f"apps/{draft.slug}.instructions.md",
        "knowledge": {
            "enabled": draft.knowledge_enabled,
            "vector_store_env": draft.knowledge_vector_store_env if draft.knowledge_enabled else "",
            "reserve_tokens": draft.knowledge_reserve_tokens if draft.knowledge_enabled else 0,
            "platform_tool_reserve_usd_micros": usd_to_micros(draft.knowledge_platform_tool_reserve_usd) if draft.knowledge_enabled else 0,
        },
        "access": {
            "mode": draft.access_mode,
            "included_runs": draft.included_runs,
            "commercial_enforcement": "NOT_IMPLEMENTED",
        },
        "billing": {
            "allowed_payer_modes": draft.allowed_payer_modes,
            "default_payer_mode": draft.default_payer_mode,
        },
        "routing": {
            "policy": "cost_aware_v0",
            "default_model": draft.default_model,
            "allowed_models": draft.allowed_models,
        },
        "delivery": {"mode": draft.delivery_mode},
        "ui": {"welcome": draft.welcome or f"{draft.display_name}に質問してください。"},
        "usage": {
            "max_input_chars": draft.max_input_chars,
            "max_history_messages": draft.max_history_messages,
            "max_output_tokens": draft.max_output_tokens,
        },
    }

    if platform_enabled:
        package["billing"]["platform_credit"] = {
            "enabled": True,
            "budget_id_env": draft.platform_budget_id_env,
            "hard_limit_usd_micros": usd_to_micros(draft.platform_hard_limit_usd),
        }

    validator = _schema_validator(str(schema_path.resolve()))
    schema_errors = sorted(validator.iter_errors(package), key=lambda item: list(item.path))
    if schema_errors:
        formatted = [f"Schema: {'/'.join(map(str, err.path)) or '<root>'}: {err.message}" for err in schema_errors]
        raise StudioValidationError(formatted, warnings)

    return {
        "valid": True,
        "package": package,
        "warnings": warnings,
        "exports": {
            "package_filename": f"{draft.slug}.json",
            "instructions_filename": f"{draft.slug}.instructions.md",
        },
    }
