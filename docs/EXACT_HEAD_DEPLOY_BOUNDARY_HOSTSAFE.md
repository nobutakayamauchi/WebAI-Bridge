# Exact-head deploy boundary — host-safe Git trust

The exact target source remains immutable and root-owned.

The runtime identity `webai` receives Git trust only for the exact release path and only for the exact expected `deployment_preflight_handoff.py` command that compares `DEPLOYED_REVISION` with local Git HEAD. Before that command runs, Git repository/config redirect variables are removed, `PATH` is fixed to trusted system binaries, inherited Python path/home injection is cleared, and system/global Git config is disabled.

Because dynamic-loader variables act before `/usr/bin/env` can sanitize a process, the candidate service also locks `LD_PRELOAD`, `LD_AUDIT`, `LD_LIBRARY_PATH`, `PYTHONPATH`, and `PYTHONHOME` after the operator EnvironmentFile and sets `PYTHONNOUSERSITE=1`. These locks apply to the service identity, while the `safe.directory` Git trust remains restricted to `ExecStartPre`. The long-running `ExecStart` command itself remains unchanged and receives no Git trust configuration.

No global `safe.directory` entry is created, source ownership is not transferred to the runtime user, and release/venv/controller Git metadata must remain root-owned and non-group/world-writable. The exact release source rejects symlinks except the separately verified generated `runtime/.venv` link.

The host-safe entrypoint must itself be executed from one explicitly pinned controller Git revision. The shell reads the wrapper from that revision, the wrapper loads the base deploy capsule from the same revision, and controller revision movement during prepare fails closed.

Evidence distinguishes the raw target-rendered service hash from the candidate overlay service hash and declares the only permitted overlay classes as the exact `ExecStartPre` Git-trust wrapper plus the fixed runtime environment locks above.
