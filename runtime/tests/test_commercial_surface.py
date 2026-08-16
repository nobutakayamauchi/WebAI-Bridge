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


def test_paid_buyer_page_requires_secure_transport_after_free_surface_branch():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    marker = 'if (app_config.get("access") or {}).get("mode") == "FREE":\n        return free_page_response()\n    require_secure_transport(request)'
    assert marker in source


def test_free_buyer_page_is_no_store_so_mobile_safari_cannot_reuse_stale_byok_ui():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    assert "def free_page_response()" in source
    assert 'response.headers["Cache-Control"] = "no-store, max-age=0"' in source
    assert 'response.headers["Pragma"] = "no-cache"' in source
    assert 'response.headers["Expires"] = "0"' in source


def test_paid_buyer_page_has_no_store_no_referrer_frame_and_exfiltration_guards():
    source = (RUNTIME_DIR / "commercial.py").read_text(encoding="utf-8")
    assert 'response.headers["Cache-Control"] = "no-store"' in source
    assert 'response.headers["Referrer-Policy"] = "no-referrer"' in source
    assert 'response.headers["X-Frame-Options"] = "DENY"' in source
    assert "connect-src 'self'" in source
    assert "frame-ancestors 'none'" in source


def test_free_and_paid_byok_surfaces_use_explicit_connect_then_hide_copy():
    for name in ["index.html", "paid.html"]:
        source = (RUNTIME_DIR / "static" / name).read_text(encoding="utf-8")
        assert '>APIを接続</button>' in source
        assert "✓ API接続済み" in source
        assert "setByokState(true" in source
        assert "hidden = !byokConnected" in source or "hidden = !byok || !byokConnected" in source
