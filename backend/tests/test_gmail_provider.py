from datetime import UTC, datetime
from typing import Any

import pytest
from googleapiclient.errors import HttpError

from inboxkeeper.mail.headers import AuthResults, UnsubscribeInfo
from inboxkeeper.providers.base import CursorExpiredError
from inboxkeeper.providers.gmail import GmailProvider, parse_message
from tests.gmail_fake import FakeGmailHttp, build_service, error, message_resource


def make_provider(
    route: Any, batch_size: int = 50
) -> tuple[GmailProvider, FakeGmailHttp, list[float]]:
    http = FakeGmailHttp(route)
    sleeps: list[float] = []
    provider = GmailProvider(build_service(http), sleep=sleeps.append, batch_size=batch_size)
    return provider, http, sleeps


def test_parse_message() -> None:
    resource = message_resource("m1")
    resource["payload"]["headers"] += [
        {"name": "Cc", "value": "Friend <friend@x.com>"},
        {"name": "List-Id", "value": "<deals.shop.com>"},
        {"name": "List-Unsubscribe", "value": "<https://shop.com/u?id=1>"},
        {"name": "List-Unsubscribe-Post", "value": "List-Unsubscribe=One-Click"},
        {
            "name": "Authentication-Results",
            "value": "mx.google.com; spf=pass; dkim=pass; dmarc=pass",
        },
    ]

    meta = parse_message(resource)

    assert meta.id == "m1"
    assert meta.thread_id == "t-m1"
    assert meta.received_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert meta.labels == {"INBOX", "UNREAD"}
    assert meta.sender_email == "deals@shop.com"
    assert meta.sender_name == "Shop"
    assert meta.recipients == ("me@example.com", "friend@x.com")
    assert meta.snippet == "Don't miss out"
    assert meta.list_id == "<deals.shop.com>"
    assert meta.unsubscribe == UnsubscribeInfo(http_url="https://shop.com/u?id=1", one_click=True)
    assert meta.auth == AuthResults(spf="pass", dkim="pass", dmarc="pass")
    assert meta.mime_type == "multipart/alternative"


def test_parse_message_tolerates_missing_fields() -> None:
    meta = parse_message({"id": "m1", "threadId": "t1", "internalDate": "0"})
    assert meta.labels == frozenset()
    assert meta.sender_email == ""
    assert meta.unsubscribe is None


def test_iter_message_ids_pages_and_excludes_trash() -> None:
    seen_queries: list[dict[str, list[str]]] = []

    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        assert path == "/users/me/messages"
        seen_queries.append(query)
        if "pageToken" not in query:
            return 200, {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"}
        return 200, {"messages": [{"id": "c"}]}

    provider, _, _ = make_provider(route)

    assert list(provider.iter_message_ids()) == ["a", "b", "c"]
    assert seen_queries[0]["q"] == ["-in:trash"]
    assert seen_queries[0]["includeSpamTrash"] == ["true"]
    assert seen_queries[1]["pageToken"] == ["p2"]


def test_get_messages_batches_and_skips_missing() -> None:
    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        msg_id = path.rsplit("/", 1)[1]
        assert query["format"] == ["metadata"]
        if msg_id == "gone":
            return error(404, "notFound")
        return 200, message_resource(msg_id)

    provider, http, _ = make_provider(route, batch_size=2)
    metas = provider.get_messages(["a", "gone", "b"])

    assert [m.id for m in metas] == ["a", "b"]
    assert len(http.requests) == 3


def test_get_messages_retries_rate_limited_requests() -> None:
    attempts: dict[str, int] = {}

    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        msg_id = path.rsplit("/", 1)[1]
        attempts[msg_id] = attempts.get(msg_id, 0) + 1
        if msg_id == "busy" and attempts[msg_id] < 3:
            return error(429, "rateLimitExceeded")
        return 200, message_resource(msg_id)

    provider, _, sleeps = make_provider(route)
    metas = provider.get_messages(["ok", "busy"])

    assert {m.id for m in metas} == {"ok", "busy"}
    assert attempts == {"ok": 1, "busy": 3}
    assert len(sleeps) == 2


def test_get_messages_raises_on_permanent_errors() -> None:
    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        return error(400, "badRequest")

    provider, _, _ = make_provider(route)
    with pytest.raises(HttpError):
        provider.get_messages(["a"])


def test_changes_since_collects_history() -> None:
    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        assert path == "/users/me/history"
        assert query["startHistoryId"] == ["100"]
        if "pageToken" not in query:
            return 200, {
                "history": [
                    {"messagesAdded": [{"message": {"id": "new"}}]},
                    {"labelsAdded": [{"message": {"id": "starred"}, "labelIds": ["STARRED"]}]},
                ],
                "nextPageToken": "p2",
                "historyId": "150",
            }
        return 200, {
            "history": [
                {"labelsRemoved": [{"message": {"id": "read"}, "labelIds": ["UNREAD"]}]},
                {"messagesAdded": [{"message": {"id": "brief"}}]},
                {"messagesDeleted": [{"message": {"id": "brief"}}]},
            ],
            "historyId": "175",
        }

    provider, _, _ = make_provider(route)
    changes = provider.changes_since("100")

    assert changes.changed == {"new", "starred", "read"}
    assert changes.deleted == {"brief"}
    assert changes.cursor == "175"


def test_changes_since_raises_when_history_expired() -> None:
    provider, _, _ = make_provider(lambda *_: error(404, "notFound"))
    with pytest.raises(CursorExpiredError):
        provider.changes_since("1")


def test_account_email_and_cursor_come_from_profile() -> None:
    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        assert path == "/users/me/profile"
        return 200, {"emailAddress": "me@gmail.com", "historyId": "4242"}

    provider, http, _ = make_provider(route)

    assert provider.get_account_email() == "me@gmail.com"
    assert provider.get_account_email() == "me@gmail.com"
    assert provider.get_cursor() == "4242"
    assert len(http.requests) == 2


def test_modify_labels_uses_batch_modify() -> None:
    bodies: list[Any] = []

    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        assert (method, path) == ("POST", "/users/me/messages/batchModify")
        bodies.append(body)
        return 204, {}

    provider, _, _ = make_provider(route)
    provider.modify_labels(["a", "b"], remove=["INBOX"])

    assert bodies == [{"ids": ["a", "b"], "addLabelIds": [], "removeLabelIds": ["INBOX"]}]


def test_trash_and_untrash() -> None:
    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        return 200, {"id": path.split("/")[-2]}

    provider, http, _ = make_provider(route)
    provider.trash(["a", "b"])
    provider.untrash(["a"])

    assert http.requests == [
        ("POST", "/users/me/messages/a/trash"),
        ("POST", "/users/me/messages/b/trash"),
        ("POST", "/users/me/messages/a/untrash"),
    ]


def test_top_level_requests_retry_with_backoff() -> None:
    calls = 0

    def route(method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return error(403, "userRateLimitExceeded")
        return 200, {"emailAddress": "me@gmail.com", "historyId": "1"}

    provider, _, sleeps = make_provider(route)

    assert provider.get_account_email() == "me@gmail.com"
    assert len(sleeps) == 1
