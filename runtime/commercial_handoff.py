from __future__ import annotations

# Paid browser handoff + server-owned PACKAGE_TEXT Knowledge route surface.
# This surface owns the Knowledge-aware Creator Studio and protects it with
# fail-closed creator authentication whenever Studio is publicly enabled.
import commercial as base
from checkout_browser_binding import install_checkout_browser_binding
from creator_auth import install_creator_auth
from external_entitlement_authority import install_external_entitlement_routes
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
# Stripe completion must prove possession of the initiating browser binding before
# it is allowed to mint the one-time body handoff code. Install this before the
# Studio/auth wrappers so every Creator Studio production route surface inherits it.
install_checkout_browser_binding(base)
install_knowledge_studio_routes(base)
CREATOR_AUTH = install_creator_auth(base)
EXTERNAL_ENTITLEMENT_AUTHORITY = install_external_entitlement_routes(base)
app = base.app
