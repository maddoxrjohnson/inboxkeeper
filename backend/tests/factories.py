from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

from inboxkeeper.mail.headers import domain_of
from inboxkeeper.providers.base import INBOX, MessageMeta

_ids = count(1)
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def make_message(**overrides: Any) -> MessageMeta:
    n = next(_ids)
    sender = overrides.pop("sender_email", f"sender{n}@example.com")
    fields: dict[str, Any] = {
        "id": f"m{n}",
        "thread_id": f"t{n}",
        "received_at": BASE_TIME + timedelta(hours=n),
        "labels": frozenset({INBOX}),
        "size_estimate": 2_000,
        "sender_name": domain_of(sender).split(".")[0].title(),
        "sender_email": sender,
        "recipients": ("me@example.com",),
        "subject": f"Message {n}",
        "snippet": "",
    }
    fields.update(overrides)
    if isinstance(fields["labels"], set):
        fields["labels"] = frozenset(fields["labels"])
    return MessageMeta(**fields)
