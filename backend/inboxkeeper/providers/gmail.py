import html
import logging
import random
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from itertools import batched
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from inboxkeeper.mail.headers import (
    parse_auth_results,
    parse_list_unsubscribe,
    parse_recipients,
    parse_sender,
)
from inboxkeeper.providers.base import ChangeSet, CursorExpiredError, MessageMeta

log = logging.getLogger(__name__)

METADATA_HEADERS = [
    "From",
    "To",
    "Cc",
    "Subject",
    "List-Id",
    "List-Unsubscribe",
    "List-Unsubscribe-Post",
    "Authentication-Results",
]

# Gmail allows up to 100 calls per batch but recommends 50; larger batches
# mostly just trade one big 429 for many small ones.
BATCH_SIZE = 50
MODIFY_CHUNK = 1000
MAX_ATTEMPTS = 6

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}


def parse_message(resource: dict[str, Any]) -> MessageMeta:
    payload = resource.get("payload", {})
    headers: dict[str, list[str]] = {}
    for h in payload.get("headers", []):
        headers.setdefault(h["name"].lower(), []).append(h["value"])

    def first(name: str) -> str | None:
        values = headers.get(name.lower())
        return values[0] if values else None

    sender_name, sender_email = parse_sender(first("From") or "")
    return MessageMeta(
        id=resource["id"],
        thread_id=resource["threadId"],
        received_at=datetime.fromtimestamp(int(resource["internalDate"]) / 1000, tz=UTC),
        labels=frozenset(resource.get("labelIds", [])),
        size_estimate=int(resource.get("sizeEstimate", 0)),
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=tuple(parse_recipients(first("To") or "", first("Cc") or "")),
        subject=first("Subject") or "",
        snippet=html.unescape(resource.get("snippet", "")),
        list_id=first("List-Id"),
        unsubscribe=parse_list_unsubscribe(
            first("List-Unsubscribe"), first("List-Unsubscribe-Post")
        ),
        auth=parse_auth_results(headers.get("authentication-results", [])),
        mime_type=payload.get("mimeType", ""),
    )


def _is_retryable(exc: HttpError) -> bool:
    status = exc.resp.status
    if status in _RETRYABLE_STATUS:
        return True
    if status == 403:
        details = exc.error_details if isinstance(exc.error_details, list) else []
        return any(d.get("reason") in _RATE_LIMIT_REASONS for d in details)
    return False


class GmailProvider:
    def __init__(
        self,
        service: Any,
        *,
        sleep: Callable[[float], None] = time.sleep,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._service = service
        self._users = service.users()
        self._sleep = sleep
        self._batch_size = batch_size
        self._email: str | None = None

    @classmethod
    def from_credentials(cls, credentials: Any) -> "GmailProvider":
        return cls(build("gmail", "v1", credentials=credentials, cache_discovery=False))

    def get_account_email(self) -> str:
        if self._email is None:
            self._email = self._profile()["emailAddress"]
        return self._email

    def iter_message_ids(self, *, include_spam: bool = True) -> Iterator[str]:
        params: dict[str, Any] = {"userId": "me", "maxResults": 500}
        if include_spam:
            # includeSpamTrash is all-or-nothing, so filter the trash back out.
            params.update(includeSpamTrash=True, q="-in:trash")

        page_token = None
        while True:
            resp = self._execute(self._users.messages().list(**params, pageToken=page_token))
            for item in resp.get("messages", []):
                yield item["id"]
            page_token = resp.get("nextPageToken")
            if not page_token:
                return

    def get_messages(self, ids: Sequence[str]) -> list[MessageMeta]:
        def make_request(msg_id: str) -> Any:
            return self._users.messages().get(
                userId="me", id=msg_id, format="metadata", metadataHeaders=METADATA_HEADERS
            )

        responses = self._batch(ids, make_request)
        return [parse_message(responses[i]) for i in ids if i in responses]

    def get_cursor(self) -> str:
        return str(self._profile()["historyId"])

    def changes_since(self, cursor: str) -> ChangeSet:
        changed: set[str] = set()
        deleted: set[str] = set()
        new_cursor = cursor
        page_token = None

        while True:
            request = self._users.history().list(
                userId="me", startHistoryId=cursor, pageToken=page_token
            )
            try:
                resp = self._execute(request)
            except HttpError as exc:
                if exc.resp.status == 404:
                    raise CursorExpiredError(cursor) from exc
                raise

            for record in resp.get("history", []):
                for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                    for entry in record.get(key, []):
                        changed.add(entry["message"]["id"])
                for entry in record.get("messagesDeleted", []):
                    deleted.add(entry["message"]["id"])

            new_cursor = str(resp.get("historyId", new_cursor))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return ChangeSet(frozenset(changed - deleted), frozenset(deleted), new_cursor)

    def modify_labels(
        self, ids: Sequence[str], *, add: Sequence[str] = (), remove: Sequence[str] = ()
    ) -> None:
        for chunk in batched(ids, MODIFY_CHUNK):
            body = {"ids": list(chunk), "addLabelIds": list(add), "removeLabelIds": list(remove)}
            self._execute(self._users.messages().batchModify(userId="me", body=body))

    def trash(self, ids: Sequence[str]) -> None:
        self._batch(ids, lambda i: self._users.messages().trash(userId="me", id=i))

    def untrash(self, ids: Sequence[str]) -> None:
        self._batch(ids, lambda i: self._users.messages().untrash(userId="me", id=i))

    def _profile(self) -> dict[str, Any]:
        profile: dict[str, Any] = self._execute(self._users.getProfile(userId="me"))
        return profile

    def _execute(self, request: Any) -> Any:
        for attempt in range(MAX_ATTEMPTS):
            try:
                return request.execute()
            except HttpError as exc:
                if not _is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise
                self._backoff(attempt)
        raise AssertionError("unreachable")

    def _batch(
        self, ids: Sequence[str], make_request: Callable[[str], Any]
    ) -> dict[str, dict[str, Any]]:
        """Run one request per id through Gmail's batch endpoint.

        Rate-limited sub-requests are retried with backoff; ids that come back
        404 are left out of the result.
        """
        results: dict[str, dict[str, Any]] = {}
        for chunk in batched(ids, self._batch_size):
            pending = list(chunk)
            for attempt in range(MAX_ATTEMPTS):
                pending = self._batch_once(pending, make_request, results)
                if not pending:
                    break
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(f"Gmail kept rate limiting {len(pending)} requests")
                self._backoff(attempt)
        return results

    def _batch_once(
        self,
        ids: Sequence[str],
        make_request: Callable[[str], Any],
        results: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Send one batch, filling `results`. Returns the ids worth retrying."""
        retry: list[str] = []
        failures: list[HttpError] = []

        def on_response(request_id: str, response: Any, exc: HttpError | None) -> None:
            if exc is None:
                results[request_id] = response
            elif exc.resp.status == 404:
                log.debug("message %s no longer exists", request_id)
            elif _is_retryable(exc):
                retry.append(request_id)
            else:
                failures.append(exc)

        batch = self._service.new_batch_http_request(callback=on_response)
        for msg_id in ids:
            batch.add(make_request(msg_id), request_id=msg_id)
        self._execute(batch)

        if failures:
            raise failures[0]
        return retry

    def _backoff(self, attempt: int) -> None:
        delay = min(2**attempt, 32) + random.uniform(0, 1)
        log.info("Gmail rate limit hit, retrying in %.1fs", delay)
        self._sleep(delay)
