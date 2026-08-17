from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import entitlement_cli
from knowledge_artifact import canonical_knowledge_file, text_sha256, validate_package_text_artifact
from package_install_cli import (
    NONRUNNABLE_REPLACE_STATES,
    _load_existing_status,
    _load_package,
    _read_instructions,
    _regular_non_symlink,
    _reject_destination_symlink,
    _safe_config_dir,
    _stage_bytes,
    _stage_text,
    _validate_installable_package,
)
from package_knowledge import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_CONTEXT_CHARS,
    MAX_KNOWLEDGE_CHARS,
    PACKAGE_TEXT_BACKEND,
)


def _read_knowledge(path: Path) -> str:
    _regular_non_symlink(path, "Knowledge")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise SystemExit(f"Knowledge must be UTF-8 text: {exc}") from exc
    if not text.strip():
        raise SystemExit("Knowledge must not be empty")
    if "\x00" in text:
        raise SystemExit("Knowledge must not contain NUL bytes")
    if len(text) > MAX_KNOWLEDGE_CHARS:
        raise SystemExit(f"Knowledge exceeds {MAX_KNOWLEDGE_CHARS} characters")
    return text


def _validate_bundle_metadata(data: dict, *, knowledge_text: str) -> str:
    slug = str(data.get("slug") or "")
    knowledge = data.get("knowledge") or {}
    if not knowledge.get("enabled"):
        raise SystemExit("Three-artifact bundle requires Knowledge enabled")
    if knowledge.get("backend") != PACKAGE_TEXT_BACKEND:
        raise SystemExit(f"Three-artifact bundle requires knowledge.backend={PACKAGE_TEXT_BACKEND}")
    expected_file = canonical_knowledge_file(slug)
    if knowledge.get("file") != expected_file:
        raise SystemExit(f"knowledge.file must be canonical: {expected_file}")
    digest = str(knowledge.get("artifact_sha256") or "")
    if len(digest) != 64:
        raise SystemExit("Three-artifact bundle requires knowledge.artifact_sha256")
    if text_sha256(knowledge_text) != digest:
        raise SystemExit("Knowledge artifact SHA-256 does not match Package JSON")
    delivery = data.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise SystemExit("PACKAGE_TEXT bundle v1 requires Hosted Only runtime")

    for key, minimum, maximum, default in (
        ("max_context_chars", 256, 50_000, DEFAULT_MAX_CONTEXT_CHARS),
        ("max_chunks", 1, 12, DEFAULT_MAX_CHUNKS),
        ("chunk_chars", 200, 8000, DEFAULT_CHUNK_CHARS),
    ):
        try:
            value = int(knowledge.get(key, default))
        except (TypeError, ValueError):
            raise SystemExit(f"Knowledge {key} must be an integer") from None
        if value < minimum or value > maximum:
            raise SystemExit(f"Knowledge {key} must be between {minimum} and {maximum}")
    return slug


