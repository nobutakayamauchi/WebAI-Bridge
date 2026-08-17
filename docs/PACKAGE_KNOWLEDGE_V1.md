# Package-owned Knowledge v1

Status: `DOGFOOD / PAID_HANDOFF_GATE`

## Goal

Move the proven paid Hosted BYOK path from a generic paid chat to a package that sells both:

```text
Creator Instructions
+ Creator Knowledge
+ Hosted access entitlement
```

without forcing the buyer's OpenAI API key to own the creator's Knowledge store.

## Why the previous File Search binding is not sufficient for distributed BYOK

The existing runtime can bind `file_search` to an OpenAI Vector Store ID. OpenAI documents Vector Stores as Project-scoped API objects. A buyer BYOK key from an unrelated OpenAI Project therefore cannot be assumed to have access to a creator-owned Vector Store.

Official references:

- https://platform.openai.com/docs/api-reference/vector-stores
- https://platform.openai.com/docs/assistants/deep-dive

That means this shape is not a safe general sales contract:

```text
creator-owned OpenAI Vector Store
+ arbitrary buyer BYOK key
```

It may work for same-Project/self-use cases, but WebAI Bridge must not advertise it as portable across unrelated buyer Projects.

## v1 shape: PACKAGE_TEXT

Package-owned Knowledge is stored beside the deployed package authority:

```text
<config-dir>/<slug>.json
<config-dir>/<slug>.instructions.md
<config-dir>/<slug>.knowledge.md
```

The Package JSON binds it explicitly:

```json
{
  "knowledge": {
    "enabled": true,
    "backend": "PACKAGE_TEXT",
    "file": "apps/<slug>.knowledge.md",
    "max_context_chars": 6000,
    "max_chunks": 4,
    "chunk_chars": 1800,
    "vector_store_env": "",
    "reserve_tokens": 0,
    "platform_tool_reserve_usd_micros": 0
  }
}
```

The deployed Knowledge file must be regular, non-symlink, UTF-8, non-empty, bounded, and owner-only (`0600`). The logical file path is canonical and resolved only from `WEB_AI_CONFIG_DIR`.

## Retrieval

v1 performs deterministic local text retrieval before the provider call. It uses normalized lexical matching with ASCII terms and Japanese/CJK n-grams, selects bounded relevant chunks, and injects only those chunks into the provider instructions.

This is intentionally **not** being called semantic/vector retrieval. It exists to prove the commercial Knowledge ownership boundary before adding a heavier local embedding/index service.

When no relevant chunk matches, no Knowledge text is injected.

## Trust boundary

Retrieved Knowledge is labeled as **untrusted reference data, not instructions**. The provider receives an explicit higher-level rule not to follow role changes, policy overrides, tool instructions, or other commands found inside Knowledge text.

This reduces prompt-injection confusion but is not a mathematical guarantee against all model-level instruction-following failures.

## Cost / payer boundary

For `PACKAGE_TEXT + BYOK`:

- the creator/server owns and reads the Knowledge file;
- the buyer's API key still pays model inference;
- WebAI Bridge sends only the selected Knowledge chunks with the model request;
- no OpenAI File Search tool is invoked;
- no creator OpenAI Vector Store is required;
- no extra provider File Search tool reserve is charged by WebAI Bridge.

The selected Knowledge text necessarily transits the model provider because it is included in the inference request. `HOSTED_ONLY` means the full Knowledge source is not handed to the buyer, not that retrieved snippets never leave the WebAI Bridge server.

## Operator binding v1

Until Creator Studio exports the Knowledge artifact directly, the operator can bind a UTF-8 Knowledge file to an already deployed Hosted package with:

```bash
python knowledge_bind_cli.py --config /path/to/apps/<slug>.json --knowledge /path/to/knowledge.md
```

The operation stages the Knowledge file before updating Package JSON, uses owner-only permissions, and rolls the Knowledge asset back if Package JSON commit fails.

For the existing paid iPhone dogfood state, `paid_knowledge_dogfood_prepare.py` binds a deterministic test Knowledge fixture without touching entitlement/payment state.

## Promotion gate

PACKAGE_TEXT may move from the `commercial_handoff` dogfood surface into the canonical commercial runtime only after a real paid iPhone/BYOK run proves:

```text
existing paid entitlement
→ server-owned Knowledge binding
→ deployment preflight PASS
→ Safari protected paid page
→ ephemeral buyer BYOK
→ query whose answer exists only in Knowledge
→ correct provider response
→ response metadata reports PACKAGE_TEXT / chunks_used > 0
```

## Explicitly not yet claimed

- Creator Studio Knowledge artifact export/install is not yet canonical.
- Retrieval is lexical v1, not embeddings/vector semantic retrieval.
- Multi-file Knowledge manifests are not implemented.
- Knowledge updates/version pinning are not implemented.
- Production multi-worker cache/index coordination is not implemented.
- Portable Knowledge remains unimplemented.
