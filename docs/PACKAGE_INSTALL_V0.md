# Package Install v0 — Operator Lifecycle

Date: 2026-08-16
Status: `BOUNDED_OPERATOR_PATH / NOT_DEPLOYED`

## Purpose

Creator Studio exports two files. Package Install v0 removes ad-hoc copying into the live runtime app directory while preserving one critical separation:

```text
INSTALL != ACTIVATE
```

Installing a package never makes it runnable.

## Required flow

```text
Creator Studio export
↓
package_install_cli.py
↓
status=draft in canonical runtime/apps paths
↓
deployment_preflight.py
↓
checkout review when required
↓
entitlement_cli.py activate-config
↓
service restart/reload
↓
deployment_preflight.py
↓
manual buyer payment verification
↓
entitlement_cli.py issue
```

## Install

```bash
cd runtime
python package_install_cli.py \
  --package /path/to/my-ai.json \
  --instructions /path/to/my-ai.instructions.md
```

The destination is derived from the package slug:

```text
runtime/apps/{slug}.json
runtime/apps/{slug}.instructions.md
```

The operator cannot choose arbitrary destination filenames through the package contract.

## Installer gates

The installer refuses:

- non-draft package exports;
- `id != slug`;
- non-canonical `instructions_file`;
- draft packages that already claim `runtime=READY`;
- draft packages that already claim `ENTITLEMENT_ENFORCED`;
- schema-invalid packages;
- secret-like material embedded in Package JSON;
- symlinked source files;
- symlinked destination files;
- empty Instructions;
- Instructions containing NUL bytes;
- Instructions over the Studio v0 maximum size;
- world-writable target app directories;
- orphan destination Instructions whose authority cannot be classified;
- existing active/dogfood/unknown packages.

Installed files are written owner-only.

## Replacing an unactivated draft

Existing draft/disabled packages are not replaced by default.

After deliberate review:

```bash
python package_install_cli.py \
  --package /path/to/revised.json \
  --instructions /path/to/revised.instructions.md \
  --replace-nonrunnable
```

`--replace-nonrunnable` never authorizes replacement of `active`, `dogfood`, or unknown package states.

## Commit ordering / failure behavior

The installer stages and fsyncs both files first.

Then:

```text
1. Instructions atomic replace
2. Package JSON atomic replace  ← authority/discovery file comes last
```

If the Package JSON commit fails after Instructions were replaced:

- a new install removes the newly created orphan Instructions;
- replacement of a draft/disabled package restores the previous Instructions;
- the existing Package JSON remains unchanged.

This does not pretend to be a general distributed transaction. It is a bounded filesystem handoff designed so installation failure does not silently activate or destroy a runnable package.

## Activation remains separate

For the first paid hosted path:

```bash
python entitlement_cli.py activate-config \
  --config apps/my-ai.json
```

For `ASSISTED_SETUP`, activation requires the additional explicit operator checkout review after verifying product, amount, currency, and charge basis:

```bash
python entitlement_cli.py activate-config \
  --config apps/my-ai.json \
  --checkout-reviewed
```

Activation is still not a payment event. Buyer access is issued only after manual payment verification.

## Runtime refresh

The current runtime registry is loaded in-process. Installing or activating files does not prove that an already-running process has loaded the new state.

For the initial deployment workflow, perform an explicit service restart after the intended package state is installed/activated, then run/observe the deployment preflight and runtime behavior again.

```text
FILES CHANGED != RUNNING PROCESS CHANGED
```

## Evidence boundary

This lifecycle is covered by local/CI attack tests. It does not establish:

- real host filesystem ownership;
- deployed service user permissions;
- deployed revision identity;
- reverse-proxy/TLS behavior;
- live provider behavior;
- live Stripe behavior;
- iPhone/Safari behavior.

Those remain deployment evidence gates.
