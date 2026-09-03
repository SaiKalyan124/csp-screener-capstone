from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app as hosted_app


def settings(**overrides: object) -> SimpleNamespace:
    values = {
        "auth_required": False,
        "supabase_url": None,
        "supabase_anon_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_local_mode_does_not_require_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hosted_app, "load_settings", lambda: settings())

    assert hosted_app.require_user(None) is None
    assert hosted_app.runtime_config() == {
        "auth_required": False,
        "supabase_url": None,
        "supabase_anon_key": None,
    }


def test_hosted_mode_rejects_missing_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hosted_app,
        "load_settings",
        lambda: settings(
            auth_required=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="public-anon-key",
        ),
    )

    with pytest.raises(HTTPException) as error:
        hosted_app.require_user(None)

    assert error.value.status_code == 401
    assert error.value.detail == "Sign in is required."


def test_hosted_mode_exposes_only_public_client_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hosted_app,
        "load_settings",
        lambda: settings(
            auth_required=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="public-anon-key",
        ),
    )

    assert hosted_app.runtime_config() == {
        "auth_required": True,
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "public-anon-key",
    }
