from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
PAID_PAGE = RUNTIME_DIR / "static" / "paid.html"


def test_paid_ui_legacy_fragment_token_is_removed_with_real_history_api():
    html = PAID_PAGE.read_text(encoding="utf-8")
    assert "window.history.replaceState" in html
    assert "params.get('access')" in html
    assert "const conversationHistory = []" in html
    assert "const history = []" not in html


def test_paid_ui_defaults_to_http_only_cookie_and_keeps_legacy_bearer_recovery_bounded():
    html = PAID_PAGE.read_text(encoding="utf-8")
    assert "Stripe決済後は自動でAIへ接続します" in html
    assert "bootstrapAccess()" in html
    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "X-WebAI-Entitlement" in html
    assert "旧アクセスコード" in html
    assert "通常の購入ではアクセスコードのコピーや入力は不要です" in html
