# Next stop condition: Knowledge self-service

The paid runtime gate is no longer the blocker. The remaining productization gap is creator self-service.

Current Creator Studio still models Knowledge primarily as an operator/server Vector Store binding and exports only:

- Package JSON
- Instructions

It does not yet export a creator-owned `Knowledge` artifact that can be installed atomically with the package. Therefore a third-party creator still needs an operator to bind `PACKAGE_TEXT` after deployment.

Next implementation target:

```text
Creator Studio Knowledge input
→ Package JSON declares PACKAGE_TEXT
→ Knowledge artifact export
→ atomic Package + Instructions + Knowledge install
→ preflight
→ activation / sale
```

Until that exists, the tested paid AI is sellable operationally but not yet self-service for arbitrary creators.
