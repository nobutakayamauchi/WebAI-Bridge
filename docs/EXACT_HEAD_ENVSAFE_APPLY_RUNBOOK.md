# Exact-head env-safe transactional apply runbook

Canonical procedure for the current frozen production rollout. This document does **not** authorize a merge, production mutation, live payment, recovery mutation, iPhone/BYOK/Knowledge acceptance, or PR #30 merge.

## Frozen rollout

```text
TARGET_SHA  = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
TARGET_TREE = 155dc692264a8f7edcd74b0eaff8cba28b0f11ef
EXPECTED_PREVIOUS_SHA = 9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
```

Only the reviewed previous revision may be used as the rollback baseline. An unknown current revision is rejected before mutation. An already-active target is not restarted redundantly.

## Shared-state rollback compatibility

The stores that normal buyer/webhook traffic can mutate during rollout must be exact Git-blob matches in the reviewed previous revision and target:

```text
runtime/entitlements.py    dec40737f60cee22170e0996e856de98cb369a93
runtime/checkout_state.py  e40312626d77f5322108ce97d6d6878385e3f46b
runtime/handoff_tickets.py 9c71b08605ab1ab02a309cba52fea249313f8114
```

The apply-ready controller re-fetches the supported previous SHA and re-verifies both sides before mutation. Creator Studio writes are not part of rollout acceptance and must not be performed concurrently with the switch.

## Canonical entry

```text
deploy/exact_head_deploy_envsafe_apply_ready.py
```

Authority chain:

```text
root-owned/no-symlink controller + .git BEFORE first Git
→ reject Git include/url-rewrite/http-override/object-alternate authority
→ empty inherited environment
→ exact synchronized controller revision
→ env-safe exact-head prepare + transient candidate preflight
→ supported previous revision + shared-state compatibility
→ stable previous InvocationID + MainPID + cwd + revision + unit hash
→ pre-mutation generation rebound
→ exclusive root-only flock
→ root-only rollback backup
→ durable PREPARED_FOR_SWITCH journal
→ durable SWITCH_ARMED before service-file mutation
→ candidate/controller/source/unit recheck
→ atomic unit replacement + restart
→ stable target InvocationID + MainPID
→ bounded strict HTTPS health
→ bounded Stripe external acceptance (no payment)
→ same-generation post-Stripe health
→ root-only evidence
→ committed transaction archive
```

Authority identifiers:

