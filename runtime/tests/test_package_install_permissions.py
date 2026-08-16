from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

RUNTIME_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RUNTIME_DIR.parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

import package_install_cli as installer


def test_world_writable_config_directory_is_rejected(tmp_path):
    config_dir = tmp_path / "apps"
    config_dir.mkdir()
    os.chmod(config_dir, 0o777)

    package = json.loads((REPO_DIR / "package-schema" / "package.example.json").read_text(encoding="utf-8"))
    package.update({
        "id": "second-ai",
        "slug": "second-ai",
        "display_name": "Second AI",
        "status": "draft",
        "instructions_file": "apps/second-ai.instructions.md",
    })
    package["readiness"] = {
        "configuration": "VALIDATED",
        "runtime": "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION",
        "commercial": "MANUAL_REVIEW_REQUIRED",
        "blockers": ["HOSTED_ENTITLEMENT_NOT_IMPLEMENTED"],
    }
    package_source = tmp_path / "package.json"
    instructions_source = tmp_path / "instructions.md"
    package_source.write_text(json.dumps(package), encoding="utf-8")
    instructions_source.write_text("private instructions", encoding="utf-8")

    with pytest.raises(SystemExit, match="world-writable"):
        installer.install_package(
            package_source=package_source,
            instructions_source=instructions_source,
            config_dir=config_dir,
        )
