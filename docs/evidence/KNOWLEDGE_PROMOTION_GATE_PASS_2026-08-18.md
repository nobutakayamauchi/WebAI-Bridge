# Package Knowledge promotion gate — PASS

Date: 2026-08-18 JST

The external gate defined for `PACKAGE_TEXT` has passed on the paid iPhone/BYOK route.

Observed end-to-end result:

```text
paid entitlement
→ Safari protected page
→ ephemeral buyer BYOK
→ server-owned PACKAGE_TEXT retrieval
→ provider inference
→ correct Knowledge-only answer
```

Verification values returned correctly:

- `青いカワセミ`
- `ORBIT-CARP-7319`

Promotion of the Knowledge capability itself is approved for the tested Hosted BUY_ONCE + BYOK shape. Self-service Creator Studio Knowledge artifact creation/install remains a separate productization gate.
