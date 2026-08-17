from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import package_bundle_cli
from cost_router import PricingRegistry
from knowledge_artifact import text_sha256, validate_package_text_artifact
from knowledge_studio import KnowledgeStudioDraft, build_knowledge_studio_result
from package_knowledge import PACKAGE_TEXT_BACKEND
from studio import build_package, validate_package_document

BASE_DIR = Path(__file__).resolve().parents[1]
SCHEMA = BASE_DIR.parent / "package-schema" / "package.schema.json"
PRICING = BASE_DIR / "pricing.json"
UI = BASE_DIR.parent / "creator-studio" / "knowledge.html"


def _core():
    pricing = PricingRegistry(PRICING)
    return SimpleNamespace(
        pricing=pricing,
        PACKAGE_SCHEMA_FILE=SCHEMA,
        build_package=build_package,
        validate_package_document=validate_package_document,
    )


def _draft(*, slug: str = "knowledge-sale-ai", knowledge: str = "確認用の合言葉は青いカワセミです。") -> KnowledgeStudioDraft:
    core = _core()
    model = next(iter(core.pricing.models))
    return KnowledgeStudioDraft(
        display_name="Knowledge Sale AI",
        slug=slug,
        description="Instructions + Knowledge sale test",
        instructions="Knowledgeを参照し、関連するときだけ簡潔に回答してください。",
        welcome="質問してください。",
        knowledge_enabled=True,
        knowledge_text=knowledge,
        knowledge_max_context_chars=4000,
        knowledge_max_chunks=3,
        knowledge_chunk_chars=1200,
        access_mode="BUY_ONCE",
        access_price_jpy=500,
        checkout_setup_mode="SELF_SETUP",
        stripe_payment_link_url="https://buy.stripe.com/test_knowledge_bundle",
        stripe_link_matches_configuration=True,
        allowed_payer_modes=["BYOK"],
        default_payer_mode="BYOK",
        default_model=model,
        allowed_models=[model],
        protection_level="LEVEL_4_HOSTED_ONLY",
    )


