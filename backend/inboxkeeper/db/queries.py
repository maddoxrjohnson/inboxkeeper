from sqlalchemy import ColumnElement, exists, func, select

from inboxkeeper.db.models import Message


def has_label(label: str) -> ColumnElement[bool]:
    """SQL condition: the message carries `label` (labels are a JSON array)."""
    labels = func.json_each(Message.labels).table_valued("value")
    return exists(select(1).select_from(labels).where(labels.c.value == label))
