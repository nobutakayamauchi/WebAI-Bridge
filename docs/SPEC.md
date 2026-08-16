# WebAI Bridge — Product Specification

Status: `PRODUCT_CORE_FROZEN_FOR_DOGFOOD`
Date: 2026-08-16

## Protected outcome

A creator can configure an AI once and distribute it by URL or portable package, while independently deciding:

- what the AI contains;
- who may use it and under what commercial access terms;
- who pays inference cost and where the hard budget stops;
- whether the package is hosted-only, portable, or both.

A non-technical end user should be able to open a smartphone URL and use the AI without installing a GPT/Skill or copying prompts.

## Four independent planes

### 1. AI Package
- name / slug / description
- Instructions
- Knowledge
- provider/model/routing limits
- UI metadata

### 2. Access
Examples:
- free
- first N runs free
- paid from first run
- buy-once
- subscription
- per-use

Access price is the price of the AI/service, not the provider inference charge.

### 3. Inference payer
V0:
- `BYOK`
- `PLATFORM_CREDIT`

Future:
- `USER_WALLET`
- `CREATOR_PAYS`
- `SPONSORED`
- `HYBRID`

### 4. Delivery
- `HOSTED_ONLY`
- `PORTABLE_LICENSE`
- `HOSTED_AND_PORTABLE`

Portable delivery means secrets cannot be assumed secret after export. Creators who require hidden Instructions should use hosted-only delivery.

## Core financial invariant

```text
REQUEST
→ PACKAGE POLICY
→ ACCESS AUTHORIZATION
→ PAYER RESOLUTION
→ CREDENTIAL RESOLUTION
→ BUDGET AUTHORIZATION
→ MODEL ROUTING
→ MAX-COST RESERVATION
→ PROVIDER EXECUTION
→ USAGE OBSERVATION
→ COST CALCULATION
→ LEDGER EVENT
→ RESPONSE
```

No provider call is valid if payer resolution or budget authorization was bypassed.

## V0 scope

Required now:
- package schema
- server-side Instructions
- optional Knowledge binding
- mobile chat URL
- BYOK
- bounded platform credit
- versioned pricing registry
- persistent budget/usage ledger
- server-controlled model allowlist/default
- request/history/rate bounds
- deployment identity surface
- thin Creator Studio capable of generating valid package config

Not required before first dogfood:
- purchased credits
- Stripe
- creator revenue share
- monthly plans
- persistent BYOK secret storage
- full auth/admin system
- automatic social publishing

## Acceptance gates

1. Schema valid.
2. Local runtime + cost authorization valid.
3. Thin Creator Studio generates a package accepted by runtime without hand-editing core code.
4. Live BYOK provider call.
5. Tiny live platform-credit budget; usage reconciles to ledger.
6. Exhausted budget blocks before provider call.
7. Knowledge dogfood with explicit tool-cost policy.
8. iPhone Safari acceptance.
9. Deployment Identity captured.
10. METEOR economic/security attack set passes release blockers.
11. Second AI generated from config only.
12. First assisted customer handoff.
