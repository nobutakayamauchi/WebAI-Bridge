from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RUNTIME_DIR.parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import package_install_cli as installer


def draft_package(slug="second-ai") -> dict:
    data = json.loads((REPO_DIR / "package-schema" / "package.example.json").read_text(encoding="utf-8"))
    data["id"] = slug
    data["slug"] = slug
    data["display_name"] = "Second AI"
    data["status"] = "draft"
    data["instructions_file"] = f"apps/{slug}.instructions.md"
    data["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": ["HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"],
    }
    return data


def write_sources(tmp_path: Path, package: dict | None = None, instructions="private instructions"):
    package = draft_package() if package is None else package
    package_path = tmp_path / "export.json"
    instructions_path = tmp_path / "export.instructions.md"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    instructions_path.write_text(instructions, encoding="utf-8")
    return package_path, instructions_path


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_new_install_writes_canonical_owner_only_draft_files(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path)

    result = installer.install_package(
        package_source=package_source,
        instructions_source=instructions_source,
        config_dir=config_dir,
    )

    package_dest = config_dir / "second-ai.json"
    instructions_dest = config_dir / "second-ai.instructions.md"
    assert result["installed"] is True
    assert result["status"] == "draft"
    assert package_dest.exists() and instructions_dest.exists()
    installed = json.loads(package_dest.read_text(encoding="utf-8"))
    assert installed["status"] == "draft"
    assert installed["access"]["commercial_enforcement"] == "NOT_IMPLEMENTED"
    assert instructions_dest.read_text(encoding="utf-8") == "private instructions"
    assert mode(package_dest) & 0o077 == 0
    assert mode(instructions_dest) & 0o077 == 0
    assert not list(config_dir.glob("*.tmp"))


def test_install_never_accepts_active_or_preactivated_export(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()

    package = draft_package()
    package["status"] = "active"
    package["readiness"]["runtime"] = "READY"
    source, instructions = write_sources(tmp_path, package)
    with pytest.raises(SystemExit, match="Only draft"):
        installer.install_package(package_source=source, instructions_source=instructions, config_dir=config_dir)

    package = draft_package()
    package["access"]["commercial_enforcement"] = "ENTITLEMENT_ENFORCED"
    source.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(SystemExit, match="ENTITLEMENT_ENFORCED"):
        installer.install_package(package_source=source, instructions_source=instructions, config_dir=config_dir)


def test_draft_cannot_claim_runtime_ready(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package = draft_package()
    package["readiness"]["runtime"] = "READY"
    source, instructions = write_sources(tmp_path, package)
    with pytest.raises(SystemExit, match="must not claim readiness.runtime=READY"):
        installer.install_package(package_source=source, instructions_source=instructions, config_dir=config_dir)


def test_noncanonical_instructions_path_and_secret_material_are_rejected(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package = draft_package()
    package["instructions_file"] = "../secret.md"
    source, instructions = write_sources(tmp_path, package)
    with pytest.raises(SystemExit):
        installer.install_package(package_source=source, instructions_source=instructions, config_dir=config_dir)

    package = draft_package()
    package["credential"] = {"api_key": "sk-secret"}
    source.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(SystemExit, match="secret-like"):
        installer.install_package(package_source=source, instructions_source=instructions, config_dir=config_dir)


def test_empty_oversized_or_symlinked_instructions_are_rejected(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path, instructions="   \n")
    with pytest.raises(SystemExit, match="must not be empty"):
        installer.install_package(package_source=package_source, instructions_source=instructions_source, config_dir=config_dir)

    instructions_source.write_text("x" * (installer.MAX_INSTRUCTIONS_CHARS + 1), encoding="utf-8")
    with pytest.raises(SystemExit, match="exceed"):
        installer.install_package(package_source=package_source, instructions_source=instructions_source, config_dir=config_dir)

    real = tmp_path / "real.md"
    real.write_text("ok", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink unsupported in test environment")
    with pytest.raises(SystemExit, match="symlink"):
        installer.install_package(package_source=package_source, instructions_source=link, config_dir=config_dir)


def test_existing_active_or_dogfood_package_is_never_overwritten(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path)
    package_dest = config_dir / "second-ai.json"
    instructions_dest = config_dir / "second-ai.instructions.md"

    existing = draft_package()
    existing["status"] = "active"
    package_dest.write_text(json.dumps(existing), encoding="utf-8")
    instructions_dest.write_text("old active instructions", encoding="utf-8")
    before_package = package_dest.read_bytes()
    before_instructions = instructions_dest.read_bytes()

    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
            replace_nonrunnable=True,
        )
    assert package_dest.read_bytes() == before_package
    assert instructions_dest.read_bytes() == before_instructions


def test_existing_draft_requires_explicit_replace_and_then_replaces_both(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path, instructions="new instructions")
    package_dest = config_dir / "second-ai.json"
    instructions_dest = config_dir / "second-ai.instructions.md"

    existing = draft_package()
    package_dest.write_text(json.dumps(existing), encoding="utf-8")
    instructions_dest.write_text("old instructions", encoding="utf-8")

    with pytest.raises(SystemExit, match="--replace-nonrunnable"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
        )

    result = installer.install_package(
        package_source=package_source,
        instructions_source=instructions_source,
        config_dir=config_dir,
        replace_nonrunnable=True,
    )
    assert result["replaced_status"] == "draft"
    assert instructions_dest.read_text(encoding="utf-8") == "new instructions"


def test_orphan_instructions_are_not_overwritten(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path)
    orphan = config_dir / "second-ai.instructions.md"
    orphan.write_text("unknown origin", encoding="utf-8")

    with pytest.raises(SystemExit, match="orphan Instructions"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
            replace_nonrunnable=True,
        )
    assert orphan.read_text(encoding="utf-8") == "unknown origin"
    assert not (config_dir / "second-ai.json").exists()


def test_destination_symlink_is_rejected_before_write(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path)
    victim = tmp_path / "victim.md"
    victim.write_text("victim", encoding="utf-8")
    link = config_dir / "second-ai.instructions.md"
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlink unsupported in test environment")

    with pytest.raises(SystemExit, match="symlink"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
        )
    assert victim.read_text(encoding="utf-8") == "victim"


def test_second_replace_failure_rolls_back_new_install_without_orphan(tmp_path, monkeypatch):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path)
    real_replace = installer.os.replace
    calls = {"count": 0}

    def fail_second(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated package commit failure")
        return real_replace(src, dst)

    monkeypatch.setattr(installer.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
        )

    assert not (config_dir / "second-ai.json").exists()
    assert not (config_dir / "second-ai.instructions.md").exists()


def test_second_replace_failure_restores_previous_draft_instructions(tmp_path, monkeypatch):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    package_source, instructions_source = write_sources(tmp_path, instructions="new instructions")
    package_dest = config_dir / "second-ai.json"
    instructions_dest = config_dir / "second-ai.instructions.md"
    old_package = draft_package()
    package_dest.write_text(json.dumps(old_package), encoding="utf-8")
    instructions_dest.write_text("old instructions", encoding="utf-8")
    old_package_bytes = package_dest.read_bytes()

    real_replace = installer.os.replace
    calls = {"count": 0}

    def fail_package_once(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated package commit failure")
        return real_replace(src, dst)

    monkeypatch.setattr(installer.os, "replace", fail_package_once)
    with pytest.raises(OSError, match="simulated"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
            replace_nonrunnable=True,
        )

    assert package_dest.read_bytes() == old_package_bytes
    assert instructions_dest.read_text(encoding="utf-8") == "old instructions"
