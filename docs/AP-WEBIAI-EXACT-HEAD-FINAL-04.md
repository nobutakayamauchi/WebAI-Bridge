# AP-WEBIAI-EXACT-HEAD-FINAL-04

Real-host prepare reached the service-identity preflight and correctly failed closed on Git dubious-ownership protection because the exact release is root-owned while preflight runs as `webai`.

The accepted repair keeps source root-owned and adds no host-global Git exception; instead the host-safe controller entrypoint scopes `safe.directory` only to the exact release and only to the generated service `ExecStartPre` command, while recording the raw target-rendered service hash separately from the overlaid candidate service hash.

Production apply, live payment/browser/BYOK/Knowledge/revoke acceptance, and PR #30 merge remain separate gates.
