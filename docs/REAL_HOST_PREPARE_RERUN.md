# Real-host prepare rerun

After this branch is reviewed and merged, update `/opt/webai-bridge-control` to canonical `main` and rerun prepare through the committed host-safe entrypoint:

```bash
sudo sh -c 'git -C /opt/webai-bridge-control show HEAD:deploy/exact_head_deploy_hostsafe.py | python3 -I - prepare'
```

Stop after `PREPARED_CANDIDATE_PASS`; do not run production `apply` without the separate Human Gate.
