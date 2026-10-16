from sqlalchemy import ColumnElement, exists, func, select
from sqlmodel import Session, col, delete

from inboxkeeper.db.models import ActionBatch, ActionItem, Message, SyncState


def has_label(label: str) -> ColumnElement[bool]:
    """SQL condition: the message carries `label` (labels are a JSON array)."""
    labels = func.json_each(Message.labels).table_valued("value")
    return exists(select(1).select_from(labels).where(labels.c.value == label))


def clear_mailbox_data(session: Session, *, keep_account: str | None = None) -> None:
    """Delete everything stored about the mailbox: cached headers, sync state
    and the action log. `keep_account` keeps that account's sync state."""
    session.exec(delete(ActionItem))
    session.exec(delete(ActionBatch))
    session.exec(delete(Message))
    session.exec(delete(SyncState).where(col(SyncState.account) != keep_account))
