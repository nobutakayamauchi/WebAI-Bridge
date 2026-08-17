# Creator Studio Knowledge Bundle v1

## Goal

Turn the paid Hosted path from a generic paid chat into a sellable dedicated AI whose product content is:

1. Package JSON
2. Creator Instructions
3. Creator Knowledge

The three artifacts are authored from one Creator Studio validation result. Knowledge remains server-owned in Hosted mode and is not handed to the buyer as package source.

## Supported v1 shape

- `delivery.mode = HOSTED_ONLY`
- `knowledge.backend = PACKAGE_TEXT`
- access: `BUY_ONCE` or `SUBSCRIPTION`
- paid inference: buyer `BYOK` only
- Stripe Payment Link + the existing commercial handoff runtime

Portable Knowledge, portable runtime, and creator/platform-funded paid inference are not part of this v1.

## Creator flow

Open `/studio` on the `commercial_handoff:app` route surface with Creator Studio explicitly enabled.

The Knowledge-aware Studio accepts:

- AI name / slug / description
- Instructions
- Knowledge text
- retrieval limits (`max_context_chars`, `max_chunks`, `chunk_chars`)
- BUY_ONCE or SUBSCRIPTION access price
- Stripe Payment Link binding acknowledgement
- model and ordinary usage limits

A successful validation exports:

- `<slug>.json`
- `<slug>.instructions.md`
- `<slug>.knowledge.md`

The Package JSON records the canonical Knowledge path and SHA-256 of the exact exported Knowledge text.

## Operator install

Use `runtime/package_bundle_cli.py install` with all three exported artifacts and the target deployed `apps` authority directory.

The installer does not claim a filesystem-wide three-file POSIX transaction. Instead it provides a runtime authority transaction:

1. validate all three sources before mutation;
2. stage owner-only files in the target authority directory;
3. replace Instructions;
4. replace Knowledge;
5. replace Package JSON **last**;
6. fsync the directory best-effort;
7. verify the installed Knowledge against the Package JSON SHA-256.

Because AppRegistry discovers Package JSON as authority, a new package cannot become discoverable before both referenced support assets exist. Replacement of active/dogfood packages is refused. Draft/disabled replacement rolls support assets back if the Package JSON authority commit fails.

## Activation

Use `runtime/package_bundle_cli.py activate --config <deployed-package-json>`.

Activation first verifies:

- canonical PACKAGE_TEXT file binding;
- owner-only Knowledge file;
- Knowledge UTF-8 / size constraints;
- Package JSON Knowledge SHA-256 against the installed artifact.

Only then does it invoke the existing paid Hosted activation, which changes the package to `active`, enables `ENTITLEMENT_ENFORCED`, and moves runtime readiness to `READY`.

The same Knowledge integrity check is repeated after activation.

## Runtime fail-closed rule

`commercial_handoff:app` validates activated PACKAGE_TEXT artifacts at startup. A missing, unsafe, or digest-mismatched Knowledge artifact blocks startup rather than serving an activated paid AI with a broken Knowledge contract.

Legacy dogfood PACKAGE_TEXT bindings created before digest metadata remain loadable, but new three-artifact bundles require the SHA-256 metadata.

## Sale boundary

A draft validation is not a sale-ready proof by itself.

The remaining runtime conditions are still required:

- explicit package activation;
- live Stripe configuration;
- working webhook / checkout verification;
- browser handoff / entitlement fulfillment;
- HTTPS;
- buyer BYOK connection for inference.

Those paid checkout and browser-handoff components already exist on `commercial_handoff:app`; this v1 connects Creator-authored Instructions + Knowledge to that commercial route without weakening the existing entitlement boundary.
