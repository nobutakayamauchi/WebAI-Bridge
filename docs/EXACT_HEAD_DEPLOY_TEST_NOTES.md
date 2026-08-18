# Exact-head deploy test notes

Local isolated validation performed before opening the Draft PR:

```text
python -m py_compile deploy/exact_head_deploy.py runtime/tests/test_exact_head_deploy.py
pytest -q runtime/tests/test_exact_head_deploy.py
→ 6 passed
```

Covered fail-closed properties:

- target SHA/tree/domain are pinned;
- tracked modification is rejected;
- untracked runtime code is rejected;
- only the pinned external `runtime/.venv` link is tolerated;
- controller/live WorkingDirectory overlap is rejected;
- candidate systemd preflight cannot launch Uvicorn;
- production apply rejects approval text that is not the exact pinned SHA.

GitHub CI remains the canonical repository-wide regression gate after the Draft PR is opened.
