# Exact-head env-safe transactional apply runbook

This is the canonical host procedure for moving the frozen WebAI Bridge target from **prepared candidate** to **production** after the apply capsule is merged and separately approved.

This document does **not** itself authorize a merge, production apply, live payment, iPhone/BYOK/Knowledge acceptance, recovery mutation, or PR #30 merge.

## Frozen rollout identities

```text
TARGET_SHA  = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
TARGET_TREE = 155dc692264a8f7edcd74b0eaff8cba28b0f11ef
EXPECTED_PREVIOUS_SHA = 9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
```

Production mutation is allowed only from the reviewed previous revision above. If production is already on the target, redundant apply is refused. Any other current production revision is a hard stop before mutation.

## Rollback shared-state compatibility

The persistent entitlement / checkout / handoff schema modules are required to be exact Git-blob matches in both the reviewed previous revision and target:

```text
runtime/entitlements.py    dec40737f60cee22170e0996e856de98cb369a93
runtime/checkout_state.py  e40312626d77f5322108ce97d6d6878385e3f46b
runtime/handoff_tickets.py 9c71b08605ab1ab02a309cba52fea249313f8114
```

The apply-ready prepare fetches the reviewed previous SHA and proves those old/target blob identities again. Unknown previous revisions are not treated as rollback-compatible.

This gate covers the persistent stores that production can mutate during normal buyer/webhook traffic while rollout acceptance is running. Creator Studio mutation is not part of the rollout acceptance and should not be performed concurrently with the production switch.

## Canonical controller entry

```text
deploy/exact_head_deploy_envsafe_apply_ready.py
```

Authority chain:

```text
root/no-symlink controller trust BEFORE first Git
→ empty inherited environment
→ exact synchronized controller revision
→ env-safe exact-head prepare / transient candidate preflight
→ reviewed previous revision + shared-state compatibility
→ stable previous InvocationID + MainPID + cwd + revision + service hash
→ pre-mutation generation rebound
→ exclusive root-only apply lock
→ separate root-only rollback backup
→ durable PREPARED_FOR_SWITCH transaction
→ SWITCH_ARMED before any service-file mutation
→ candidate/controller/source/unit recheck
→ atomic systemd unit replacement
→ restart
→ stable target InvocationID + MainPID
→ strict bounded HTTPS health
→ bounded Stripe external acceptance (no payment)
→ same-generation post-Stripe health
→ root-only success evidence
→ committed transaction archive
```

## Root-only control state

```text
/var/lib/webai-bridge-deploy-control/
  deploy-evidence/
  deploy-backups/
  production-apply/
    apply.lock
    active-apply.json
  apply-transactions/
```

Any existing `active-apply.json` is a hard stop. Do not delete it to force another deploy.

## Canonical clean bootstrap

Every controller invocation—not just the first sync—must begin from an empty environment and prove the controller/Git metadata are root-owned and non-writable before the committed apply object is read.

The Python apply-ready wrapper repeats this trust check itself before its first Git command, so the shell check below is defense in depth rather than inherited proof.

### 1. Synchronize controller — reversible

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
    test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"
    test "$(/usr/bin/git -C "$C" config --local --get remote.origin.url)" = "https://github.com/nobutakayamauchi/WebAI-Bridge.git"
    test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"
    test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main
    /usr/bin/git -C "$C" fetch --no-tags origin main
    /usr/bin/git -C "$C" merge --ff-only origin/main
    test "$(/usr/bin/git -C "$C" rev-parse HEAD)" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"
  '
```

### 2. Apply-ready prepare — reversible Human-Gate evidence

This performs a fresh exact-head prepare/preflight and records the stable current production generation. It does not replace/restart production.

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
    test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"
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

Expected evidence includes:

```text
status = PREPARED_CANDIDATE_PASS
production_mutation = false
production_apply_enabled = true
apply_authority = ROOT_ONLY_TRANSACTIONAL_APPLY_V2
backup_authority = SEPARATE_ROOT_ONLY_SERVICE_BACKUP_V2
transaction_authority = DURABLE_SWITCH_ARMED_FAIL_CLOSED_V2
previous_generation_authority = STABLE_INVOCATION_ID_MAINPID_SNAPSHOT_V1
bootstrap_controller_trust_authority = ROOT_OWNED_GIT_BEFORE_FIRST_GIT_V1
pre_mutation_generation_authority = PRE_MUTATION_GENERATION_REBOUND_V2
rollback_state_compatibility_authority = EXACT_SHARED_STATE_SCHEMA_BLOB_EQUIVALENCE_V1
expected_previous_revision = 9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
previous_production_supported = true
target_already_active = false
previous_production_snapshot = {...}
```

If `previous_production_supported=false`, stop. If `target_already_active=true`, do not reapply; verify the already-running target instead.

## 3. Production apply — HUMAN GATE / irreversible service mutation

**STOP HERE until explicit production apply approval is given.**

After approval, execute the same root-trusted empty bootstrap with exact target SHA as approval token. The command performs a **fresh prepare/preflight again** and re-observes the previous production generation before the first mutation; it does not inherit the earlier prepare PASS.

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
    test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"
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

## Success condition

```text
status = DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS
production_mutation = true
running_identity.revision = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
stripe_external_acceptance = PASS
live_payment_performed = false
pre_mutation_generation_revalidated = true
expected_previous_revision = 9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
```

The readiness layer additionally requires one unchanged `InvocationID + MainPID` through target identity, HTTPS health, Stripe external acceptance, and post-Stripe health.

## Failure / rollback conditions

```text
PRE_SWITCH_FAILURE
ROLLBACK_VERIFIED_AFTER_FAILURE
ROLLBACK_FAILED
```

`ROLLBACK_VERIFIED_AFTER_FAILURE` means the exact previous unit was restored and the previous revision/cwd plus HTTPS health were verified after restart.

`ROLLBACK_FAILED` is a hard stop. The active root-only transaction must remain and no further apply may run.

## Crash boundary

Immediately before service-file replacement the durable journal becomes:

```text
phase = SWITCH_ARMED
production_mutation = false
production_mutation_possible = true
```

A kill/host failure in the atomic-switch window therefore cannot later be misreported as proof that no mutation occurred.

If `active-apply.json` exists after interruption, inspect only:

```bash
sudo python3 -m json.tool /var/lib/webai-bridge-deploy-control/production-apply/active-apply.json
```

Recovery can replace/restart production and is therefore a separate mutation Human Gate. Do not improvise recovery by deleting the marker.

## Non-claims

This apply gate does not certify live Stripe payment, browser-bound paid completion, iPhone Safari handoff, BYOK live inference, PACKAGE_TEXT Knowledge behavior, revoke→401, or PR #30 merge readiness. Those remain later reality gates after exact production apply passes.
