# Paid Package Knowledge iPhone Dogfood — 2026-08-18

Status: **PASS**

## Goal

Prove that the already-working paid Hosted BYOK flow can answer from creator/server-owned Knowledge that is not present in the buyer prompt or creator Instructions.

## Tested path

```text
existing live Stripe BUY_ONCE entitlement
→ Safari protected paid page
→ ephemeral buyer BYOK session
→ PACKAGE_TEXT server-owned Knowledge
→ local bounded retrieval
→ OpenAI inference
→ answer rendered in iPhone Safari
```

## Runtime state observed before the test

- `commercial_handoff:app` running on `127.0.0.1:8080`
- local `/health` returned `status=ok`
- existing Cloudflare Quick Tunnel process remained live
- existing paid `v3` entitlement/payment state was reused; no second purchase was required

## Deterministic Knowledge fixture

The package-owned Knowledge contained facts intentionally absent from the browser prompt:

- verification phrase: `青いカワセミ`
- internal identifier: `ORBIT-CARP-7319`

## External iPhone Safari query

The buyer asked:

```text
Knowledgeに書かれている確認用の合言葉は何？ 内部識別子も答えて。
```

Observed answer:

```text
確認用の合言葉は「青いカワセミ」です。
内部識別子は「ORBIT-CARP-7319」です。
```

Both Knowledge-only values were returned correctly in iPhone Safari while the paid entitlement and ephemeral BYOK session remained enforced.

## Result

For the tested Hosted BUY_ONCE + BYOK shape, WebAI Bridge now proves:

```text
Creator Instructions
+ creator/server-owned Knowledge
+ paid access entitlement
+ buyer-funded inference
```

The full Knowledge source remains server-owned; bounded retrieved context is sent to the model provider when relevant. No provider key, Stripe secret, webhook secret, entitlement token, or full Knowledge source is recorded here.

## Promotion decision

The external promotion gate in `docs/PACKAGE_KNOWLEDGE_V1.md` is satisfied for the tested paid iPhone/BYOK path.

Not yet proved: Creator Studio Knowledge artifact export/install, semantic/vector retrieval, multi-file manifests, Knowledge version lifecycle, portable Knowledge, production multi-worker coordination, or permanent production infrastructure.
