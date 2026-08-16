# Cost Router

The current executable v0 cost router lives in `runtime/cost_router.py` so the dogfood runtime stays small.

This directory marks the product boundary for later extraction when multiple runtimes/providers justify a standalone component. Do not split it merely for aesthetic architecture.

Protected outcome: acceptable AI quality inside an explicit authorized cost/risk envelope.
