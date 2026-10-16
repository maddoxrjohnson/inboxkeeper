import json
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from inboxkeeper.api.app import create_app
from inboxkeeper.api.context import AppContext
from inboxkeeper.auth.google import AuthError
from inboxkeeper.config import Settings
from inboxkeeper.providers.base import INBOX, SPAM, UNREAD
from inboxkeeper.providers.fake import FakeProvider
from tests.factories import make_message


def sync_and_wait(client: TestClient, ctx: AppContext, **body: Any) -> dict[str, Any]:
    resp = client.post("/api/sync", json=body)
    assert resp.status_code == 202
    ctx.sync.join(timeout=5)
    result: dict[str, Any] = client.get("/api/sync").json()
    return result


def test_account_when_nothing_is_set_up(client: TestClient) -> None:
    assert client.get("/api/account").json() == {
        "connected": False,
        "email": None,
        "has_client_secrets": False,
        "last_synced_at": None,
        "message_count": 0,
    }


@pytest.mark.usefixtures("connected")
def test_sync_then_account_reflects_cache(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    for _ in range(3):
        provider.deliver(make_message())

    status = sync_and_wait(client, ctx)
    assert status["state"] == "done"
    assert status["mode"] == "full"
    assert status["fetched"] == 3

    account = client.get("/api/account").json()
    assert account["connected"]
    assert account["email"] == "me@example.com"
    assert account["message_count"] == 3
    assert account["last_synced_at"] is not None


def test_sync_requires_connection(client: TestClient) -> None:
    assert client.post("/api/sync").status_code == 401


@pytest.mark.usefixtures("connected")
def test_sync_rejects_bad_limit(client: TestClient) -> None:
    assert client.post("/api/sync", json={"limit": 0}).status_code == 422


def test_concurrent_sync_is_rejected(settings: Settings, provider: FakeProvider) -> None:
    gate = threading.Event()

    def slow_factory() -> FakeProvider:
        gate.wait(timeout=5)
        return provider

    app = create_app(settings, provider_factory=slow_factory)
    ctx: AppContext = app.state.ctx
    ctx.auth.token_path.write_text("{}")
    client = TestClient(app)

    assert client.post("/api/sync").status_code == 202
    assert client.post("/api/sync").status_code == 409
    assert client.post("/api/auth/disconnect").status_code == 409
    gate.set()
    ctx.sync.join(timeout=5)


@pytest.mark.usefixtures("connected")
def test_stats(client: TestClient, ctx: AppContext, provider: FakeProvider) -> None:
    provider.deliver(
        make_message(sender_email="a@news.com", labels={INBOX, UNREAD}, size_estimate=100)
    )
    provider.deliver(make_message(sender_email="a@news.com", labels={INBOX}, size_estimate=300))
    provider.deliver(make_message(sender_email="b@friend.com", labels=set(), size_estimate=50))
    provider.deliver(make_message(sender_email="x@spam.biz", labels={SPAM}, size_estimate=10))
    sync_and_wait(client, ctx)

    stats = client.get("/api/stats").json()

    assert stats["total"] == 4
    assert stats["inbox"] == 2
    assert stats["inbox_unread"] == 1
    assert stats["spam"] == 1
    assert stats["total_size"] == 460
    assert [s["email"] for s in stats["top_senders"]] == ["a@news.com", "b@friend.com"]
    assert stats["top_senders"][0]["total_size"] == 400


def test_auth_start_without_client_secrets_reports_error(client: TestClient) -> None:
    resp = client.get("/api/auth/google/start")

    assert resp.status_code == 307
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert "No OAuth client" in query["auth_error"][0]


def test_auth_start_redirects_to_google(client: TestClient, ctx: AppContext) -> None:
    ctx.auth.client_secrets_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "abc",
                    "client_secret": "shh",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        )
    )
    resp = client.get("/api/auth/google/start")

    assert resp.headers["location"].startswith("https://accounts.google.com/")
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8765/"]


def test_callback_success(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(ctx.auth, "finish", lambda state, code: seen.append((state, code)))

    resp = client.get("/", params={"state": "s", "code": "c"})

    assert seen == [("s", "c")]
    assert resp.headers["location"] == "http://localhost:5173/?connected=1"


def test_callback_auth_error(
    client: TestClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(state: str, code: str) -> None:
        raise AuthError("link expired")

    monkeypatch.setattr(ctx.auth, "finish", fail)
    resp = client.get("/", params={"state": "s", "code": "c"})

    assert parse_qs(urlsplit(resp.headers["location"]).query) == {"auth_error": ["link expired"]}


def test_callback_user_cancelled(client: TestClient) -> None:
    resp = client.get("/", params={"error": "access_denied"})
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query == {"auth_error": ["Sign-in was cancelled."]}


def test_root_without_params_goes_to_frontend(client: TestClient) -> None:
    assert client.get("/").headers["location"] == "http://localhost:5173"


@pytest.mark.usefixtures("connected")
def test_disconnect_forgets_token_and_cache(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    provider.deliver(make_message())
    sync_and_wait(client, ctx)

    assert client.post("/api/auth/disconnect").status_code == 204

    account = client.get("/api/account").json()
    assert not account["connected"]
    assert account["message_count"] == 0
    assert account["last_synced_at"] is None
