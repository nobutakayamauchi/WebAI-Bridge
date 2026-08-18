# Exact-head env-safe prepare runbook

This is the canonical **prepare-only** host entry for the current WebAI Bridge reality gate.

It intentionally separates bootstrap trust from the Python deploy capsule. The controller must be proven clean and synchronized before any committed Python controller object is executed.

## Scope

This runbook may:

- fetch `origin/main`;
- inspect the controller clone;
- stage the exact pinned release and venv;
- run the transient candidate preflight;
- write prepare evidence under `/var/lib/webai-bridge-deploy-control/deploy-evidence`.

It does **not** authorize or perform production apply, service replacement/restart, live payment, or the iPhone/BYOK/revoke acceptance chain.

`deploy/exact_head_deploy_envsafe.py apply ...` is intentionally fail-closed in this controller revision.

## Controller bootstrap

Expected controller:

```text
/opt/webai-bridge-control
```

Use the following root, empty-environment bootstrap. Do not replace it with a normal inherited-shell invocation.

```bash
sudo /usr/bin/env -i \
  PATH=/usr/bin:/bin \
  HOME=/root \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  GIT_CONFIG_SYSTEM=/dev/null \
  GIT_CONFIG_GLOBAL=/dev/null \
  GIT_CONFIG_NOSYSTEM=1 \
  GIT_NO_REPLACE_OBJECTS=1 \
  /bin/sh -ceu '
    C=/opt/webai-bridge-control

    test -d "$C/.git"
    test "$(/usr/bin/stat -c %u "$C")" = 0
    test "$(/usr/bin/stat -c %u "$C/.git")" = 0
    test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 \) -print -quit)"

    ORIGIN=$(/usr/bin/git -C "$C" config --local --get remote.origin.url)
    test "$ORIGIN" = "https://github.com/nobutakayamauchi/WebAI-Bridge.git"

    test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"
    /usr/bin/git -C "$C" fetch --no-tags origin main
    test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main

    R=$(/usr/bin/git -C "$C" rev-parse HEAD)
    test "$R" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"

    /usr/bin/git -C "$C" show "$R:deploy/exact_head_deploy_envsafe.py" |
      /usr/bin/env -i \
        PATH=/usr/bin:/bin \
        HOME=/root \
        LANG=C.UTF-8 \
        LC_ALL=C.UTF-8 \
        WEB_AI_BOOTSTRAP_CLEAN=1 \
        WEB_AI_CONTROLLER_REVISION="$R" \
        /usr/bin/python3 -I - prepare
  '
```

## Why the two empty environments exist

The first `env -i` protects the shell and Git bootstrap from inherited Git, proxy, TLS, Python, pip, or loader control variables.

The second `env -i` is the exact environment accepted by the Python wrapper. The wrapper fails if any undeclared environment key reaches it, then installs its own bounded child-process environment before controller Git operations or dependency execution.

## Prepare trust ordering

Before the base capsule can execute dependency installation, the env-safe wrapper requires:

```text
controller revision pinned
→ controller tree root-owned/non-writable
→ release root root-owned/non-writable
→ venv root root-owned/non-writable
→ any pre-existing exact release root-owned/non-writable
→ any pre-existing exact venv root-owned/non-writable
→ only then base verify/fetch/venv/render/preflight
```

This prevents a HEAD-correct but modified pre-existing release from feeding a modified `requirements.txt` into pip before source verification.

## Evidence boundary

New prepare evidence is root-only and separate from mutable application state:

```text
/var/lib/webai-bridge-deploy-control/deploy-evidence
```

Historical evidence under the older application-state location is historical only; it is not rewritten or inherited as proof for this exact controller/target.

## Expected successful status

The prepare evidence must report:

```text
status = PREPARED_CANDIDATE_PASS
production_mutation = false
production_apply_enabled = false
process_environment_authority = CLEAN_BOOTSTRAP_ALLOWLIST_V1
prepare_trust_authority = ROOT_OWNED_BEFORE_DEPENDENCY_EXECUTION_V1
evidence_authority = SEPARATE_ROOT_ONLY_DEPLOY_CONTROL_STATE_V1
```

The pinned target remains the exact SHA/tree recorded by the env-safe wrapper. A successful prepare does not certify production runtime, Stripe live payment, iPhone browser authority, BYOK, Knowledge retrieval, or revoke→401.
