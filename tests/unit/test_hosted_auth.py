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
        "allowed_emails": (),
        "weekly_ai_budget_usd": 3.0,
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


def test_hosted_mode_rejects_authenticated_email_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b'{"id":"00000000-0000-0000-0000-000000000001","email":"outsider@example.com"}'

    monkeypatch.setattr(
        hosted_app,
        "load_settings",
        lambda: settings(
            auth_required=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="public-anon-key",
            allowed_emails=("member@example.com",),
        ),
    )
    monkeypatch.setattr(hosted_app, "urlopen", lambda *args, **kwargs: Response())

    with pytest.raises(HTTPException) as error:
        hosted_app.require_user("Bearer valid-token")

    assert error.value.status_code == 403


def test_hosted_mode_accepts_authenticated_email_on_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b'{"id":"00000000-0000-0000-0000-000000000001","email":"MEMBER@example.com"}'

    monkeypatch.setattr(
        hosted_app,
        "load_settings",
        lambda: settings(
            auth_required=True,
            supabase_url="https://example.supabase.co",
            supabase_anon_key="public-anon-key",
            allowed_emails=("member@example.com",),
        ),
    )
    monkeypatch.setattr(hosted_app, "urlopen", lambda *args, **kwargs: Response())

    user = hosted_app.require_user("Bearer valid-token")
    assert user is not None
    assert user.email == "member@example.com"
    assert user.access_token == "valid-token"


def test_weekly_budget_rejection_returns_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    user = hosted_app.AuthenticatedUser(user_id="user-1", email="a@example.com", access_token="token")

    class Quota:
        def __init__(self, *_args):
            pass

        def reserve(self, *_args):
            return {"allowed": False, "resets_at": "Monday"}

    monkeypatch.setattr(hosted_app, "load_settings", lambda: settings(
        supabase_url="https://example.supabase.co", supabase_anon_key="anon"
    ))
    monkeypatch.setattr(hosted_app, "SupabaseUsageQuota", Quota)

    with pytest.raises(HTTPException) as error:
        hosted_app.reserve_ai_budget(user, 0.03)

    assert error.value.status_code == 429
    assert "$3.00" in error.value.detail
