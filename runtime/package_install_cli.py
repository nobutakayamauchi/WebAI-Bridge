from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path

from deployment_preflight import _secret_key_paths
from studio import validate_package_document

BASE_DIR = Path(__file__).resolve().parent
PACKAGE_SCHEMA_FILE = BASE_DIR.parent / "package-schema" / "package.schema.json"
DEFAULT_CONFIG_DIR = Path(os.getenv("WEB_AI_CONFIG_DIR", BASE_DIR / "apps"))
MAX_INSTRUCTIONS_CHARS = 100_000
NONRUNNABLE_REPLACE_STATES = {"draft", "disabled"}


def _regular_non_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise SystemExit(f"{label} must not be a symlink")
    if not path.exists() or not path.is_file():
        raise SystemExit(f"{label} must be an existing regular file: {path}")


def _safe_config_dir(path: Path) -> Path:
    if path.is_symlink():
        raise SystemExit("Config directory must not be a symlink")
    if not path.exists() or not path.is_dir():
        raise SystemExit(f"Config directory does not exist: {path}")
    resolved = path.resolve()
    if not os.access(resolved, os.W_OK):
        raise SystemExit(f"Config directory is not writable: {resolved}")
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & 0o002:
        raise SystemExit("Config directory must not be world-writable")
    return resolved


def _load_package(path: Path) -> dict:
    _regular_non_symlink(path, "Package JSON")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Package JSON is invalid: {exc}") from exc
    errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Package schema invalid: " + "; ".join(errors))
    return data


def _validate_installable_package(data: dict) -> str:
    slug = str(data.get("slug") or "")
    if not slug:
        raise SystemExit("Package slug is missing")
    if data.get("id") != slug:
        raise SystemExit("Package id must equal slug for operator install v0")
    if data.get("status") != "draft":
        raise SystemExit("Only draft Studio exports may be installed; install must never activate a package")

    readiness = data.get("readiness") or {}
    if readiness.get("configuration") != "VALIDATED":
        raise SystemExit("Draft package must retain readiness.configuration=VALIDATED")
    if readiness.get("runtime") == "READY":
        raise SystemExit("Draft package must not claim readiness.runtime=READY before explicit activation")

    access = data.get("access") or {}
    if access.get("commercial_enforcement") == "ENTITLEMENT_ENFORCED":
        raise SystemExit("Draft package must not claim ENTITLEMENT_ENFORCED before explicit activation")

    expected = f"apps/{slug}.instructions.md"
    if data.get("instructions_file") != expected:
        raise SystemExit(f"instructions_file must be canonical: {expected}")
    secret_paths = _secret_key_paths(data)
    if secret_paths:
        raise SystemExit("Package JSON contains secret-like material: " + ", ".join(secret_paths))
    return slug


def _read_instructions(path: Path) -> str:
    _regular_non_symlink(path, "Instructions")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise SystemExit(f"Instructions must be UTF-8 text: {exc}") from exc
    if not text.strip():
        raise SystemExit("Instructions must not be empty")
    if "\x00" in text:
        raise SystemExit("Instructions must not contain NUL bytes")
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise SystemExit(f"Instructions exceed {MAX_INSTRUCTIONS_CHARS} characters")
    return text


def _load_existing_status(package_path: Path) -> str | None:
    if not package_path.exists():
        return None
    if package_path.is_symlink() or not package_path.is_file():
        raise SystemExit("Existing destination Package JSON is not a regular file")
    try:
        existing = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Existing destination Package JSON cannot be safely classified: {exc}") from exc
    return str(existing.get("status") or "unknown")


def _reject_destination_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise SystemExit(f"{label} destination must not be a symlink")


def _stage_bytes(config_dir: Path, *, prefix: str, content: bytes, mode: int = 0o600) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=config_dir)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, mode)
        return staged
    except Exception:
        try:
            staged.unlink(missing_ok=True)
        finally:
            raise


def _stage_text(config_dir: Path, *, prefix: str, content: str, mode: int = 0o600) -> Path:
    return _stage_bytes(config_dir, prefix=prefix, content=content.encode("utf-8"), mode=mode)


