import json
import stat
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from google_auth_oauthlib.flow import Flow

from inboxkeeper.auth.google import SCOPES, AuthError, GoogleAuth

REDIRECT = "http://127.0.0.1:8765/"

CLIENT = {
    "installed": {
        "client_id": "abc.apps.googleusercontent.com",
        "client_secret": "shh",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


@pytest.fixture
def auth(tmp_path: Path) -> GoogleAuth:
    (tmp_path / "credentials.json").write_text(json.dumps(CLIENT))
    return GoogleAuth(tmp_path)


@pytest.fixture
def fake_token_exchange(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    granted = list(SCOPES)

    def fetch_token(self: Flow, **kwargs: Any) -> None:
        assert kwargs == {"code": "the-code"}
        self.oauth2session.token = {
            "access_token": "access",
            "refresh_token": "refresh",
            "scope": granted,
            "expires_at": time.time() + 3600,
        }

    monkeypatch.setattr(Flow, "fetch_token", fetch_token)
    return granted


def state_from(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def test_start_builds_consent_url_with_pkce(auth: GoogleAuth) -> None:
    query = parse_qs(urlsplit(auth.start(REDIRECT)).query)

    assert query["scope"] == [" ".join(SCOPES)]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]


def test_start_requires_client_secrets(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="No OAuth client"):
        GoogleAuth(tmp_path).start(REDIRECT)


def test_start_rejects_web_clients(tmp_path: Path) -> None:
    (tmp_path / "credentials.json").write_text(json.dumps({"web": CLIENT["installed"]}))
    with pytest.raises(AuthError, match="Desktop app"):
        GoogleAuth(tmp_path).start(REDIRECT)


@pytest.mark.usefixtures("fake_token_exchange")
def test_finish_saves_private_token(auth: GoogleAuth) -> None:
    state = state_from(auth.start(REDIRECT))
    auth.finish(state, "the-code")

    assert auth.has_token()
    assert stat.S_IMODE(auth.token_path.stat().st_mode) == 0o600
    creds = auth.load_credentials()
    assert creds is not None
    assert creds.refresh_token == "refresh"


@pytest.mark.usefixtures("fake_token_exchange")
def test_finish_rejects_unknown_state(auth: GoogleAuth) -> None:
    auth.start(REDIRECT)
    with pytest.raises(AuthError, match="expired"):
        auth.finish("forged-state", "the-code")
    assert not auth.has_token()


def test_finish_requires_gmail_scope(auth: GoogleAuth, fake_token_exchange: list[str]) -> None:
    fake_token_exchange[:] = ["openid"]
    state = state_from(auth.start(REDIRECT))

    with pytest.raises(AuthError, match="permission"):
        auth.finish(state, "the-code")
    assert not auth.has_token()


def test_state_can_only_be_used_once(auth: GoogleAuth, fake_token_exchange: list[str]) -> None:
    state = state_from(auth.start(REDIRECT))
    auth.finish(state, "the-code")
    with pytest.raises(AuthError):
        auth.finish(state, "the-code")


def test_corrupt_token_is_discarded(auth: GoogleAuth) -> None:
    auth.token_path.write_text("{not json")

    assert auth.load_credentials() is None
    assert not auth.has_token()


@pytest.mark.usefixtures("fake_token_exchange")
def test_disconnect_revokes_and_deletes(auth: GoogleAuth, monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[Any] = []
    monkeypatch.setattr(
        "inboxkeeper.auth.google.requests.post", lambda url, **kw: revoked.append(kw["params"])
    )
    auth.finish(state_from(auth.start(REDIRECT)), "the-code")

    auth.disconnect()

    assert revoked == [{"token": "refresh"}]
    assert not auth.has_token()