def _asset_snapshot(path: Path) -> tuple[bytes | None, int]:
    if not path.exists():
        return None, 0o600
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"Existing bundle asset is not a regular file: {path}")
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _restore_asset(*, config_dir: Path, slug: str, label: str, dest: Path, previous: bytes | None, mode: int) -> None:
    if previous is None:
        dest.unlink(missing_ok=True)
        return
    staged = _stage_bytes(config_dir, prefix=f".{slug}.{label}.restore.", content=previous, mode=mode)
    try:
        os.replace(staged, dest)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def install_bundle(
    *,
    package_source: Path,
    instructions_source: Path,
    knowledge_source: Path,
    config_dir: Path,
    replace_nonrunnable: bool = False,
) -> dict:
    """Install Package JSON + Instructions + Knowledge with Package JSON as authority commit.

    There is no multi-file POSIX transaction. The runtime-safe invariant is therefore:
    support assets are staged/replaced first and the discoverable Package JSON is replaced
    last. New installs cannot be discovered before both referenced assets exist. Replacing
    an existing runnable package is refused; draft/disabled replacement is rollback guarded.
    """

    config_dir = _safe_config_dir(config_dir)
    data = _load_package(package_source)
    slug = _validate_installable_package(data)
    instructions = _read_instructions(instructions_source)
    knowledge_text = _read_knowledge(knowledge_source)
    _validate_bundle_metadata(data, knowledge_text=knowledge_text)

    package_dest = config_dir / f"{slug}.json"
    instructions_dest = config_dir / f"{slug}.instructions.md"
    knowledge_dest = config_dir / f"{slug}.knowledge.md"
    for path, label in (
        (package_dest, "Package JSON"),
        (instructions_dest, "Instructions"),
        (knowledge_dest, "Knowledge"),
    ):
        _reject_destination_symlink(path, label)

    existing_status = _load_existing_status(package_dest)
    if existing_status is None and (instructions_dest.exists() or knowledge_dest.exists()):
        raise SystemExit("Refusing to overwrite orphan Instructions/Knowledge without a classifiable Package JSON")
    if existing_status is not None:
        if existing_status not in NONRUNNABLE_REPLACE_STATES:
            raise SystemExit(
                f"Refusing to overwrite existing {existing_status!r} package; active/dogfood authority requires a separate lifecycle operation"
            )
        if not replace_nonrunnable:
            raise SystemExit(
                f"Destination package already exists with status={existing_status}; pass --replace-nonrunnable only after deliberate review"
            )

    previous_instructions, instructions_mode = _asset_snapshot(instructions_dest)
    previous_knowledge, knowledge_mode = _asset_snapshot(knowledge_dest)

    package_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    staged_instructions = _stage_text(config_dir, prefix=f".{slug}.instructions.", content=instructions)
    staged_knowledge = _stage_text(config_dir, prefix=f".{slug}.knowledge.", content=knowledge_text)
    staged_package = _stage_text(config_dir, prefix=f".{slug}.package.", content=package_text)
    instructions_committed = False
    knowledge_committed = False
    package_committed = False

    try:
        os.replace(staged_instructions, instructions_dest)
        staged_instructions = None
        instructions_committed = True
        os.replace(staged_knowledge, knowledge_dest)
        staged_knowledge = None
        knowledge_committed = True
        # Authority commit last: AppRegistry discovers the new bundle only after
        # both referenced server-owned assets are present.
        os.replace(staged_package, package_dest)
        staged_package = None
        package_committed = True
        try:
            dir_fd = os.open(config_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        if not package_committed:
            rollback_errors: list[Exception] = []
            if knowledge_committed:
                try:
                    _restore_asset(
                        config_dir=config_dir, slug=slug, label="knowledge", dest=knowledge_dest,
                        previous=previous_knowledge, mode=knowledge_mode,
                    )
                except Exception as exc:
                    rollback_errors.append(exc)
            if instructions_committed:
                try:
                    _restore_asset(
                        config_dir=config_dir, slug=slug, label="instructions", dest=instructions_dest,
                        previous=previous_instructions, mode=instructions_mode,
                    )
                except Exception as exc:
                    rollback_errors.append(exc)
            if rollback_errors:
                raise RuntimeError("Bundle commit failed and support-asset rollback also failed; operator intervention required") from rollback_errors[0]
        raise
    finally:
        for staged in (staged_instructions, staged_knowledge, staged_package):
            if staged is not None:
                staged.unlink(missing_ok=True)

    verification_errors = validate_package_text_artifact(
        config_dir=config_dir,
        app_config=data,
        require_digest=True,
    )
    if verification_errors:
        raise RuntimeError("Installed Knowledge verification failed after authority commit: " + "; ".join(verification_errors))

    return {
        "installed": True,
        "slug": slug,
        "status": "draft",
        "authority_commit": "PACKAGE_JSON_LAST",
        "package_path": str(package_dest),
        "instructions_path": str(instructions_dest),
        "knowledge_path": str(knowledge_dest),
        "knowledge_sha256": data["knowledge"]["artifact_sha256"],
        "replaced_status": existing_status,
        "next": f"python package_bundle_cli.py activate --config {package_dest}",
    }


def activate_bundle(*, config_path: Path, checkout_reviewed: bool = False) -> dict:
    path, data = entitlement_cli.load_package_config(str(config_path))
    errors = validate_package_text_artifact(config_dir=path.parent, app_config=data, require_digest=True)
    if errors:
        raise SystemExit("Refusing activation: " + "; ".join(errors))

    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        rc = entitlement_cli.cmd_activate_config(SimpleNamespace(config=str(path), checkout_reviewed=checkout_reviewed))
    if rc != 0:
        raise SystemExit(f"Activation failed with exit code {rc}")
    try:
        activation = json.loads(capture.getvalue())
    except json.JSONDecodeError as exc:
        raise RuntimeError("Activation did not return valid JSON") from exc

    activated = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_package_text_artifact(config_dir=path.parent, app_config=activated, require_digest=True)
    if errors:
        raise RuntimeError("Knowledge verification failed after activation: " + "; ".join(errors))
    if activated.get("status") != "active" or (activated.get("access") or {}).get("commercial_enforcement") != "ENTITLEMENT_ENFORCED":
        raise RuntimeError("Activation did not establish active entitlement enforcement")

    return {
        "activated": True,
        "package_id": activated["slug"],
        "knowledge_verified": True,
        "knowledge_sha256": activated["knowledge"]["artifact_sha256"],
        "runtime": (activated.get("readiness") or {}).get("runtime"),
        "commercial": (activated.get("readiness") or {}).get("commercial"),
        "checkout_binding_verification": activation.get("checkout_binding_verification"),
        "next": "Start/restart commercial_handoff:app. Stripe checkout can then fulfill buyer entitlement; keep paid inference BYOK-only in v1.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install and activate a three-artifact WebAI Bridge Knowledge package")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Atomic authority install: Package JSON + Instructions + Knowledge")
    install.add_argument("--package", required=True)
    install.add_argument("--instructions", required=True)
    install.add_argument("--knowledge", required=True)
    install.add_argument("--config-dir", required=True)
    install.add_argument("--replace-nonrunnable", action="store_true")

    activate = sub.add_parser("activate", help="Verify Knowledge integrity, then activate paid Hosted entitlement enforcement")
    activate.add_argument("--config", required=True)
    activate.add_argument("--checkout-reviewed", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "install":
            result = install_bundle(
                package_source=Path(args.package),
                instructions_source=Path(args.instructions),
                knowledge_source=Path(args.knowledge),
                config_dir=Path(args.config_dir),
                replace_nonrunnable=args.replace_nonrunnable,
            )
        else:
            result = activate_bundle(config_path=Path(args.config), checkout_reviewed=args.checkout_reviewed)
    except (SystemExit, RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_in_output": False}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": "PASS", **result, "secrets_in_output": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
