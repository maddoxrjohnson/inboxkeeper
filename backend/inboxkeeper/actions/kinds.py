from dataclasses import dataclass
from enum import StrEnum

from inboxkeeper.providers.base import INBOX, SPAM, TRASH, UNREAD


class ActionKind(StrEnum):
    ARCHIVE = "archive"
    TRASH = "trash"
    MARK_READ = "mark_read"
    NOT_SPAM = "not_spam"


@dataclass(frozen=True, slots=True)
class LabelChange:
    add: frozenset[str] = frozenset()
    remove: frozenset[str] = frozenset()
    # Whether protected mail needs individual confirmation. Moving something
    # out of spam can't hide or lose it, so that one doesn't.
    guarded: bool = True

    def would_change(self, labels: frozenset[str]) -> bool:
        return bool(self.add - labels or self.remove & labels)

    def apply_to(self, labels: frozenset[str]) -> frozenset[str]:
        return (labels | self.add) - self.remove


CHANGES = {
    ActionKind.ARCHIVE: LabelChange(remove=frozenset({INBOX})),
    ActionKind.TRASH: LabelChange(add=frozenset({TRASH})),
    ActionKind.MARK_READ: LabelChange(remove=frozenset({UNREAD})),
    ActionKind.NOT_SPAM: LabelChange(
        add=frozenset({INBOX}), remove=frozenset({SPAM}), guarded=False
    ),
}
