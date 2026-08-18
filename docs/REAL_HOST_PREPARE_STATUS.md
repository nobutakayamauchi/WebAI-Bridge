# Real-host prepare status

Observed on the controlled Oracle host:

```text
controller main: 814e9065bbddc4d7c5eeeb947347c0e42d2a8974
exact target: 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
prepare result: FAIL CLOSED
cause: Git dubious ownership during service-identity local revision check
production service mutation: none
```

A command-scoped `safe.directory` diagnostic returned the exact target SHA, confirming the failure is the Git ownership trust boundary rather than source drift.

The host-safe deploy wrapper is intended to close this single boundary before real-host prepare is rerun. Production apply remains unapproved.
