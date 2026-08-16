# Token Wallet / Cost Router

Status: `CORE_INVARIANT / V0_REQUIRED`

## Why it exists

The durable business question is not merely “can we host an AI?” It is:

> Who is financially authorized to pay for this inference, and how much may be spent before execution begins?

Therefore billing authority is a runtime authorization boundary.

## Hard invariant

```text
NO PAYER RESOLUTION
→ NO BUDGET AUTHORIZATION
→ NO MODEL EXECUTION
```

## V0 payer modes

### BYOK
User supplies the provider API credential. Provider inference cost belongs to that user's provider account. V0 intentionally avoids persistent key storage.

### PLATFORM_CREDIT
Operator/creator explicitly funds a bounded allowance. The runtime must reserve budget before provider execution and fail closed when the remaining allowance cannot cover the reservation.

## Pricing registry rules

```text
MODEL NAME != PRICE
CURRENT PRICE != HISTORICAL PRICE
MISSING PRICE != ZERO COST
```

Pricing is versioned external evidence. Every usage event binds model + pricing version.

Snapshot reviewed 2026-08-16 for the 2026-07-30 OpenAI price-change announcement:

- `gpt-5.6-luna`: input $0.20 / 1M, output $1.20 / 1M
- `gpt-5.6-terra`: input $2.00 / 1M, output $12.00 / 1M
- `gpt-5.6-sol`: input $5.00 / 1M, output $30.00 / 1M

Source is recorded in `runtime/pricing.json`; these are not eternal constants.

## Cost-aware routing

Quality control can also be cost control:

```text
Luna
→ escalate only with evidence
Terra
→ escalate only with evidence
Sol
→ expensive validation only when justified
```

The user must not be able to force an otherwise-disallowed expensive tier through prompt text.

## Ledger minimum

For platform-funded execution record at least:
- package
- payer mode
- budget ID
- provider/model
- pricing version
- input/output tokens where observed
- reserved cost
- actual cost where observable
- charged cost
- result

Never log provider API keys in ordinary usage events.

## Economic METEOR cases

- payer bypass
- budget exhaustion bypass
- concurrent double-spend
- user-forced model escalation
- missing price treated as free
- provider failure charged as success
- BYOK secret leakage
- shared public URL becoming unlimited operator subsidy
- Knowledge/tool cost silently omitted
