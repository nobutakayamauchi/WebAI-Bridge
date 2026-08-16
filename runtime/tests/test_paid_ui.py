from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
PAID_PAGE = RUNTIME_DIR / "static" / "paid.html"


def test_paid_ui_fragment_token_is_removed_with_real_history_api():
    html = PAID_PAGE.read_text(encoding="utf-8")
    assert "window.history.replaceState" in html
    assert "const conversationHistory = []" in html
    assert "const history = []" not in html


def test_paid_ui_keeps_bearer_out_of_query_and_persistent_local_storage():
    html = PAID_PAGE.read_text(encoding="utf-8")
    assert "location.hash" in html
    assert "#access=" in html
    assert "sessionStorage" in html
    assert "localStorage" not in html
    assert "X-WebAI-Entitlement" in html
