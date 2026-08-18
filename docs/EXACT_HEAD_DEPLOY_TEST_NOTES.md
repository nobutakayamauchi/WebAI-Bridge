# Exact-head deploy test notes

Initial isolated validation before opening the Draft PR:

```text
python -m py_compile deploy/exact_head_deploy.py runtime/tests/test_exact_head_deploy.py
pytest -q runtime/tests/test_exact_head_deploy.py
→ 6 passed
```

After merge-readiness Counter-DA found the rollback-evidence gap and controller-identity edge cases, the isolated regression set was expanded and rerun:

```text
pytest -q test_exact_head_deploy.py
→ 10 passed
```

Covered fail-closed properties now include:

- target SHA/tree/domain are pinned;
- tracked modification is rejected;
- untracked runtime code is rejected;
- only the pinned external `runtime/.venv` link is tolerated;
- controller worktree must be completely clean;
- controller must run canonical `main == origin/main`;
- overlap is checked against the actual systemd production `WorkingDirectory`, not only the unit-file text;
- candidate systemd preflight cannot launch Uvicorn;
- production apply rejects approval text that is not the exact pinned SHA;
- rollback must restore the exact previous unit hash;
- rollback must return to the previous runtime cwd and `DEPLOYED_REVISION`;
- a mismatched rollback identity fails closed;
- prepare/deploy evidence paths are unique and final records are read-only.

GitHub CI remains the canonical repository-wide regression gate after each branch-head change. A local isolated PASS is not promoted to production evidence.
