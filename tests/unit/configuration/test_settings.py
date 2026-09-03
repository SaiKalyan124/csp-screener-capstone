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


def test_load_env_files_includes_nested_dotenv(monkeypatch) -> None:
    loaded: list[object] = []
    monkeypatch.setattr(config, "load_dotenv", lambda path, **kwargs: loaded.append(path))
    monkeypatch.delenv("CSP_SHARED_ENV_FILE", raising=False)

    config.load_env_files()

    assert config.ROOT / "csp-screener-capstone" / ".env" in loaded


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
