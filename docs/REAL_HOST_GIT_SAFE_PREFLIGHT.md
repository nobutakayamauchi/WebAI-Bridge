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

`deploy/exact_head_deploy_hostsafe.py` now requires one explicitly pinned controller revision and loads the base deploy capsule from that exact revision rather than re-reading mutable `HEAD`.

The overlay is accepted only when the generated `ExecStartPre` exactly equals the pinned release's expected `deployment_preflight_handoff.py` command. That command is wrapped with a command-local environment that:

- removes Git repository/config redirect variables such as `GIT_DIR`, `GIT_WORK_TREE`, and inherited Git config paths;
- fixes `PATH=/usr/bin:/bin`;
- clears inherited `PYTHONPATH` and `PYTHONHOME`;
- disables system/global Git config for the check;
- sets exactly one protected `safe.directory` entry for the exact release path.

The long-running WebAI `ExecStart` remains unchanged and receives no Git trust overlay.

The prepare gate also requires the release source, exact venv, controller root, and controller Git metadata to remain root-owned and non-group/world-writable. The exact release source rejects symlinks except the separately verified generated `runtime/.venv` link; the pinned target tree contains no tracked symlinks.

Evidence records the raw target-rendered service hash separately from the candidate overlay service hash and labels the permitted delta as `ONLY_EXECSTARTPRE`.

## Non-claims

This does not certify production apply, HTTPS health, Stripe external acceptance, live payment, browser handoff, BYOK, Knowledge retrieval, or revoke-to-401; those remain later gates.
