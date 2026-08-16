from __future__ import annotations

import importlib
import json
import os
import stat
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

RUNTIME_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = RUNTIME_DIR.parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from commercial_studio import adapt_manual_hosted_entitlement
from deployment_preflight import run_preflight
from package_install_cli import install_package
from studio import StudioDraft, build_package


class FakeUsage:
    input_tokens = 120
    output_tokens = 18


class FakeResponse:
    output_text = "e2e-paid-ok"
    usage = FakeUsage()


class FakeResponses:
    def __init__(self, sink):
        self.sink = sink

    def create(self, **kwargs):
        self.sink.append(kwargs)
        return FakeResponse()


class FakeOpenAI:
    created = []

    def __init__(self, api_key):
        self.api_key = api_key
        self.calls = []
        self.responses = FakeResponses(self.calls)
        type(self).created.append(self)


def private_mode(path: Path) -> bool:
    return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_full_studio_install_activate_entitle_runtime_byok_revoke_flow(tmp_path, monkeypatch, capsys):
    slug = "e2e-paid-ai"
    creator_marker = "E2E-CREATOR-INSTRUCTION-UNIQUE"
    export_dir = tmp_path / "export"
    config_dir = tmp_path / "apps"
    state_dir = tmp_path / "state"
    export_dir.mkdir()
    config_dir.mkdir()
    state_dir.mkdir()
    os.chmod(config_dir, 0o700)
    os.chmod(state_dir, 0o700)

    draft = StudioDraft(
        display_name="E2E Paid AI",
        slug=slug,
        description="Full lifecycle fixture",
        instructions=f"{creator_marker}\nAnswer briefly.",
        access_mode="BUY_ONCE",
        access_price_jpy=1500,
        checkout_setup_mode="SELF_SETUP",
        stripe_payment_link_url="https://buy.stripe.com/e2e_fixture",
        stripe_link_matches_configuration=True,
        allowed_payer_modes=["BYOK"],
        default_payer_mode="BYOK",
        default_model="gpt-5.6-luna",
        allowed_models=["gpt-5.6-luna"],
        protection_level="LEVEL_4_HOSTED_ONLY",
        welcome="E2E paid AI",
    )
    built = build_package(
        draft,
        schema_path=REPO_DIR / "package-schema" / "package.schema.json",
        available_models={"gpt-5.6-luna"},
    )
    adapted = adapt_manual_hosted_entitlement(built)
    package = adapted["package"]

    assert package["status"] == "draft"
    assert package["access"]["commercial_enforcement"] == "NOT_IMPLEMENTED"
    assert adapted["readiness"]["runtime"] == "DRAFT_REQUIRES_MANUAL_ENTITLEMENT_ACTIVATION"
    assert adapted["ready_to_run"] is False
    assert adapted["ready_to_sell"] is False

    package_source = export_dir / adapted["exports"]["package_filename"]
    instructions_source = export_dir / adapted["exports"]["instructions_filename"]
    package_source.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    instructions_source.write_text(draft.instructions, encoding="utf-8")

    installed = install_package(
        package_source=package_source,
        instructions_source=instructions_source,
        config_dir=config_dir,
    )
    deployed_package = Path(installed["package_path"])
    deployed_instructions = Path(installed["instructions_path"])
    assert deployed_package.parent == config_dir
    assert deployed_instructions.parent == config_dir
    assert private_mode(deployed_package)
    assert private_mode(deployed_instructions)

    env = {
        "WEB_AI_SERVICE_UNIT": "webai-bridge.service",
        "WEB_AI_WORKING_DIRECTORY": str(RUNTIME_DIR.resolve()),
        "WEB_AI_ROUTE_SURFACE": "commercial:app",
        "WEB_AI_CONFIG_DIR": str(config_dir.resolve()),
        "DEPLOYED_REVISION": "a" * 40,
        "WEB_AI_DIAGNOSTICS_ENABLED": "0",
        "WEB_AI_STUDIO_ENABLED": "0",
        "WEB_AI_ALLOW_INSECURE_HTTP": "0",
        "WEB_AI_ENTITLEMENT_DB": str((state_dir / "entitlements.sqlite3").resolve()),
        "WEB_AI_LEDGER_PATH": str((state_dir / "ledger.sqlite3").resolve()),
    }

    draft_preflight = run_preflight(
        env=env,
        runtime_dir=RUNTIME_DIR,
        config_dir=config_dir,
        verify_git_revision=False,
    )
    assert draft_preflight["ok"] is True
    assert draft_preflight["active_packages"] == 0
    assert draft_preflight["active_paid_packages"] == 0

    entitlement_cli = importlib.import_module("entitlement_cli")
    assert entitlement_cli.cmd_activate_config(
        SimpleNamespace(config=str(deployed_package), checkout_reviewed=False)
    ) == 0
    capsys.readouterr()
    activated = json.loads(deployed_package.read_text(encoding="utf-8"))
    assert activated["status"] == "active"
    assert activated["access"]["commercial_enforcement"] == "ENTITLEMENT_ENFORCED"
    assert activated["access"]["checkout"]["binding_verification"] == "CREATOR_ATTESTED"
    assert private_mode(deployed_package), "activation must not widen Package JSON permissions"

    active_preflight = run_preflight(
        env=env,
        runtime_dir=RUNTIME_DIR,
        config_dir=config_dir,
        verify_git_revision=False,
    )
    assert active_preflight["ok"] is True
    assert active_preflight["active_packages"] == 1
    assert active_preflight["active_paid_packages"] == 1
    assert active_preflight["findings"] == []

    entitlement_db = state_dir / "entitlements.sqlite3"
    assert entitlement_cli.cmd_issue(
        SimpleNamespace(
            config=str(deployed_package),
            payment_verified=True,
            payment_ref="pay_e2e_001",
            buyer_ref="buyer-e2e-001",
            days=None,
            base_url="https://e2e.example.com",
            db=str(entitlement_db),
        )
    ) == 0
    issue_output = json.loads(capsys.readouterr().out)
    buyer_token = issue_output["token"]
    assert buyer_token.startswith("webai_")
    assert buyer_token.encode() not in entitlement_db.read_bytes()

    # Import the actual commercial runtime only after the installed package and
    # entitlement state exist, mirroring a service restart/reload after activation.
    monkeypatch.setenv("WEB_AI_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("WEB_AI_LEDGER_PATH", str(state_dir / "ledger.sqlite3"))
    monkeypatch.setenv("WEB_AI_ENTITLEMENT_DB", str(entitlement_db))
    monkeypatch.setenv("WEB_AI_REQUESTS_PER_MINUTE", "999")
    monkeypatch.setenv("WEB_AI_ALLOW_INSECURE_HTTP", "1")
    monkeypatch.setenv("WEB_AI_STUDIO_ENABLED", "0")
    monkeypatch.setenv("WEB_AI_DIAGNOSTICS_ENABLED", "0")

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    FakeOpenAI.created = []
    for name in ["commercial", "app", "entitlements", "cost_router"]:
        sys.modules.pop(name, None)
    commercial = importlib.import_module("commercial")
    client = TestClient(commercial.app)

    assert set(commercial.core.registry.apps) == {slug}
    assert creator_marker in commercial.core.registry.get(slug)["_instructions"]

    denied = client.get(f"/apps/{slug}/public-config")
    assert denied.status_code == 401

    config = client.get(
        f"/apps/{slug}/public-config",
        headers={"X-WebAI-Entitlement": buyer_token},
    )
    assert config.status_code == 200
    assert config.json()["status"] == "active"
    assert config.json()["allowed_payer_modes"] == ["BYOK"]

    chat = client.post(
        "/api/chat",
        headers={
            "X-WebAI-Entitlement": buyer_token,
            "X-Provider-API-Key": "buyer-provider-secret",
        },
        json={
            "slug": slug,
            "message": "confirm",
            "history": [],
            "payer_mode": "BYOK",
        },
    )
    assert chat.status_code == 200
    assert chat.json()["text"] == "e2e-paid-ok"
    assert chat.json()["payer_mode"] == "BYOK"
    assert FakeOpenAI.created[-1].api_key == "buyer-provider-secret"
    call = FakeOpenAI.created[-1].calls[-1]
    assert creator_marker in call["instructions"]
    assert "WebAI Bridge Hosted Safety Policy" in call["instructions"]
    assert call["store"] is False

    # Revoke using only the non-secret payment reference: operator does not need
    # to retain plaintext bearer tokens to stop a leaked/replaced buyer token.
    assert commercial.entitlements.revoke_payment(
        package_id=slug,
        payment_ref="pay_e2e_001",
    ) == 1
    before = len(FakeOpenAI.created)
    revoked = client.post(
        "/api/chat",
        headers={
            "X-WebAI-Entitlement": buyer_token,
            "X-Provider-API-Key": "buyer-provider-secret",
        },
        json={"slug": slug, "message": "should fail", "history": [], "payer_mode": "BYOK"},
    )
    assert revoked.status_code == 401
    assert len(FakeOpenAI.created) == before
