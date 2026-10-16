from datetime import UTC, datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from inboxkeeper.db.types import UTCDateTime
from inboxkeeper.mail.headers import AuthResults, UnsubscribeInfo, domain_of
from inboxkeeper.providers.base import MessageMeta


def utcnow() -> datetime:
    return datetime.now(UTC)


class Message(SQLModel, table=True):
    """Cached metadata for one message. Bodies are never stored."""

    id: str = Field(primary_key=True)
    thread_id: str = Field(index=True)
    received_at: datetime = Field(sa_type=UTCDateTime, index=True)
    labels: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    size_estimate: int = 0
    sender_name: str = ""
    sender_email: str = Field(default="", index=True)
    sender_domain: str = Field(default="", index=True)
    recipients: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    subject: str = ""
    snippet: str = ""
    list_id: str | None = Field(default=None, index=True)
    unsubscribe_http: str | None = None
    unsubscribe_mailto: str | None = None
    unsubscribe_one_click: bool = False
    spf: str | None = None
    dkim: str | None = None
    dmarc: str | None = None
    mime_type: str = ""
    synced_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)

    @classmethod
    def from_meta(cls, meta: MessageMeta) -> "Message":
        unsub = meta.unsubscribe or UnsubscribeInfo()
        return cls(
            id=meta.id,
            thread_id=meta.thread_id,
            received_at=meta.received_at,
            labels=sorted(meta.labels),
            size_estimate=meta.size_estimate,
            sender_name=meta.sender_name,
            sender_email=meta.sender_email,
            sender_domain=domain_of(meta.sender_email),
            recipients=list(meta.recipients),
            subject=meta.subject,
            snippet=meta.snippet,
            list_id=meta.list_id,
            unsubscribe_http=unsub.http_url,
            unsubscribe_mailto=unsub.mailto,
            unsubscribe_one_click=unsub.one_click,
            spf=meta.auth.spf,
            dkim=meta.auth.dkim,
            dmarc=meta.auth.dmarc,
            mime_type=meta.mime_type,
        )

    @property
    def auth(self) -> AuthResults:
        return AuthResults(spf=self.spf, dkim=self.dkim, dmarc=self.dmarc)


class SyncState(SQLModel, table=True):
    account: str = Field(primary_key=True)
    cursor: str | None = None
    # False while the first full sync is still in progress, so an interrupted
    # sync can pick up where it left off instead of refetching everything.
    full_sync_complete: bool = False
    last_synced_at: datetime | None = Field(default=None, sa_type=UTCDateTime)


class ActionBatch(SQLModel, table=True):
    """One user-approved action and its outcome. The basis for undo."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str
    status: str = "pending"  # pending -> applied | failed, then possibly undone
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, index=True)
    undone_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    applied_count: int = 0
    skipped_count: int = 0
    total_size: int = 0
    error: str | None = None


class ActionItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="actionbatch.id", index=True, ondelete="CASCADE")
    message_id: str
    # Labels before the action ran, so undo can put back exactly what was there.
    prev_labels: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    sender_email: str = ""
    subject: str = ""
    size_estimate: int = 0
    skipped_reason: str | None = None


class Proposal(SQLModel, table=True):
    """A suggested action from a scanner, waiting for the user to review it."""

    __table_args__ = (UniqueConstraint("scanner", "key"),)

    id: int | None = Field(default=None, primary_key=True)
    scanner: str = Field(index=True)
    # Identifies the group within its scanner (a sender, a list), so a rescan
    # updates the same proposal and remembers if the user dismissed it.
    key: str
    kind: str
    title: str
    reason: str
    message_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Matching mail that the protection rules held back.
    protected_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    total_size: int = 0
    status: str = "pending"  # pending | applied | dismissed
    batch_id: int | None = Field(default=None, foreign_key="actionbatch.id", ondelete="SET NULL")
    updated_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime)