```text
bootstrap_controller_trust_authority = ROOT_OWNED_GIT_NO_EXTERNAL_AUTHORITY_V2
apply_authority = ROOT_ONLY_TRANSACTIONAL_APPLY_V2
backup_authority = SEPARATE_ROOT_ONLY_SERVICE_BACKUP_V2
transaction_authority = DURABLE_SWITCH_ARMED_FAIL_CLOSED_V2
previous_generation_authority = STABLE_INVOCATION_ID_MAINPID_SNAPSHOT_V1
pre_mutation_generation_authority = PRE_MUTATION_GENERATION_REBOUND_V2
rollback_state_compatibility_authority = EXACT_SHARED_STATE_SCHEMA_BLOB_EQUIVALENCE_V1
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

Any existing `active-apply.json` is a hard stop. Never delete it merely to force another deploy.

## Clean controller bootstrap

Every invocation, not only the first synchronization, must use an empty environment. The Python outer wrapper independently proves controller/.git root trust and rejects external Git authority before its first Git command.

Controller synchronization remains reversible:

```bash
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 /bin/sh -ceu 'C=/opt/webai-bridge-control; test -d "$C/.git"; test "$(/usr/bin/stat -c %u "$C")" = 0; test "$(/usr/bin/stat -c %u "$C/.git")" = 0; test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"; test "$(/usr/bin/git -C "$C" config --local --get remote.origin.url)" = "https://github.com/nobutakayamauchi/WebAI-Bridge.git"; test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"; test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main; /usr/bin/git -C "$C" fetch --no-tags origin main; /usr/bin/git -C "$C" merge --ff-only origin/main; test "$(/usr/bin/git -C "$C" rev-parse HEAD)" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"'
```

## Apply-ready prepare — reversible gate

Run after this controller is merged and Oracle main is synchronized, but before production approval. It does not replace or restart production:

```bash
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 /bin/sh -ceu 'C=/opt/webai-bridge-control; test -d "$C/.git"; test "$(/usr/bin/stat -c %u "$C")" = 0; test "$(/usr/bin/stat -c %u "$C/.git")" = 0; test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"; test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"; /usr/bin/git -C "$C" fetch --no-tags origin main; test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main; R=$(/usr/bin/git -C "$C" rev-parse HEAD); test "$R" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"; /usr/bin/git -C "$C" show "$R:deploy/exact_head_deploy_envsafe_apply_ready.py" | /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 WEB_AI_BOOTSTRAP_CLEAN=1 WEB_AI_CONTROLLER_REVISION="$R" /usr/bin/python3 -I - prepare'
```

Required prepare result:

```text
status = PREPARED_CANDIDATE_PASS
production_mutation = false
production_apply_enabled = true
previous_production_supported = true
target_already_active = false
expected_previous_revision = 9a1c5a4cd01a16aa7bfa02eede89800aa6d494b1
bootstrap_controller_trust_authority = ROOT_OWNED_GIT_NO_EXTERNAL_AUTHORITY_V2
rollback_state_compatibility_authority = EXACT_SHARED_STATE_SCHEMA_BLOB_EQUIVALENCE_V1
previous_production_snapshot = {...}
```

If `previous_production_supported=false`, stop. If `target_already_active=true`, verify the target instead of reapplying.

## Production apply — HUMAN GATE

**STOP until explicit production apply approval.** This command mutates/restarts production. It performs a fresh prepare/preflight again and re-observes/rebinds the previous generation before the first mutation; it does not inherit the earlier prepare PASS.

```bash
sudo /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 GIT_CONFIG_SYSTEM=/dev/null GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 /bin/sh -ceu 'C=/opt/webai-bridge-control; test -d "$C/.git"; test "$(/usr/bin/stat -c %u "$C")" = 0; test "$(/usr/bin/stat -c %u "$C/.git")" = 0; test -z "$(/usr/bin/find "$C/.git" \( ! -user root -o -perm /022 -o -type l \) -print -quit)"; test -z "$(/usr/bin/git -C "$C" status --porcelain --untracked-files=all)"; /usr/bin/git -C "$C" fetch --no-tags origin main; test "$(/usr/bin/git -C "$C" rev-parse --abbrev-ref HEAD)" = main; R=$(/usr/bin/git -C "$C" rev-parse HEAD); test "$R" = "$(/usr/bin/git -C "$C" rev-parse origin/main)"; /usr/bin/git -C "$C" show "$R:deploy/exact_head_deploy_envsafe_apply_ready.py" | /usr/bin/env -i PATH=/usr/bin:/bin HOME=/root LANG=C.UTF-8 LC_ALL=C.UTF-8 WEB_AI_BOOTSTRAP_CLEAN=1 WEB_AI_CONTROLLER_REVISION="$R" /usr/bin/python3 -I - apply --approve 5fd4c791e636464f1a3b5195a3e1048b505d6de5'
```

Success requires:

```text
status = DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS
production_mutation = true
running_identity.revision = 5fd4c791e636464f1a3b5195a3e1048b505d6de5
stripe_external_acceptance = PASS
live_payment_performed = false
pre_mutation_generation_revalidated = true
```

## Failure / crash behavior

Expected failure states are `PRE_SWITCH_FAILURE`, `ROLLBACK_VERIFIED_AFTER_FAILURE`, and `ROLLBACK_FAILED`. A rollback PASS means the exact previous unit, revision/cwd generation, and HTTPS health were verified after restore. `ROLLBACK_FAILED` leaves the active transaction and blocks another apply.

Immediately before service-file replacement the durable transaction becomes:

```text
phase = SWITCH_ARMED
production_mutation = false
production_mutation_possible = true
```

Thus a kill/host failure in the atomic-switch window cannot later be reported as proof of no mutation. Recovery can itself replace/restart production and is a separate Human Gate.

Read-only interrupted-transaction inspection:

```bash
sudo python3 -m json.tool /var/lib/webai-bridge-deploy-control/production-apply/active-apply.json
```

## Non-claims

This gate does not certify live Stripe payment, browser-bound paid completion, iPhone Safari body handoff, BYOK live inference, PACKAGE_TEXT Knowledge behavior, revoke→401, or PR #30 merge readiness. Those remain later reality gates.
