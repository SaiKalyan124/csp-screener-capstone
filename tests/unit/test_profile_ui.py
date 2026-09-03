from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_profile_supports_guided_and_custom_modes() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="profile-view"' in html
    assert 'value="guided"' in html
    assert 'value="custom"' in html
    assert 'id="profile-capital"' in html
    assert 'id="profile-dte-min"' in html
    assert 'id="profile-delta-max"' in html
    assert "PROFILE_PRESETS" in script
    assert "Minimum values must not exceed maximum values." in script


def test_unused_history_navigation_is_removed() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert ">History<" not in html
    assert 'id="profile-nav"' in html
    assert 'id="screener-nav" data-short="S" href="#screener">CSP Screener</a>' in html


def test_profile_persistence_is_user_scoped_and_cached() -> None:
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    migration = (
        ROOT / "supabase" / "migrations" / "202609030003_user_profiles.sql"
    ).read_text(encoding="utf-8")

    assert '.from("user_profiles")' in script
    assert "profileLoadedForUser" in script
    assert 'onConflict: "user_id"' in script
    assert "enable row level security" in migration.lower()
    assert "force row level security" in migration.lower()
    assert migration.count("(select auth.uid()) = user_id") == 4
    assert "revoke all on public.user_profiles from anon" in migration.lower()


def test_profile_is_sent_to_screening_and_chat() -> None:
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert "function profileQuery" in script
    assert "profileQuery(symbol)" in script
    assert "profile: profileRequestPayload()" in script
    assert "excluded by the active profile" in script
    assert "exceeds the ${money.format(positionLimit)} profile limit" in script


def test_profile_fields_have_plain_language_hover_help() -> None:
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert "PROFILE_FIELD_HELP" in script
    assert "DTE means days to expiration" in script
    assert "less assignment probability" in script
    assert "Widest allowed bid/ask spread" in script


def test_llm_profile_advisor_requires_apply_then_explicit_save() -> None:
    script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert '"/api/profile/recommend"' in script
    assert "LLM PROFILE ADVISOR" in script
    assert "Apply recommendation" in script
    assert "applied to the form but not saved" in script
    assert "Recommended presets" in script
