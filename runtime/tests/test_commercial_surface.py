from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]


def test_commercial_gateway_never_root_mounts_unentitled_core_app():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    assert 'app.mount("/", core.app)' not in source
    assert "Intentionally no root mount of core.app" in source


def test_commercial_gateway_explicitly_wraps_paid_config_and_chat_routes():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    assert '@app.get("/apps/{slug}/public-config")' in source
    assert '@app.post("/api/chat")' in source
    assert source.count("require_entitlement(app_config, buyer_token)") >= 2
