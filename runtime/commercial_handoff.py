from __future__ import annotations

# Paid browser handoff + server-owned PACKAGE_TEXT Knowledge route surface.
# This surface now also owns the Knowledge-aware Creator Studio and fails
# startup closed when an activated PACKAGE_TEXT artifact is missing/corrupt.
import commercial as base
from knowledge_artifact import validate_package_text_artifact
from knowledge_studio import install_knowledge_studio_routes
from package_knowledge import chat_with_package_text

_original_chat = base.core.chat


def _knowledge_chat(*, payload, request, byok_api_key=None):
    return chat_with_package_text(
        core=base.core,
        original_chat=_original_chat,
        payload=payload,
        request=request,
        byok_api_key=byok_api_key,
    )


for _config in base.core.registry.apps.values():
    if _config.get("status") in base.core.RUNNABLE_STATUSES:
        _errors = validate_package_text_artifact(
            config_dir=base.core.CONFIG_DIR,
            app_config=_config,
            require_digest=False,  # legacy dogfood bindings predate digest metadata
        )
        if _errors:
            raise RuntimeError(
                f"Activated PACKAGE_TEXT Knowledge is invalid for {_config.get('slug')}: " + "; ".join(_errors)
            )

base.core.chat = _knowledge_chat
install_knowledge_studio_routes(base)
app = base.app
