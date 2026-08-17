from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

from commercial_studio import adapt_manual_hosted_entitlement
from knowledge_artifact import canonical_knowledge_file, text_sha256
from package_knowledge import PACKAGE_TEXT_BACKEND
from studio import StudioDraft, StudioValidationError

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_STUDIO_PAGE = BASE_DIR.parent / "creator-studio" / "knowledge.html"


class KnowledgeStudioDraft(StudioDraft):
    """Creator Studio draft with a first-class server-owned Knowledge artifact."""

    knowledge_text: str = Field(default="", max_length=1_000_000)
    knowledge_max_context_chars: int = Field(default=6000, ge=256, le=50_000)
    knowledge_max_chunks: int = Field(default=4, ge=1, le=12)
    knowledge_chunk_chars: int = Field(default=1800, ge=200, le=8000)


def build_knowledge_studio_result(*, core, payload: KnowledgeStudioDraft) -> dict:
    # The legacy Studio validator knows only provider vector-store Knowledge. Build
    # the ordinary package with Knowledge disabled, then bind the new deterministic
    # PACKAGE_TEXT contract and validate the final package again.
    base_payload = payload.model_copy(update={
        "knowledge_enabled": False,
        "knowledge_vector_store_env": "",
        "knowledge_reserve_tokens": 0,
        "knowledge_platform_tool_reserve_usd": 0,
    })
    result = core.build_package(
        base_payload,
        schema_path=core.PACKAGE_SCHEMA_FILE,
        available_models=set(core.pricing.models.keys()),
    )
    package = deepcopy(result["package"])
    warnings = list(result.get("warnings") or [])
    exports = dict(result.get("exports") or {})

    if payload.knowledge_enabled:
        text = payload.knowledge_text
        errors: list[str] = []
        if not text.strip():
            errors.append("Knowledge text must not be empty when Knowledge is enabled.")
        if "\x00" in text:
            errors.append("Knowledge text must not contain NUL bytes.")
        if (package.get("delivery") or {}).get("mode") != "HOSTED_ONLY":
            errors.append("PACKAGE_TEXT Knowledge v1 is Hosted Only; portable Knowledge is not implemented.")
        if errors:
            raise StudioValidationError(errors, warnings)

        slug = package["slug"]
        package["knowledge"] = {
            "enabled": True,
            "backend": PACKAGE_TEXT_BACKEND,
            "file": canonical_knowledge_file(slug),
            "artifact_sha256": text_sha256(text),
            "max_context_chars": payload.knowledge_max_context_chars,
            "max_chunks": payload.knowledge_max_chunks,
            "chunk_chars": payload.knowledge_chunk_chars,
            # PACKAGE_TEXT has no separate provider tool charge. Its retrieved
            # text is ordinary model input and is charged through inference.
            "reserve_tokens": 0,
            "platform_tool_reserve_usd_micros": 0,
        }
        exports["knowledge_filename"] = f"{slug}.knowledge.md"
        warnings.append(
            "Knowledge is exported as a server-owned PACKAGE_TEXT artifact. Install Package JSON, Instructions, and Knowledge as one bundle before activation."
        )
    else:
        package["knowledge"] = {
            "enabled": False,
            "reserve_tokens": 0,
            "platform_tool_reserve_usd_micros": 0,
        }

    schema_errors = core.validate_package_document(package, schema_path=core.PACKAGE_SCHEMA_FILE)
    if schema_errors:
        raise StudioValidationError(schema_errors, warnings)

    result["package"] = package
    result["exports"] = exports
    result["warnings"] = warnings
    result["knowledge_artifact"] = {
        "enabled": bool(payload.knowledge_enabled),
        "filename": exports.get("knowledge_filename"),
        "sha256": (package.get("knowledge") or {}).get("artifact_sha256"),
        "chars": len(payload.knowledge_text) if payload.knowledge_enabled else 0,
    }

    # Re-run the commercial adapter after final package construction so the
    # narrow BUY_ONCE/SUBSCRIPTION + Hosted + BYOK activation path is represented.
    return adapt_manual_hosted_entitlement(result)


def install_knowledge_studio_routes(base) -> None:
    """Replace only the Studio routes on the paid Knowledge route surface.

    The rest of commercial_handoff remains the canonical paid runtime. Removing
    the old Studio routes before adding these avoids ambiguous duplicate FastAPI
    route ordering while leaving all checkout/chat routes untouched.
    """

    studio_paths = {"/studio", "/api/studio/options", "/api/studio/validate"}
    base.app.router.routes[:] = [
        route for route in base.app.router.routes
        if getattr(route, "path", None) not in studio_paths
    ]

    @base.app.get("/studio")
    def knowledge_creator_studio_page():
        base.core.require_studio_enabled()
        if not KNOWLEDGE_STUDIO_PAGE.exists():
            raise HTTPException(status_code=503, detail="Knowledge Creator Studio UI is missing")
        return FileResponse(KNOWLEDGE_STUDIO_PAGE)

    @base.app.get("/api/studio/options")
    def knowledge_creator_studio_options() -> dict:
        options = base.core.creator_studio_options()
        options.update({
            "knowledge_backend": PACKAGE_TEXT_BACKEND,
            "knowledge_artifact_export": True,
            "knowledge_bundle_install": "PACKAGE_JSON_PLUS_INSTRUCTIONS_PLUS_KNOWLEDGE",
            "knowledge_portable_runtime": "NOT_IMPLEMENTED",
            "commercial_enforcement": "ACTIVATION_REQUIRED",
        })
        return options

    @base.app.post("/api/studio/validate")
    def knowledge_creator_studio_validate(payload: KnowledgeStudioDraft, request: Request) -> dict:
        base.core.require_studio_enabled()
        base.core.enforce_rate_limit(request)
        try:
            return build_knowledge_studio_result(core=base.core, payload=payload)
        except StudioValidationError as exc:
            raise HTTPException(status_code=422, detail={"errors": exc.errors, "warnings": exc.warnings}) from None
