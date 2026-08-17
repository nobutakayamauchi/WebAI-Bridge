from __future__ import annotations

import hashlib
from pathlib import Path

from package_knowledge import PACKAGE_TEXT_BACKEND, load_package_text


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_knowledge_file(slug: str) -> str:
    return f"apps/{slug}.knowledge.md"


def validate_package_text_artifact(*, config_dir: Path, app_config: dict, require_digest: bool = False) -> list[str]:
    knowledge = app_config.get("knowledge") or {}
    if not knowledge.get("enabled") or knowledge.get("backend") != PACKAGE_TEXT_BACKEND:
        return []

    errors: list[str] = []
    slug = str(app_config.get("slug") or "")
    expected_file = canonical_knowledge_file(slug)
    if knowledge.get("file") != expected_file:
        errors.append(f"Package Knowledge file must be canonical: {expected_file}")
        return errors

    digest = str(knowledge.get("artifact_sha256") or "")
    if require_digest and len(digest) != 64:
        errors.append("PACKAGE_TEXT bundle requires knowledge.artifact_sha256")

    try:
        text = load_package_text(config_dir=config_dir, app_config=app_config)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    if digest and text_sha256(text) != digest:
        errors.append("Package Knowledge artifact SHA-256 does not match package metadata")
    return errors
