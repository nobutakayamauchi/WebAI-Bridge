# AP-WEBIAI-EXACT-HEAD-FINAL-03

Status: `HUMAN GATE / PRODUCTION APPLY NOT APPROVED`
Priority: `P0 / FAST`
Target: `WebAI-Bridge`

## Pinned target

```text
commit: 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
tree:   38be7d9d9145cfcf9bc3aba47eccb4f453da4439
domain: webai.140-238-62-74.sslip.io
CI:     runtime-tests #228 SUCCESS on the same tree
```

## Approved reversible preparation scope

- maintain a separate `/opt/webai-bridge-control` clone;
- fetch the pinned target commit;
- create the detached release worktree;
- build the pinned Python 3.12 dependency environment;
- verify source purity;
- regenerate deployment artifacts from the target commit itself;
- run the target handoff preflight through a transient systemd oneshot with the service identity/sandbox;
- inspect results.

## Not approved by this packet

- replacing `/etc/systemd/system/webai-bridge.service`;
- restarting the production service;
- creating a live Stripe payment;
- changing price/product configuration;
- merging PR #30;
- merging the deploy-tooling PR.

## Production apply command — requires separate approval

```bash
sudo python3 deploy/exact_head_deploy.py apply \
  --approve 0dffd30f362b5cf2d144fc9e5e47b6d11bbf7f98
```

Successful apply must produce secret-free evidence proving running PID/cwd/revision, no-access-log command surface, fixed-domain HTTPS health, and Stripe external acceptance. Failure after switch must restore the previous service unit and restart it.
