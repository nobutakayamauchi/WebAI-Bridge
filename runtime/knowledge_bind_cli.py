from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from pathlib import Path

from package_knowledge import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_CONTEXT_CHARS,
    MAX_KNOWLEDGE_CHARS,
    PACKAGE_TEXT_BACKEND,
)
from studio import validate_package_document

BASE_DIR = Path(__file__).resolve().parent
PACKAGE_SCHEMA_FILE = BASE_DIR.parent / "package-schema" / "package.schema.json"


def _regular_non_symlink(path: Path, label: str) -> None:
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise SystemExit(f"{label} must be an existing regular non-symlink file: {path}")


def _read_knowledge(path: Path) -> str:
    _regular_non_symlink(path, "Knowledge source")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise SystemExit(f"Knowledge source must be UTF-8 text: {exc}") from exc
    if not text.strip():
        raise SystemExit("Knowledge source must not be empty")
    if "\x00" in text:
        raise SystemExit("Knowledge source must not contain NUL bytes")
    if len(text) > MAX_KNOWLEDGE_CHARS:
        raise SystemExit(f"Knowledge source exceeds {MAX_KNOWLEDGE_CHARS} characters")
    return text


def _load_package(path: Path) -> dict:
    _regular_non_symlink(path, "Package JSON")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Package JSON is invalid: {exc}") from exc
    errors = validate_package_document(data, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Package schema invalid: " + "; ".join(errors))
    slug = str(data.get("slug") or "")
    if not slug or data.get("id") != slug:
        raise SystemExit("Package id/slug authority is invalid")
    delivery = data.get("delivery") or {}
    if delivery.get("mode") != "HOSTED_ONLY" or delivery.get("runtime_implementation") != "AVAILABLE":
        raise SystemExit("Package-owned Knowledge v1 binds only to Hosted runtime packages")
    if data.get("status") not in {"draft", "dogfood", "active", "disabled"}:
        raise SystemExit("Package status is not recognized")
    return data


def _stage(path: Path, *, content: bytes, mode: int = 0o600) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, mode)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _restore(path: Path, previous: bytes | None, previous_mode: int) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    staged = _stage(path, content=previous, mode=previous_mode)
    try:
        os.replace(staged, path)
        staged = None
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def bind_package_text_knowledge(
    *,
    package_path: Path,
    knowledge_source: Path,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    allow_active: bool = False,
) -> dict:
    data = _load_package(package_path)
    if data.get("status") in {"active", "dogfood"} and not allow_active:
        raise SystemExit(
            "Refusing to mutate runnable package Knowledge without explicit allow_active acknowledgement"
        )
    knowledge_text = _read_knowledge(knowledge_source)
    slug = data["slug"]
    config_dir = package_path.parent.resolve()
    if package_path.resolve().parent != config_dir:
        raise SystemExit("Package path authority is invalid")
    mode = stat.S_IMODE(config_dir.stat().st_mode)
    if mode & 0o002:
        raise SystemExit("Package config directory must not be world-writable")

    if not 256 <= max_context_chars <= 50_000:
        raise SystemExit("max-context-chars must be between 256 and 50000")
    if not 1 <= max_chunks <= 12:
        raise SystemExit("max-chunks must be between 1 and 12")
    if not 200 <= chunk_chars <= 8000:
        raise SystemExit("chunk-chars must be between 200 and 8000")

    knowledge_dest = config_dir / f"{slug}.knowledge.md"
    if knowledge_dest.is_symlink():
        raise SystemExit("Knowledge destination must not be a symlink")

    previous_knowledge = knowledge_dest.read_bytes() if knowledge_dest.exists() else None
    previous_knowledge_mode = (
        stat.S_IMODE(knowledge_dest.stat().st_mode) if knowledge_dest.exists() else 0o600
    )
    previous_package = package_path.read_bytes()
    previous_package_mode = stat.S_IMODE(package_path.stat().st_mode)

    updated = dict(data)
    updated["knowledge"] = {
        "enabled": True,
        "backend": PACKAGE_TEXT_BACKEND,
        "file": f"apps/{slug}.knowledge.md",
        "max_context_chars": max_context_chars,
        "max_chunks": max_chunks,
        "chunk_chars": chunk_chars,
        "vector_store_env": "",
        "reserve_tokens": 0,
        "platform_tool_reserve_usd_micros": 0,
    }
    errors = validate_package_document(updated, schema_path=PACKAGE_SCHEMA_FILE)
    if errors:
        raise SystemExit("Updated package schema invalid: " + "; ".join(errors))

    package_bytes = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    knowledge_staged = _stage(knowledge_dest, content=knowledge_text.encode("utf-8"), mode=0o600)
    package_staged = _stage(package_path, content=package_bytes, mode=0o600)
    knowledge_committed = False
    package_committed = False
    try:
        # Knowledge arrives before Package JSON advertises it.
        os.replace(knowledge_staged, knowledge_dest)
        knowledge_staged = None
        knowledge_committed = True
        os.replace(package_staged, package_path)
        package_staged = None
        package_committed = True
        try:
            fd = os.open(config_dir, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
    except Exception:
        if knowledge_committed and not package_committed:
            try:
                _restore(knowledge_dest, previous_knowledge, previous_knowledge_mode)
                _restore(package_path, previous_package, previous_package_mode)
            except Exception as restore_exc:
                raise RuntimeError("Knowledge bind failed and rollback also failed; operator intervention required") from restore_exc
        raise
    finally:
        if knowledge_staged is not None:
            knowledge_staged.unlink(missing_ok=True)
        if package_staged is not None:
            package_staged.unlink(missing_ok=True)

    return {
        "status": "BOUND",
        "slug": slug,
        "package_status": updated.get("status"),
        "backend": PACKAGE_TEXT_BACKEND,
        "knowledge_path": str(knowledge_dest),
        "knowledge_chars": len(knowledge_text),
        "secrets_in_output": False,
        "next": "Restart the commercial runtime and rerun deployment preflight before external use.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind server-owned package Knowledge to an existing Hosted AI Package")
    parser.add_argument("--config", required=True, help="Deployed Package JSON")
    parser.add_argument("--knowledge", required=True, help="UTF-8 markdown/text Knowledge source")
    parser.add_argument("--max-context-chars", type=int, default=DEFAULT_MAX_CONTEXT_CHARS)
    parser.add_argument("--max-chunks", type=int, default=DEFAULT_MAX_CHUNKS)
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument(
        "--allow-active",
        action="store_true",
        help="Explicitly acknowledge mutation of an active/dogfood package; restart and preflight are still required",
    )
    args = parser.parse_args()
    try:
        result = bind_package_text_knowledge(
            package_path=Path(args.config),
            knowledge_source=Path(args.knowledge),
            max_context_chars=args.max_context_chars,
            max_chunks=args.max_chunks,
            chunk_chars=args.chunk_chars,
            allow_active=args.allow_active,
        )
    except (SystemExit, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "secrets_in_output": False}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
