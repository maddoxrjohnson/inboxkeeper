from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from inboxkeeper.sync import SyncStatus


class AccountOut(BaseModel):
    connected: bool
    email: str | None
    has_client_secrets: bool
    client_secrets_path: str
    last_synced_at: datetime | None
    message_count: int


class SyncRequest(BaseModel):
    full: bool = False
    limit: int | None = Field(default=None, ge=1)


class SyncStatusOut(BaseModel):
    state: Literal["idle", "running", "done", "error"]
    processed: int
    total: int
    mode: str | None
    fetched: int | None
    removed: int | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_status(cls, status: SyncStatus) -> "SyncStatusOut":
        result = status.result
        return cls(
            state=status.state,
            processed=status.processed,
            total=status.total,
            mode=result.mode if result else None,
            fetched=result.fetched if result else None,
            removed=result.removed if result else None,
            error=status.error,
            started_at=status.started_at,
            finished_at=status.finished_at,
        )


class SenderStat(BaseModel):
    email: str
    name: str
    count: int
    total_size: int


class StatsOut(BaseModel):
    total: int
    inbox: int
    inbox_unread: int
    spam: int
    total_size: int
    top_senders: list[SenderStat]
