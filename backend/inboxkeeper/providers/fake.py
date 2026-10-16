"""In-memory provider used by the test suite and for demoing the UI offline."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace

from inboxkeeper.providers.base import SPAM, TRASH, ChangeSet, CursorExpiredError, MessageMeta


class FakeProvider:
    def __init__(self, messages: Iterable[MessageMeta] = (), email: str = "me@example.com") -> None:
        self.email = email
        self._messages = {m.id: m for m in messages}
        # Each entry is (message id, deleted?). The cursor is an index into this log.
        self._log: list[tuple[str, bool]] = []
        self._log_start = 0
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def get_account_email(self) -> str:
        return self.email

    def iter_message_ids(self, *, include_spam: bool = True) -> Iterator[str]:
        newest_first = sorted(self._messages.values(), key=lambda m: m.received_at, reverse=True)
        for msg in newest_first:
            if TRASH in msg.labels or (SPAM in msg.labels and not include_spam):
                continue
            yield msg.id

    def get_messages(self, ids: Sequence[str]) -> list[MessageMeta]:
        self.calls.append(("get_messages", tuple(ids)))
        return [self._messages[i] for i in ids if i in self._messages]

    def get_cursor(self) -> str:
        return str(self._log_start + len(self._log))

    def changes_since(self, cursor: str) -> ChangeSet:
        pos = int(cursor)
        if pos < self._log_start:
            raise CursorExpiredError(cursor)

        changed: set[str] = set()
        deleted: set[str] = set()
        for msg_id, was_deleted in self._log[pos - self._log_start :]:
            if was_deleted:
                deleted.add(msg_id)
                changed.discard(msg_id)
            else:
                changed.add(msg_id)
                deleted.discard(msg_id)
        return ChangeSet(frozenset(changed), frozenset(deleted), self.get_cursor())

    def modify_labels(
        self, ids: Sequence[str], *, add: Sequence[str] = (), remove: Sequence[str] = ()
    ) -> None:
        self.calls.append(("modify_labels", tuple(ids)))
        for msg_id in ids:
            msg = self._messages[msg_id]
            self._update(replace(msg, labels=(msg.labels | set(add)) - set(remove)))

    def trash(self, ids: Sequence[str]) -> None:
        self.calls.append(("trash", tuple(ids)))
        self.modify_labels(ids, add=[TRASH])

    def untrash(self, ids: Sequence[str]) -> None:
        self.calls.append(("untrash", tuple(ids)))
        self.modify_labels(ids, remove=[TRASH])

    # Test helpers for simulating activity that happens outside the app.

    def deliver(self, msg: MessageMeta) -> None:
        self._update(msg)

    def delete_forever(self, msg_id: str) -> None:
        del self._messages[msg_id]
        self._log.append((msg_id, True))

    def expire_history(self) -> None:
        self._log_start += len(self._log)
        self._log.clear()

    def _update(self, msg: MessageMeta) -> None:
        self._messages[msg.id] = msg
        self._log.append((msg.id, False))
