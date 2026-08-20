from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

import package_bundle_cli
from commercial_studio import MANUAL_WARNING, adapt_manual_hosted_entitlement
from knowledge_artifact import canonical_knowledge_file, text_sha256
from package_knowledge import PACKAGE_TEXT_BACKEND
from studio import StudioDraft, StudioValidationError

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_STUDIO_PAGE = BASE_DIR.parent / "creator-studio" / "knowledge.html"
KNOWLEDGE_SALE_WARNING = (
    "Paid Hosted sale still requires explicit package activation and correctly configured Stripe checkout/webhook/browser handoff. "
    "Draft validation does not itself prove a live Stripe endpoint or buyer entitlement."
)


class KnowledgeStudioDraft(StudioDraft):
    """Creator Studio draft with a first-class server-owned Knowledge artifact."""

    knowledge_text: str = Field(default="", max_length=1_000_000)
    knowledge_max_context_chars: int = Field(default=6000, ge=256, le=50_000)
    knowledge_max_chunks: int = Field(default=4, ge=1, le=12)
    knowledge_chunk_chars: int = Field(default=1800, ge=200, le=8000)


class KnowledgeStudioPublishDraft(KnowledgeStudioDraft):
    """Explicit creator-authorized request to install and activate one validated bundle."""

    publish_confirmed: bool = False


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
    adapted = adapt_manual_hosted_entitlement(result)
    if payload.access_mode in {"BUY_ONCE", "SUBSCRIPTION"}:
        adapted["warnings"] = [w for w in adapted.get("warnings", []) if w != MANUAL_WARNING]
        if KNOWLEDGE_SALE_WARNING not in adapted["warnings"]:
            adapted["warnings"].append(KNOWLEDGE_SALE_WARNING)
    return adapted


def _write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    os.chmod(path, 0o600)


def _publish_validated_bundle(*, base, payload: KnowledgeStudioPublishDraft) -> dict:
    if not payload.publish_confirmed:
        raise HTTPException(status_code=400, detail="Explicit publish confirmation is required")
    if payload.access_mode != "BUY_ONCE":
        raise HTTPException(status_code=422, detail="Direct publish v1 supports BUY_ONCE only")
    if not payload.stripe_link_matches_configuration:
        raise HTTPException(status_code=422, detail="Stripe Payment Link creator attestation is required before publish")

    try:
        result = build_knowledge_studio_result(core=base.core, payload=payload)
    except StudioValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors, "warnings": exc.warnings}) from None

    package = result["package"]
    slug = str(package.get("slug") or "")
    checkout = (package.get("access") or {}).get("checkout") or {}
    config_dir = Path(base.core.CONFIG_DIR)

    # Browser downloads are optional. The authenticated creator can publish the
    # exact validated three-artifact result directly to the private server state.
    # Source files are ephemeral and owner-only; package_bundle_cli remains the
    # single authority for Package JSON-last install and Knowledge integrity.
    with tempfile.TemporaryDirectory(prefix=".studio-publish-", dir=str(config_dir)) as temp_name:
        temp_dir = Path(temp_name)
        os.chmod(temp_dir, 0o700)
        package_source = temp_dir / "package.in"
        instructions_source = temp_dir / "instructions.in"
        knowledge_source = temp_dir / "knowledge.in"
        _write_private(package_source, json.dumps(package, ensure_ascii=False, indent=2) + "\n")
        _write_private(instructions_source, payload.instructions + "\n")
        _write_private(knowledge_source, payload.knowledge_text)

        try:
            installed = package_bundle_cli.install_bundle(
                package_source=package_source,
                instructions_source=instructions_source,
                knowledge_source=knowledge_source,
                config_dir=config_dir,
                # A prior failed activation may have left a safe non-runnable
                # draft. A fresh authenticated publish may deliberately replace it.
                replace_nonrunnable=True,
            )
        except (SystemExit, RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail={"stage": "install", "error": str(exc)}) from None

        try:
            activated = package_bundle_cli.activate_bundle(
                config_path=Path(installed["package_path"]),
                checkout_reviewed=False,
            )
        except (SystemExit, RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            # Fail closed: an install that cannot activate remains draft and is
            # therefore not sellable/runnable. A later creator publish can retry.
            raise HTTPException(
                status_code=409,
                detail={"stage": "activate", "error": str(exc), "draft_installed": True},
            ) from None

    base.core.registry.reload()
    active = base.core.registry.get(slug)
    if active.get("status") != "active" or (active.get("access") or {}).get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise HTTPException(status_code=500, detail="Published package did not become active in the live registry")

    return {
        "status": "PUBLISHED",
        "package_id": slug,
        "authority_commit": installed["authority_commit"],
        "knowledge_verified": bool(activated.get("knowledge_verified")),
        "knowledge_sha256": activated.get("knowledge_sha256"),
        "runtime": activated.get("runtime"),
        "commercial": activated.get("commercial"),
        "checkout_binding_verification": activated.get("checkout_binding_verification"),
        # Do not hand callers the raw Stripe Payment Link as the normal sale URL:
        # Hosted v1 must start at the buyer page so /api/buy can bind checkout to
        # the initiating browser before Stripe returns the Checkout Session id.
        "checkout_url": f"/api/buy/{slug}",
        "buyer_path": f"/a/{slug}",
        "stripe_payment_link_configured": bool(checkout.get("payment_link_url")),
        "active_packages": len(base.core.registry.apps),
        "secrets_in_output": False,
    }


def install_knowledge_studio_routes(base) -> None:
    """Replace only the Studio routes on the paid Knowledge route surface.

    The rest of commercial_handoff remains the canonical paid runtime. Removing
    the old Studio routes before adding these avoids ambiguous duplicate FastAPI
    route ordering while leaving all checkout/chat routes untouched.
    """

    studio_paths = {"/studio", "/api/studio/options", "/api/studio/validate", "/api/studio/publish"}
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
            "knowledge_direct_publish": True,
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

    @base.app.post("/api/studio/publish")
    def knowledge_creator_studio_publish(payload: KnowledgeStudioPublishDraft, request: Request) -> dict:
        base.core.require_studio_enabled()
        base.core.enforce_rate_limit(request)
        return _publish_validated_bundle(base=base, payload=payload)
