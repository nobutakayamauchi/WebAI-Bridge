# AP-WEBIAI-EXACT-HEAD-FINAL-03

Status: `HUMAN GATE / DEPLOY-TOOLING MERGE NOT YET APPROVED / PRODUCTION APPLY NOT APPROVED`
Priority: `P0 / FAST`
Target: `WebAI-Bridge`

## Pinned target

```text
commit: 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
tree:   38be7d9d9145cfcf9bc3aba47eccb4f453da4439
domain: webai.140-238-62-74.sslip.io
CI:     runtime-tests #228 SUCCESS on the same tree
```

## Approved reversible preparation scope after deploy-tooling merge

- maintain a separate root-owned `/opt/webai-bridge-control` clone;
- require its full worktree to be clean;
- require controller branch `main` and exact synchronization with `origin/main`;
- execute the deploy capsule from the committed Git object under Python isolated mode rather than trusting a working-tree script;
- inspect the actual systemd `WorkingDirectory` and reject controller/live overlap;
- fetch the pinned target commit;
- create the detached release worktree;
- build the pinned Python 3.12 dependency environment;
- verify source purity and Python/dependency marker identity;
- regenerate deployment artifacts from the target commit itself;
- run the target handoff preflight through a transient systemd oneshot with the service identity/sandbox;
- freeze a unique read-only, secret-free prepare evidence record;
- inspect results.

## Not approved by this packet

- merging the deploy-tooling PR;
- replacing `/etc/systemd/system/webai-bridge.service`;
- restarting the production service;
- creating a live Stripe payment;
- changing price/product configuration;
- merging PR #30.

## Canonical prepare invocation — only after deploy-tooling merge

The controller clone is expected to be root-owned so root Git identity checks remain fail-closed without global `safe.directory` exceptions.

```bash
sudo sh -c 'git -C /opt/webai-bridge-control show HEAD:deploy/exact_head_deploy.py | python3 -I - prepare'
```

The capsule itself additionally requires the controller worktree to be clean and `main == origin/main` before it fetches/stages the immutable PR #30 target.

## Production apply command — requires separate approval

```bash
sudo sh -c 'git -C /opt/webai-bridge-control show HEAD:deploy/exact_head_deploy.py | python3 -I - apply --approve 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98'
```

Successful apply must produce secret-free evidence proving running PID/cwd/revision, no-access-log command surface, fixed-domain HTTPS health, and Stripe external acceptance.

Failure after the unit switch is not allowed to claim rollback merely because a copy/restart was attempted. It must atomically restore the previous unit, verify its exact unit hash, restart it successfully, and verify that the restored process returns to the pre-switch cwd and `DEPLOYED_REVISION`. If any rollback verification fails, the evidence status must be `ROLLBACK_FAILED` and the deploy stops as failed.
