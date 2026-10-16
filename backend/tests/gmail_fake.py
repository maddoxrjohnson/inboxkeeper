"""A tiny stand-in for the Gmail REST API, wired in at the HTTP layer.

Plugging in below googleapiclient means the real request building, batch
encoding and error handling all get exercised by the tests.
"""

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httplib2
from googleapiclient.discovery import build

Route = Callable[[str, str, dict[str, list[str]], Any], tuple[int, Any]]


class FakeGmailHttp:
    def __init__(self, route: Route) -> None:
        self.route = route
        self.requests: list[tuple[str, str]] = []
        self.on_batch_start: Callable[[], None] = lambda: None

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: str | bytes | None = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> tuple[httplib2.Response, bytes]:
        headers = headers or {}
        if isinstance(body, bytes):
            body = body.decode()
        parts = urlsplit(uri)
        if parts.path == "/batch":
            return self._batch(body or "", headers["content-type"])
        status, payload = self._dispatch(method, parts.path, parts.query, body)
        return _response(status), json.dumps(payload).encode()

    def _dispatch(self, method: str, path: str, query: str, body: str | None) -> tuple[int, Any]:
        path = path.removeprefix("/gmail/v1")
        self.requests.append((method, path))
        return self.route(method, path, parse_qs(query), json.loads(body) if body else None)

    def _batch(self, body: str, content_type: str) -> tuple[httplib2.Response, bytes]:
        boundary = re.search(r'boundary="?([^";]+)"?', content_type)
        assert boundary
        self.on_batch_start()
        out = []
        for part in body.split(f"--{boundary.group(1)}"):
            content_id = re.search(r"Content-ID: <([^>]+)>", part)
            request_line = re.search(r"^(GET|POST) (\S+) HTTP/1.1", part, re.MULTILINE)
            if not (content_id and request_line):
                continue
            url = urlsplit(request_line.group(2))
            status, payload = self._dispatch(request_line.group(1), url.path, url.query, None)
            out.append(
                "--BOUNDARY\r\n"
                "Content-Type: application/http\r\n"
                f"Content-ID: <response-{content_id.group(1)}>\r\n\r\n"
                f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n\r\n"
                f"{json.dumps(payload)}\r\n"
            )
        content = "".join(out) + "--BOUNDARY--"
        resp = _response(200, {"content-type": "multipart/mixed; boundary=BOUNDARY"})
        return resp, content.encode()


def _response(status: int, extra: dict[str, str] | None = None) -> httplib2.Response:
    return httplib2.Response(
        {"status": str(status), "content-type": "application/json", **(extra or {})}
    )


def error(status: int, reason: str = "error") -> tuple[int, Any]:
    return status, {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}


def build_service(http: FakeGmailHttp) -> Any:
    return build("gmail", "v1", http=http, static_discovery=True)


def message_resource(msg_id: str, **overrides: Any) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "id": msg_id,
        "threadId": f"t-{msg_id}",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Don&#39;t miss out",
        "sizeEstimate": 4321,
        "internalDate": "1767225600000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Shop <deals@shop.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Big sale"},
            ],
        },
    }
    resource.update(overrides)
    return resource
