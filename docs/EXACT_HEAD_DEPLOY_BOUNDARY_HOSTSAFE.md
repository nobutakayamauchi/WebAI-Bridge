# Exact-head deploy boundary — host-safe Git trust

The exact target source remains immutable and root-owned.

The runtime identity `webai` receives Git trust only for the exact release path and only for the preflight command that compares `DEPLOYED_REVISION` with local Git HEAD. The long-running application process receives no Git trust environment, no global `safe.directory` entry is created, and source ownership is not transferred to the runtime user.

The host-safe entrypoint must itself be executed from the committed controller Git object so dirty working-tree code is never trusted before the canonical controller cleanliness gate.
