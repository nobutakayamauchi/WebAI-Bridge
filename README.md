# WebAI-Bridge

Create, distribute, monetize, and run portable Web AI packages with Knowledge, BYOK, and cost-aware inference routing.

## Product boundary

WebAI Bridge is not only a GPT migration utility. It is an **AI Package Platform** with four independent controls:

1. **AI Package** — name, description, Instructions, Knowledge, model/routing policy.
2. **Access** — free, included allowance, paid access, buy-once, subscription, per-use.
3. **Inference payer** — BYOK, platform/user credit, creator-funded, sponsored, or hybrid.
4. **Delivery** — hosted URL, portable package, or both.

Hard rule:

```text
ACCESS PRICE != INFERENCE COST
NO PAYER RESOLUTION -> NO BUDGET AUTHORIZATION -> NO MODEL EXECUTION
```

## Repository structure

```text
creator-studio/   Thin creator configuration surface (next active build)
runtime/          Hosted Web AI runtime + mobile chat + ledger
cost-router/      Cost/payer boundary documentation and extraction target
package-schema/   Canonical AI Package contract
docs/             Product, cost and distribution specifications
```

## Current status

`DOGFOOD / NOT_PRODUCTION`

The initial runtime has been extracted from the Limit Development dogfood episode. Local regression evidence at extraction time: **12 passed**. Live provider, mobile, deployment and commercial payment validation remain separate gates.

## Origin / evidence

The original dogfood evidence remains in `nobutakayamauchi/RS-AI-limit-development`, Issue #10 and Draft PR #11. This repository is now the product implementation source; the Limit Development repository remains the experimental evidence source.

## License

No license is granted yet. Package portability and code licensing will be decided deliberately rather than inferred from repository visibility.
