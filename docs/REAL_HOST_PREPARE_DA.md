# Real-host prepare DA

DA rejected two tempting workarounds:

- changing exact release ownership to `webai`, because that would let the runtime identity modify source;
- adding a host-global Git `safe.directory`, because that creates hidden persistent host trust outside the deploy evidence boundary.

The selected repair is a deterministic control-plane overlay limited to `ExecStartPre` for the exact root-owned release path.
