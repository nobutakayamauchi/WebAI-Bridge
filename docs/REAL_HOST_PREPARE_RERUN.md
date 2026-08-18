# Real-host prepare rerun

After this branch is reviewed and merged, update `/opt/webai-bridge-control` to canonical `main` and rerun prepare through one pinned controller revision.

The shell captures controller `HEAD` once, exports that exact revision to the host-safe wrapper, and reads the wrapper from the same Git object. The wrapper then refuses to load a base deploy capsule from any other controller revision.

```bash
sudo bash -c 'set -euo pipefail; r=$(git -C /opt/webai-bridge-control rev-parse HEAD); export WEB_AI_CONTROLLER_REVISION="$r"; git -C /opt/webai-bridge-control show "$r:deploy/exact_head_deploy_hostsafe.py" | python3 -I - prepare'
```

A successful rerun must report `PREPARED_CANDIDATE_PASS`, the pinned controller revision, raw target-rendered service hash, candidate overlay service hash, scoped Git trust, sanitized Git/Python environment, and root-owned non-writable runtime identity.

Stop after `PREPARED_CANDIDATE_PASS`; do not run production `apply` without the separate Human Gate.
