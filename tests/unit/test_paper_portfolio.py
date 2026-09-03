from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_portfolio_migration_enforces_user_scoped_rls() -> None:
    sql = (ROOT / "supabase/migrations/202609030002_paper_portfolio.sql").read_text()

    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert sql.count("auth.uid()) = user_id") == 4
    assert "revoke all on public.paper_option_positions from anon" in sql


def test_portfolio_ui_uses_explicit_paper_option_actions() -> None:
    html = (ROOT / "web/index.html").read_text()
    javascript = (ROOT / "web/app.js").read_text()

    assert 'id="portfolio-view"' in html
    assert "No orders are submitted" in html
    assert "SELL_TO_OPEN" in html and "SELL_TO_OPEN" in javascript
    assert "BUY_TO_OPEN" in html
    assert "Buy to close" in javascript
    assert "Sell to close" in javascript
