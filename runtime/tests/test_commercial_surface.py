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


def test_paid_buyer_page_requires_secure_transport_before_fragment_secret_processing():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    marker = 'if (app_config.get("access") or {}).get("mode") == "FREE":\n        return FileResponse(core.STATIC_DIR / "index.html")\n    require_secure_transport(request)'
    assert marker in source


def test_paid_buyer_page_has_no_store_no_referrer_frame_and_exfiltration_guards():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    assert 'response.headers["Cache-Control"] = "no-store"' in source
    assert 'response.headers["Referrer-Policy"] = "no-referrer"' in source
    assert 'response.headers["X-Frame-Options"] = "DENY"' in source
    assert "connect-src 'self'" in source
    assert "frame-ancestors 'none'" in source
