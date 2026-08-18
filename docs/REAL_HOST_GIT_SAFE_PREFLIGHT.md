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

`deploy/exact_head_deploy_hostsafe.py` loads the canonical deploy capsule from the committed controller Git object and overlays only the generated service's `ExecStartPre` command with command-scoped Git configuration:

```text
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=<exact release path>
```

The long-running WebAI `ExecStart` does not inherit this Git trust configuration, the exact target source remains root-owned, and the evidence records both the raw target-rendered service hash and the overlaid candidate service hash.

## Non-claims

This does not certify production apply, HTTPS health, Stripe external acceptance, live payment, browser handoff, BYOK, Knowledge retrieval, or revoke-to-401; those remain later gates.
