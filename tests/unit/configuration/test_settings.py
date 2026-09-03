import pytest

from csp_screener import config


def test_load_settings_accepts_alpaca_compatible_names(monkeypatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "test-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test-secret")

    settings = config.load_settings()

    assert settings.alpaca_key == "test-key"
    assert settings.alpaca_secret == "test-secret"


def test_load_settings_rejects_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)
    for name in (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="credentials are missing"):
        config.load_settings()


def test_load_settings_strips_hosted_secret_whitespace(monkeypatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("ALPACA_API_KEY", " test-key ")
    monkeypatch.setenv("ALPACA_SECRET_KEY", " test-secret\n")
    monkeypatch.setenv("SUPABASE_URL", " https://example.supabase.co\r\n")
    monkeypatch.setenv("SUPABASE_ANON_KEY", " publishable-key\n")
    monkeypatch.setenv("AUTH_REQUIRED", " true\n")

    settings = config.load_settings()

    assert settings.alpaca_key == "test-key"
    assert settings.alpaca_secret == "test-secret"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_anon_key == "publishable-key"
    assert settings.auth_required is True