def _export_sources(tmp_path: Path, *, slug: str = "knowledge-sale-ai", knowledge: str = "確認用の合言葉は青いカワセミです。"):
    draft = _draft(slug=slug, knowledge=knowledge)
    result = build_knowledge_studio_result(core=_core(), payload=draft)
    package_path = tmp_path / result["exports"]["package_filename"]
    instructions_path = tmp_path / result["exports"]["instructions_filename"]
    knowledge_path = tmp_path / result["exports"]["knowledge_filename"]
    package_path.write_text(json.dumps(result["package"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    instructions_path.write_text(draft.instructions + "\n", encoding="utf-8")
    knowledge_path.write_text(draft.knowledge_text, encoding="utf-8")
    return draft, result, package_path, instructions_path, knowledge_path


def test_creator_studio_exports_package_instructions_and_knowledge() -> None:
    draft = _draft()
    result = build_knowledge_studio_result(core=_core(), payload=draft)
    package = result["package"]
    knowledge = package["knowledge"]

    assert result["exports"] == {
        "package_filename": "knowledge-sale-ai.json",
        "instructions_filename": "knowledge-sale-ai.instructions.md",
        "knowledge_filename": "knowledge-sale-ai.knowledge.md",
    }
    assert knowledge["enabled"] is True
    assert knowledge["backend"] == PACKAGE_TEXT_BACKEND
    assert knowledge["file"] == "apps/knowledge-sale-ai.knowledge.md"
    assert knowledge["artifact_sha256"] == text_sha256(draft.knowledge_text)
    assert result["knowledge_artifact"]["chars"] == len(draft.knowledge_text)
    assert result["readiness"]["runtime"] == "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION"
    assert "HOSTED_ENTITLEMENT_NOT_IMPLEMENTED" not in result["readiness"]["blockers"]


def test_creator_studio_rejects_empty_knowledge() -> None:
    draft = _draft(knowledge="   ")
    with pytest.raises(ValueError, match="Knowledge text must not be empty"):
        build_knowledge_studio_result(core=_core(), payload=draft)


def test_three_artifact_install_then_activation(tmp_path: Path) -> None:
    draft, result, package_src, instructions_src, knowledge_src = _export_sources(tmp_path)
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)

    installed = package_bundle_cli.install_bundle(
        package_source=package_src,
        instructions_source=instructions_src,
        knowledge_source=knowledge_src,
        config_dir=config_dir,
    )
    assert installed["authority_commit"] == "PACKAGE_JSON_LAST"

    package_dest = config_dir / f"{draft.slug}.json"
    instructions_dest = config_dir / f"{draft.slug}.instructions.md"
    knowledge_dest = config_dir / f"{draft.slug}.knowledge.md"
    for path in (package_dest, instructions_dest, knowledge_dest):
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    deployed = json.loads(package_dest.read_text(encoding="utf-8"))
    assert validate_package_text_artifact(config_dir=config_dir, app_config=deployed, require_digest=True) == []

    activated = package_bundle_cli.activate_bundle(config_path=package_dest)
    assert activated["activated"] is True
    assert activated["knowledge_verified"] is True
    deployed = json.loads(package_dest.read_text(encoding="utf-8"))
    assert deployed["status"] == "active"
    assert deployed["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert deployed["readiness"]["runtime"] == "READY"
    assert validate_package_text_artifact(config_dir=config_dir, app_config=deployed, require_digest=True) == []


def test_activation_refuses_knowledge_changed_after_install(tmp_path: Path) -> None:
    draft, _result, package_src, instructions_src, knowledge_src = _export_sources(tmp_path)
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)
    package_bundle_cli.install_bundle(
        package_source=package_src,
        instructions_source=instructions_src,
        knowledge_source=knowledge_src,
        config_dir=config_dir,
    )
    knowledge_dest = config_dir / f"{draft.slug}.knowledge.md"
    knowledge_dest.write_text("改ざん済みKnowledge", encoding="utf-8")
    os.chmod(knowledge_dest, 0o600)

    with pytest.raises(SystemExit, match="SHA-256"):
        package_bundle_cli.activate_bundle(config_path=config_dir / f"{draft.slug}.json")

    deployed = json.loads((config_dir / f"{draft.slug}.json").read_text(encoding="utf-8"))
    assert deployed["status"] == "draft"
    assert deployed["access"]["commercial_enforcement"] == "NOT_IMPLEMENTED"


def test_install_rolls_back_support_assets_when_authority_commit_fails(tmp_path: Path, monkeypatch) -> None:
    draft, _result, package_src, instructions_src, knowledge_src = _export_sources(tmp_path)
    config_dir = tmp_path / "apps"
    config_dir.mkdir(mode=0o700)
    real_replace = package_bundle_cli.os.replace
    failed = False

    def fail_package_commit(src, dst):
        nonlocal failed
        if not failed and Path(dst).name == f"{draft.slug}.json":
            failed = True
            raise OSError("simulated package authority commit failure")
        return real_replace(src, dst)

    monkeypatch.setattr(package_bundle_cli.os, "replace", fail_package_commit)
    with pytest.raises(OSError, match="simulated package authority"):
        package_bundle_cli.install_bundle(
            package_source=package_src,
            instructions_source=instructions_src,
            knowledge_source=knowledge_src,
            config_dir=config_dir,
        )

    assert not (config_dir / f"{draft.slug}.json").exists()
    assert not (config_dir / f"{draft.slug}.instructions.md").exists()
    assert not (config_dir / f"{draft.slug}.knowledge.md").exists()


def test_knowledge_creator_studio_ui_has_three_exports() -> None:
    text = UI.read_text(encoding="utf-8")
    assert 'id="knowledgeText"' in text
    assert 'id="downloadPackage"' in text
    assert 'id="downloadInstructions"' in text
    assert 'id="downloadKnowledge"' in text
    assert "Package JSON + Instructions + Knowledge" in text
