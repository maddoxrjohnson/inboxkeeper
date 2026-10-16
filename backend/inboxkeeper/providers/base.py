"""The interface every mailbox backend implements.

Label names follow Gmail's system labels (INBOX, SPAM, UNREAD, STARRED, ...).
Other providers are expected to map their own folders and flags onto these so
scanners and safety rules only have to understand one vocabulary.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from inboxkeeper.mail.headers import AuthResults, UnsubscribeInfo

INBOX = "INBOX"
SPAM = "SPAM"
TRASH = "TRASH"
UNREAD = "UNREAD"
STARRED = "STARRED"
IMPORTANT = "IMPORTANT"
SENT = "SENT"
CATEGORY_PROMOTIONS = "CATEGORY_PROMOTIONS"
CATEGORY_SOCIAL = "CATEGORY_SOCIAL"
CATEGORY_UPDATES = "CATEGORY_UPDATES"
CATEGORY_FORUMS = "CATEGORY_FORUMS"


@dataclass(frozen=True, slots=True)
class MessageMeta:
    id: str
    thread_id: str
    received_at: datetime
    labels: frozenset[str] = frozenset()
    size_estimate: int = 0
    sender_name: str = ""
    sender_email: str = ""
    recipients: tuple[str, ...] = ()
    subject: str = ""
    snippet: str = ""
    list_id: str | None = None
    unsubscribe: UnsubscribeInfo | None = None
    auth: AuthResults = field(default_factory=AuthResults)
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class ChangeSet:
    changed: frozenset[str]
    deleted: frozenset[str]
    cursor: str


class CursorExpiredError(Exception):
    """The provider no longer remembers changes that far back; a full sync is needed."""


class MailProvider(Protocol):
    def get_account_email(self) -> str: ...

    def iter_message_ids(self, *, include_spam: bool = True) -> Iterator[str]:
        """Yield every message id outside the trash, newest first."""
        ...

    def get_messages(self, ids: Sequence[str]) -> list[MessageMeta]:
        """Fetch metadata for the given ids. Ids that no longer exist are skipped."""
        ...

    def get_cursor(self) -> str:
        """An opaque marker for "now", to pass to changes_since later."""
        ...

    def changes_since(self, cursor: str) -> ChangeSet: ...

    def modify_labels(
        self, ids: Sequence[str], *, add: Sequence[str] = (), remove: Sequence[str] = ()
    ) -> None: ...

    def trash(self, ids: Sequence[str]) -> None: ...

    def untrash(self, ids: Sequence[str]) -> None: ...
