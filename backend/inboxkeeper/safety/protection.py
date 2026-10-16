"""Rules for mail that bulk actions must leave alone.

A protected message can still be acted on, but only when the user confirms that
specific message. Scanners use these rules to keep protected mail out of their
suggestions, and the executor checks them again against fresh labels right
before touching anything.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from sqlmodel import Session, select

from inboxkeeper.db.models import Message
from inboxkeeper.db.queries import has_label
from inboxkeeper.providers.base import IMPORTANT, SENT, STARRED

SENSITIVE_TERMS = [
    r"receipts?",
    r"invoices?",
    r"order (?:confirmation|confirmed)",
    r"tax(?:es)?",
    r"w-?2",
    r"1099",
    r"bank(?:ing)?",
    r"statements?",
    r"payroll",
    r"pay ?stubs?",
    r"passwords?",
    r"verification code",
    r"security (?:alert|code)",
    r"2fa",
    r"two-factor",
    r"legal",
    r"contracts?",
    r"lease",
    r"insurance",
    r"medical",
    r"prescriptions?",
    r"appointments?",
    r"tickets?",
    r"itinerary",
    r"boarding pass",
]
_SENSITIVE = re.compile(r"\b(?:" + "|".join(SENSITIVE_TERMS) + r")\b", re.IGNORECASE)


class MessageLike(Protocol):
    @property
    def labels(self) -> Collection[str]: ...
    @property
    def sender_email(self) -> str: ...
    @property
    def subject(self) -> str: ...
    @property
    def snippet(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ProtectionPolicy:
    starred: bool = True
    important: bool = True
    correspondents: bool = True
    sensitive_terms: bool = True

    def reasons(self, msg: MessageLike, correspondents: Collection[str] = ()) -> list[str]:
        """Why `msg` is protected. An empty list means it isn't."""
        found: list[str] = []
        if SENT in msg.labels:
            found.append("Sent by you")
        if self.starred and STARRED in msg.labels:
            found.append("Starred")
        if self.important and IMPORTANT in msg.labels:
            found.append("Marked important")
        if self.correspondents and msg.sender_email in correspondents:
            found.append("From someone you've emailed")
        if self.sensitive_terms:
            match = _SENSITIVE.search(f"{msg.subject}\n{msg.snippet}")
            if match:
                found.append(f'Mentions "{match.group(0).lower()}"')
        return found


def load_correspondents(session: Session) -> set[str]:
    """Every address the user has sent mail to, according to the cache."""
    rows = session.exec(select(Message.recipients).where(has_label(SENT)))
    return {addr for recipients in rows for addr in recipients}
