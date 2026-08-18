# /goal — WebAI Bridge exact-head deploy v1

Date: 2026-08-18
Mode: `CASH_NOW / BUILD_ACCELERATE`
Method: `Ultimate Loop / DA / Counter-DA / Human Gate`
Status: `IMPLEMENTED CANDIDATE / PRODUCTION APPLY NOT YET APPROVED`

## Goal

Deploy the immutable PR #30 head:

```text
commit 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
tree   38be7d9d9145cfcf9bc3aba47eccb4f453da4439
```

onto the controlled fixed-domain host without modifying that target commit, without mutating the currently running checkout before the cutover, and without silently inheriting older-revision production evidence.

The deploy mechanism is deliberately developed on a separate branch based on `main`. It is an external control plane that fetches and deploys this immutable target. It must not be added to PR #30 itself because doing so would change the very HEAD being certified.

## Protected outcome

```text
separate controller checkout
→ fetch exact commit
→ verify exact tree
→ detached release worktree
→ pinned CI-observed dependency constraints
→ source-purity gate
→ target revision renders its own deployment artifacts
→ generated no-access-log/service identity verified
→ transient systemd preflight as service user/sandbox
→ HUMAN GATE
→ atomic production unit switch
→ running PID/cwd/revision/cmdline proof
→ fixed-domain HTTPS health
→ Stripe external acceptance
→ evidence freeze
```

No live payment is created by this deployer. The final buyer payment/iPhone/revoke acceptance remains a separate gate.

## DA findings closed

### 1. Self-staleness

Bad approach:

```text
add deploy workflow to PR #30
→ PR #30 HEAD changes
→ exact-head target changes
→ previous evidence becomes stale
```

Resolution: deploy tooling lives outside PR #30 and pins an explicit immutable target SHA + tree.

### 2. Mutating the currently running checkout before cutover

Using `/opt/webai-bridge` as both production runtime and deployment controller would allow a pull/checkout to change files underneath the old live process before the service switch.

Resolution:

```text
controller: /opt/webai-bridge-control
releases:   /opt/webai-bridge-releases/{sha}
venvs:      /opt/webai-bridge-venvs/{sha}
state:      /var/lib/webai-bridge
```

The deployer rejects a controller path that overlaps the current production `WorkingDirectory`.

### 3. `git HEAD == DEPLOYED_REVISION` was not enough

A dirty or untracked Python file could alter runtime behavior while `git rev-parse HEAD` still reported the expected commit.

Resolution: before preflight and before/after cutover, tracked files must be clean and the release worktree may contain only one explicit generated source-tree object:

```text
runtime/.venv -> /opt/webai-bridge-venvs/{sha}
```

Any other untracked file or directory fails closed.

### 4. Dependency drift

`runtime/requirements.txt` uses version ranges. Reinstalling later could produce a different runtime under the same Git commit.

Resolution: `deploy/runtime-tests-228.constraints.txt` pins the dependency versions observed in the successful GitHub Actions runtime-tests #228 environment. Its SHA-256 is embedded in the deployer and verified before use. A new target/CI environment requires a new explicit dependency evidence snapshot rather than silently reusing this one.

The release venv is external to the source worktree and receives an immutable marker containing target SHA, constraints hash, Python version, and `pip freeze --all`. An existing venv without the marker or with freeze drift is rejected.

### 5. systemd drop-in override

A correct generated unit can still be weakened by an existing `webai-bridge.service.d/*.conf` drop-in.

Resolution: exact-head apply rejects non-empty systemd `DropInPaths` and requires `FragmentPath` to be the expected production unit file before and after the switch.

### 6. Preflight must run as service identity

Running the Python preflight as root is weaker evidence than the real service sandbox.

Resolution: prepare creates a transient oneshot systemd unit derived from the target-rendered service. It keeps the same user/group, environment file, locked environment, working directory, and sandbox controls, but replaces production Uvicorn startup with only the target `ExecStartPre` command.

### 7. Production switch must be explicit and rollback-capable

The default invocation only prepares the release. Production mutation requires the exact pinned SHA as approval text.

After switch, the deployer verifies:

- service active;
- MainPID exists;
- `/proc/{pid}/cwd` equals the exact release runtime;
- process environment contains the exact `DEPLOYED_REVISION`;
- process command contains `commercial_handoff:app` and `--no-access-log`;
- fixed-domain `/health` returns HTTPS 200;
- target `stripe_external_acceptance.py` passes from a service-identity transient unit.

Failure after the unit switch restores the previous production unit and restarts it. A failure evidence record is still frozen.

## Counter-DA retained boundaries

The mechanism intentionally does **not** claim the following:

- dependency wheel byte-for-byte identity across OS/CPU;
- product-state immutability under `/var/lib/webai-bridge/apps`;
- browser-bound payment acceptance without an actual browser/payment;
- iPhone Safari handoff acceptance;
- provider response acceptance;
- revoke → immediate 401 acceptance;
- generic rollback of external Stripe control-plane changes.

Those are separate evidence scopes. Product state is deliberately mutable Creator authority and is checked by the Hosted-v1 reality gate rather than folded into Git identity.

## Pinned prepare/preflight

On the separate controller clone:

```bash
sudo python3 deploy/exact_head_deploy.py prepare
```

This may fetch/install/stage files and execute a transient preflight, but it does not replace or restart the production service.

## Production Human Gate

Production cutover is a separate approval:

```bash
sudo python3 deploy/exact_head_deploy.py apply \
  --approve 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
```

Do not run this command from CI or automation without explicit deployment approval for that exact SHA.

## Evidence

A successful apply writes a secret-free evidence record under:

```text
/var/lib/webai-bridge/deploy-evidence/
```

including commit/tree identity, source-purity state, dependency freeze, constraints hash, production unit hashes, running process identity, HTTPS health, and Stripe external acceptance result.

## Human Gate sequence

1. Merge this deploy-tooling PR — separate decision.
2. Bootstrap/update `/opt/webai-bridge-control` without touching the live production checkout.
3. Run `prepare` for the pinned SHA/tree.
4. Review output.
5. Approve `apply` — separate production decision.
6. After deploy evidence PASS, run the existing live buyer/iPhone/payment/revoke reality chain.
7. Only then decide PR #30 merge.
