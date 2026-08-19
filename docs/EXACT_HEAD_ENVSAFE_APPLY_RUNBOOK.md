# Exact-head env-safe transactional apply runbook

This runbook is the canonical host procedure for moving the frozen WebAI Bridge target from **prepared candidate** to **production** after the transactional apply capsule is merged and separately approved.

It does not authorize a merge, production apply, live payment, iPhone/BYOK/Knowledge acceptance, or PR #30 merge by itself.

## Frozen product target

```text
SHA  = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
TREE = 155dc692264a8f7edcd74b0eaff8cba28b0f11ef
```

The apply approval token is the exact 40-hex target SHA above.

## Controller entry

Canonical apply entry:

```text
deploy/exact_head_deploy_envsafe_apply_ready.py
```

Authority chain:

```text
clean root bootstrap
→ exact synchronized controller revision
→ env-safe exact-head prepare / candidate preflight
→ stable previous InvocationID + MainPID + cwd + revision + service hash
→ Human-Gate generation rebound
→ exclusive root-only apply lock
→ separate root-only rollback backup
→ durable PREPARED_FOR_SWITCH transaction
→ SWITCH_ARMED before any service-file mutation
→ candidate/controller/source recheck
→ atomic systemd unit replacement
→ restart
→ stable target InvocationID + MainPID
→ strict bounded HTTPS health
→ bounded Stripe external acceptance (no payment)
→ same-generation post-Stripe health
→ root-only success evidence
→ immutable transaction archive
```

## Root-only control state

The application account does not own these apply assets:

```text
/var/lib/webai-bridge-deploy-control/
  deploy-evidence/
  deploy-backups/
  production-apply/
    apply.lock
    active-apply.json        # exists only while unresolved/in progress
  apply-transactions/
```

Any existing `active-apply.json` is a hard stop. Do not start another production apply until the transaction is inspected and recovered under a separate recovery decision.

## 1. Synchronize controller

Use the same empty-environment/root-trust bootstrap used by the prepare controller. The controller must be clean, on `main`, and exactly equal to `origin/main` before any committed apply object is executed.

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
    test "$(/usr/bin/git -C "$C" config --local --get remote.origin.url)" = "https://github.com/nobutakayamauchi/WebAI-Bridge.git"
    test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"
    test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main
    /usr/bin/git -C "$C" fetch --no-tags origin main
    /usr/bin/git -C "$C" merge --ff-only origin/main
    test "$(/usr/bin/git -C "$C" rev-parse HEAD)" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"
  '
```

## 2. Apply-ready prepare — reversible gate

Run this before requesting the production Human Gate. It performs a fresh exact-head prepare/preflight and records the stable **current production generation** without replacing or restarting the production service.

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
    test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"
    /usr/bin/git -C "$C" fetch --no-tags origin main
    test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main
    R=$(/usr/bin/git -C "$C" rev-parse HEAD)
    test "$R" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"
    /usr/bin/git -C "$C" show "$R:deploy/exact_head_deploy_envsafe_apply_ready.py" |
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

Expected prepare evidence includes:

```text
status = PREPARED_CANDIDATE_PASS
production_mutation = false
production_apply_enabled = true
apply_authority = ROOT_ONLY_TRANSACTIONAL_APPLY_V2
backup_authority = SEPARATE_ROOT_ONLY_SERVICE_BACKUP_V2
transaction_authority = DURABLE_SWITCH_ARMED_FAIL_CLOSED_V2
previous_generation_authority = STABLE_INVOCATION_ID_MAINPID_SNAPSHOT_V1
human_gate_authority = PRE_APPLY_GENERATION_REBOUND_BEFORE_MUTATION_V1
previous_production_snapshot = {...}
target_already_active = false
```

`target_already_active=true` means production is already on the frozen target. Do not run apply again; verify the existing generation instead.

## 3. Production apply — HUMAN GATE

**STOP HERE until the explicit production Human Gate is approved.**

Only after approval, use the same clean bootstrap and the exact target SHA token:

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
    test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"
    /usr/bin/git -C "$C" fetch --no-tags origin main
    test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main
    R=$(/usr/bin/git -C "$C" rev-parse HEAD)
    test "$R" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"
    /usr/bin/git -C "$C" show "$R:deploy/exact_head_deploy_envsafe_apply_ready.py" |
      /usr/bin/env -i \
        PATH=/usr/bin:/bin \
        HOME=/root \
        LANG=C.UTF-8 \
        LC_ALL=C.UTF-8 \
        WEB_AI_BOOTSTRAP_CLEAN=1 \
        WEB_AI_CONTROLLER_REVISION="$R" \
        /usr/bin/python3 -I - apply \
          --approve 5fd4c791e636464f1a3b5195a3e1048b505d6de5
  '
```

This command performs a **fresh prepare/preflight again** before mutation. It does not inherit a stale prepare success.

## Success condition

Production apply is successful only when the root-only evidence reports:

```text
status = DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS
production_mutation = true
running_identity.revision = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
stripe_external_acceptance = PASS
live_payment_performed = false
human_gate_generation_revalidated = true
```

The readiness overlay additionally requires the same `InvocationID + MainPID` through target identity, HTTPS health, Stripe external acceptance, and post-Stripe health.

## Failure / rollback conditions

Expected fail-closed statuses:

```text
PRE_SWITCH_FAILURE
ROLLBACK_VERIFIED_AFTER_FAILURE
ROLLBACK_FAILED
```

`ROLLBACK_VERIFIED_AFTER_FAILURE` means the target failed but the previous exact service file, previous revision/cwd generation, and HTTPS health were restored and verified.

`ROLLBACK_FAILED` is a hard stop. The active transaction must remain in root-only control state and **no further apply may run**.

## Crash / forced termination boundary

Before service-file replacement, the journal transitions to:

```text
phase = SWITCH_ARMED
production_mutation = false
production_mutation_possible = true
```

Therefore a process kill or host failure in the atomic-switch window cannot be misreported as proof that no mutation occurred.

If `active-apply.json` exists after an interrupted run, first inspect only:

```bash
sudo python3 -m json.tool /var/lib/webai-bridge-deploy-control/production-apply/active-apply.json
```

Then compare the current service/process reality with the recorded `old_service_sha256`, `candidate_service_sha256`, `previous_service`, and `backup_service`. Recovery itself can replace/restart production and is therefore a **separate mutation Human Gate**; do not improvise recovery by deleting the active transaction marker.

## Non-claims

This apply gate does not certify:

- a live Stripe charge/payment;
- browser-bound paid completion;
- iPhone Safari body handoff;
- BYOK live provider response;
- PACKAGE_TEXT Knowledge behavior;
- revoke followed by immediate 401;
- PR #30 merge readiness.

Those remain later reality gates after exact production apply passes.
