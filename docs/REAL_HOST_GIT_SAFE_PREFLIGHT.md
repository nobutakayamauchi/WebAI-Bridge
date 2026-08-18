# Real-host Git ownership preflight finding

## Finding

The first exact-head real-host `prepare` reached the transient service-identity preflight and failed closed with:

```text
LOCAL_REVISION_CHECK_FAILED
fatal: detected dubious ownership in repository
```

The exact release is intentionally root-owned while the runtime preflight executes as `webai`. A direct diagnostic proved that the exact release HEAD is readable when Git trust is scoped only to that exact release path.

## Fix boundary

Do not `chown` the release to `webai` and do not add a host-global `safe.directory` exception.

`deploy/exact_head_deploy_hostsafe.py` requires one explicitly pinned controller revision and loads the base deploy capsule from that exact revision rather than re-reading mutable `HEAD`.

The overlay is accepted only when the generated `ExecStartPre` exactly equals the pinned release's expected `deployment_preflight_handoff.py` command. That command is wrapped with a command-local environment that removes Git repository/config redirects, fixes `PATH=/usr/bin:/bin`, clears inherited Python path/home injection, disables system/global Git config, and sets exactly one protected `safe.directory` entry for the exact release path.

Dynamic-loader injection cannot be safely removed after `/usr/bin/env` has already started, so the candidate service also locks `LD_PRELOAD`, `LD_AUDIT`, `LD_LIBRARY_PATH`, `PYTHONPATH`, and `PYTHONHOME` after the EnvironmentFile and sets `PYTHONNOUSERSITE=1`. The long-running WebAI `ExecStart` command remains unchanged and receives no Git trust configuration.

The prepare gate requires the release source, exact venv, controller root, and controller Git metadata to remain root-owned and non-group/world-writable. The exact release source rejects symlinks except the separately verified generated `runtime/.venv` link; the pinned target tree contains no tracked symlinks.

Evidence records the raw target-rendered service hash separately from the candidate overlay service hash and labels the permitted overlay classes as the exact `ExecStartPre` Git-trust wrapper plus the fixed runtime environment locks.

## Non-claims

This does not certify production apply, HTTPS health, Stripe external acceptance, live payment, browser handoff, BYOK, Knowledge retrieval, or revoke-to-401; those remain later gates.
