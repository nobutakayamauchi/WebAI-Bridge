from __future__ import annotations

# Compatibility surface only.
# Browser handoff is implemented by the canonical commercial gateway. This
# dogfood surface adds PACKAGE_TEXT Knowledge without changing the canonical
# free/commercial route until the external gate is proven.
import commercial as base
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


base.core.chat = _knowledge_chat
app = base.app
