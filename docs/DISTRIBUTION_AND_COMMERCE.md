# Distribution and Commerce Model

Status: `CORE_SCHEMA / PAYMENT_EXECUTION_DEFERRED`

## Separate the money axes

```text
ACCESS PRICE != INFERENCE COST
```

A paid AI may still use BYOK. A free AI may still consume creator-funded inference. A subscription never implies unlimited tokens unless an explicit budget policy says so.

## Creator choices

### Access policy
- free
- N included runs then paid
- paid from first use
- buy-once
- subscription
- per-use

### Inference payer policy
- user BYOK
- user/platform wallet
- creator pays
- sponsor pays
- hybrid sequence, e.g. creator pays first 10 calls then wallet or BYOK

### Delivery policy
- hosted-only URL
- portable package/license
- hosted + portable

## Example combinations

### Paid package + BYOK
Creator charges for the AI design/Knowledge/updates. User pays provider inference directly with their own API key.

### Free consultation AI + creator budget
Company publishes a free product consultation AI while setting a hard monthly inference budget.

### First N free, then user choice
Creator funds the first N calls. After allowance ends the user chooses WebAI credit or BYOK.

## Creator Studio v0 flow

```text
AI basics
→ Instructions
→ Knowledge
→ Access terms
→ Included/free allowance
→ Who pays inference
→ Delivery mode
→ Test
→ Publish URL
```

Payment collection itself is not required for the first dogfood. The schema is frozen first so Stripe/wallet/subscription later attach without rewriting provider execution.

## Hard rules

```text
PAID ACCESS != PLATFORM PAYS INFERENCE
FREE ACCESS != FREE INFERENCE
BYOK != FREE PACKAGE
SUBSCRIPTION != UNLIMITED TOKENS
PORTABLE != SECRET INSTRUCTIONS
```
