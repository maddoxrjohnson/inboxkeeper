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

# Every call inside a batch counts toward Gmail's per-user concurrency cap,
# which rejects anything past roughly 20 at once with "Too many concurrent
# requests for user". 10 leaves headroom; the size shrinks further if Gmail
# still pushes back.
BATCH_SIZE = 10
MIN_BATCH_SIZE = 5
MODIFY_CHUNK = 1000
# Enough attempts that backoff (1, 2, 4 ... capped at 60s) outlasts Gmail's
# per-minute quota window, which is what usually trips after a burst.
MAX_ATTEMPTS = 8
MAX_BACKOFF = 60

# The real per-user quota depends on the Google Cloud project: Gmail documents
# 15,000 units a minute, but new projects have been seen throttling at a fifth
# of that. So the send rate adapts: halve on a quota error, creep back up after
# each clean batch, and settle just under whatever the project allows.
QUOTA_UNITS_PER_SECOND = 100
MIN_QUOTA_PER_SECOND = 10
QUOTA_RECOVERY_STEP = 2
GET_COST = 5
TRASH_COST = 5

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


def _is_concurrency_limit(exc: HttpError) -> bool:
    return exc.resp.status == 429 and "concurrent" in str(exc.reason).lower()


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
        clock: Callable[[], float] = time.monotonic,
        batch_size: int = BATCH_SIZE,
        quota_per_second: float | None = QUOTA_UNITS_PER_SECOND,
    ) -> None:
        self._service = service
        self._users = service.users()
        self._sleep = sleep
        self._clock = clock
        self._batch_size = batch_size
        self._max_rate = quota_per_second
        self._rate = quota_per_second
        self._next_send = 0.0
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

        responses = self._batch(ids, make_request, cost=GET_COST)
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
        self._batch(ids, lambda i: self._users.messages().trash(userId="me", id=i), cost=TRASH_COST)

    def untrash(self, ids: Sequence[str]) -> None:
        self._batch(
            ids, lambda i: self._users.messages().untrash(userId="me", id=i), cost=TRASH_COST
        )

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
        self, ids: Sequence[str], make_request: Callable[[str], Any], *, cost: int
    ) -> dict[str, dict[str, Any]]:
        """Run one request per id through Gmail's batch endpoint.

        Rate-limited sub-requests are requeued in smaller batches after a
        backoff; ids that come back 404 are left out of the result.
        """
        results: dict[str, dict[str, Any]] = {}
        queue = list(ids)
        failed_attempts = 0
        while queue:
            chunk, queue = queue[: self._batch_size], queue[self._batch_size :]
            self._pace(cost * len(chunk))
            retry, errors = self._batch_once(chunk, make_request, results)
            if not retry:
                failed_attempts = 0
                self._adjust_rate(throttled=False)
                continue

            failed_attempts += 1
            if failed_attempts >= MAX_ATTEMPTS:
                raise RuntimeError(f"Gmail kept rate limiting {len(retry)} requests")
            if any(_is_concurrency_limit(e) for e in errors):
                # Resending the rejected calls as one batch would hit the same
                # cap again, so use smaller batches from here on.
                self._batch_size = max(MIN_BATCH_SIZE, self._batch_size // 2)
            else:
                self._adjust_rate(throttled=True)
            queue = retry + queue
            self._backoff(failed_attempts - 1)
        return results

    def _adjust_rate(self, *, throttled: bool) -> None:
        if self._rate is None or self._max_rate is None:
            return
        if throttled:
            self._rate = max(MIN_QUOTA_PER_SECOND, self._rate / 2)
            log.info("quota exceeded, slowing to %.0f units/s", self._rate)
        else:
            self._rate = min(self._max_rate, self._rate + QUOTA_RECOVERY_STEP)

    def _pace(self, units: int) -> None:
        """Space out requests so we stay under the current send rate."""
        if self._rate is None:
            return
        now = self._clock()
        if self._next_send > now:
            self._sleep(self._next_send - now)
            now = self._next_send
        self._next_send = now + units / self._rate

    def _batch_once(
        self,
        ids: Sequence[str],
        make_request: Callable[[str], Any],
        results: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[HttpError]]:
        """Send one batch, filling `results`.

        Returns the ids worth retrying along with the errors that caused it.
        """
        retry: list[str] = []
        retry_errors: list[HttpError] = []
        failures: list[HttpError] = []

        def on_response(request_id: str, response: Any, exc: HttpError | None) -> None:
            if exc is None:
                results[request_id] = response
            elif exc.resp.status == 404:
                log.debug("message %s no longer exists", request_id)
            elif _is_retryable(exc):
                retry.append(request_id)
                retry_errors.append(exc)
            else:
                failures.append(exc)

        batch = self._service.new_batch_http_request(callback=on_response)
        for msg_id in ids:
            batch.add(make_request(msg_id), request_id=msg_id)
        self._execute(batch)

        if failures:
            raise failures[0]
        return retry, retry_errors

    def _backoff(self, attempt: int) -> None:
        delay = min(2**attempt, MAX_BACKOFF) + random.uniform(0, 1)
        log.info("Gmail rate limit hit, retrying in %.1fs", delay)
        self._sleep(delay)