def _restore_instructions(
    *,
    config_dir: Path,
    slug: str,
    instructions_dest: Path,
    previous_content: bytes | None,
    previous_mode: int,
) -> None:
    if previous_content is None:
        instructions_dest.unlink(missing_ok=True)
        return
    staged_restore = _stage_bytes(
        config_dir,
        prefix=f".{slug}.restore.",
        content=previous_content,
        mode=previous_mode,
    )
    try:
        os.replace(staged_restore, instructions_dest)
        staged_restore = None
    finally:
        if staged_restore is not None:
            staged_restore.unlink(missing_ok=True)


def install_package(
    *,
    package_source: Path,
    instructions_source: Path,
    config_dir: Path,
    replace_nonrunnable: bool = False,
) -> dict:
    config_dir = _safe_config_dir(config_dir)
    data = _load_package(package_source)
    slug = _validate_installable_package(data)
    instructions = _read_instructions(instructions_source)

    package_dest = config_dir / f"{slug}.json"
    instructions_dest = config_dir / f"{slug}.instructions.md"
    _reject_destination_symlink(package_dest, "Package JSON")
    _reject_destination_symlink(instructions_dest, "Instructions")

    existing_status = _load_existing_status(package_dest)
    orphan_instructions = instructions_dest.exists() and existing_status is None
    if orphan_instructions:
        raise SystemExit(
            "Refusing to overwrite orphan Instructions without a classifiable destination Package JSON"
        )

    if existing_status is not None:
        if existing_status not in NONRUNNABLE_REPLACE_STATES:
            raise SystemExit(
                f"Refusing to overwrite existing {existing_status!r} package; active/dogfood/unknown authority requires a separate lifecycle operation"
            )
        if not replace_nonrunnable:
            raise SystemExit(
                f"Destination package already exists with status={existing_status}; pass --replace-nonrunnable only after deliberate review"
            )

    previous_instructions: bytes | None = None
    previous_instructions_mode = 0o600
    if instructions_dest.exists():
        if not instructions_dest.is_file():
            raise SystemExit("Existing destination Instructions is not a regular file")
        previous_instructions = instructions_dest.read_bytes()
        previous_instructions_mode = instructions_dest.stat().st_mode & 0o777

    package_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    staged_instructions = _stage_text(
        config_dir,
        prefix=f".{slug}.instructions.",
        content=instructions,
    )
    staged_package = _stage_text(
        config_dir,
        prefix=f".{slug}.package.",
        content=package_text,
    )
    instructions_committed = False
    package_committed = False

    try:
        # Authority ordering is intentional: Instructions become available first.
        # Package JSON is replaced last, so runtime discovery never sees a newly
        # installed config before its referenced Instructions file exists.
        os.replace(staged_instructions, instructions_dest)
        staged_instructions = None
        instructions_committed = True
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
            # Directory fsync is best effort across filesystems/platforms. File
            # contents themselves were already fsynced before atomic replacement.
            pass
    except Exception:
        if instructions_committed and not package_committed:
            try:
                _restore_instructions(
                    config_dir=config_dir,
                    slug=slug,
                    instructions_dest=instructions_dest,
                    previous_content=previous_instructions,
                    previous_mode=previous_instructions_mode,
                )
            except Exception as restore_exc:
                raise RuntimeError(
                    "Package commit failed and Instructions rollback also failed; operator intervention required"
                ) from restore_exc
        raise
    finally:
        if staged_instructions is not None:
            staged_instructions.unlink(missing_ok=True)
        if staged_package is not None:
            staged_package.unlink(missing_ok=True)

    return {
        "installed": True,
        "slug": slug,
        "status": "draft",
        "package_path": str(package_dest),
        "instructions_path": str(instructions_dest),
        "replaced_status": existing_status,
        "next": f"Review deployment preflight, then explicitly activate with entitlement_cli.py activate-config --config {package_dest}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install a Studio-exported WebAI Package without activating it")
    parser.add_argument("--package", required=True, help="Source Package JSON exported by Creator Studio")
    parser.add_argument("--instructions", required=True, help="Source Instructions markdown/text file")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR), help="Deployed runtime apps directory")
    parser.add_argument(
        "--replace-nonrunnable",
        action="store_true",
        help="Allow replacement only when the existing destination package is draft or disabled",
    )
    args = parser.parse_args()

    result = install_package(
        package_source=Path(args.package),
        instructions_source=Path(args.instructions),
        config_dir=Path(args.config_dir),
        replace_nonrunnable=args.replace_nonrunnable,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
