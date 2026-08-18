# Real-host prepare DA

DA rejected two tempting workarounds:

- changing exact release ownership to `webai`, because that would let the runtime identity modify source;
- adding a host-global Git `safe.directory`, because that creates hidden persistent host trust outside the deploy evidence boundary.

The first repair scoped `safe.directory` to `ExecStartPre`, but a second DA / Counter-DA pass found additional proof gaps:

1. a single arbitrary `ExecStartPre` could have received the Git trust overlay without proving it was the exact target `deployment_preflight_handoff.py` command;
2. the wrapper and base deploy capsule both referenced mutable `HEAD`, leaving a controller-revision TOCTOU window;
3. inherited `GIT_DIR`, `GIT_WORK_TREE`, Git config variables, or `PATH` could redirect the local revision check even though `safe.directory` itself was scoped correctly;
4. clean Git content alone did not prove that the runtime identity lacked write authority over the release, venv, or controller Git metadata.

The hardened repair therefore:

- requires the exact pinned release path and exact expected preflight command before adding trust;
- captures one explicit controller revision and loads both wrapper/base from that revision only;
- sanitizes Git repository/config redirect variables, fixes `PATH=/usr/bin:/bin`, and clears Python path/home injection for the preflight process only;
- keeps the long-running `ExecStart` unchanged;
- requires release source, exact venv, and controller Git metadata to remain root-owned and non-group/world-writable;
- records separate raw target-rendered and candidate overlay service hashes, with an explicit `ONLY_EXECSTARTPRE` overlay delta.

Production apply remains a separate Human Gate.
