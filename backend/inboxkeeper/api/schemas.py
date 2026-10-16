from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from inboxkeeper.actions.executor import ActionPlan, can_undo
from inboxkeeper.actions.kinds import ActionKind
from inboxkeeper.db.models import ActionBatch, Proposal
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


class ActionRequest(BaseModel):
    kind: ActionKind
    message_ids: list[str] = Field(min_length=1)
    # Protected messages the user has individually agreed to include.
    confirmed: list[str] = []


class SkippedOut(BaseModel):
    message_id: str
    reason: str
    protected: bool
    sender_email: str | None
    subject: str | None


class ActionPreviewOut(BaseModel):
    kind: ActionKind
    count: int
    total_size: int
    skipped: list[SkippedOut]

    @classmethod
    def from_plan(cls, plan: ActionPlan) -> "ActionPreviewOut":
        return cls(
            kind=plan.kind,
            count=len(plan.to_apply),
            total_size=plan.total_size,
            skipped=[
                SkippedOut(
                    message_id=s.message_id,
                    reason=s.reason,
                    protected=s.protected,
                    sender_email=s.candidate.sender_email if s.candidate else None,
                    subject=s.candidate.subject if s.candidate else None,
                )
                for s in plan.skipped
            ],
        )


class ActionBatchOut(BaseModel):
    id: int
    kind: ActionKind
    status: str
    created_at: datetime
    undone_at: datetime | None
    applied_count: int
    skipped_count: int
    total_size: int
    error: str | None
    can_undo: bool

    @classmethod
    def from_batch(cls, batch: ActionBatch) -> "ActionBatchOut":
        assert batch.id is not None
        return cls(
            id=batch.id,
            kind=ActionKind(batch.kind),
            status=batch.status,
            created_at=batch.created_at,
            undone_at=batch.undone_at,
            applied_count=batch.applied_count,
            skipped_count=batch.skipped_count,
            total_size=batch.total_size,
            error=batch.error,
            can_undo=can_undo(batch),
        )


class ActionItemOut(BaseModel):
    message_id: str
    sender_email: str
    subject: str
    size_estimate: int
    skipped_reason: str | None


class ActionDetailOut(ActionBatchOut):
    items: list[ActionItemOut]


class ProposalOut(BaseModel):
    id: int
    scanner: str
    kind: ActionKind
    title: str
    reason: str
    message_count: int
    protected_count: int
    total_size: int
    status: str
    batch_id: int | None
    updated_at: datetime

    @classmethod
    def from_proposal(cls, p: Proposal) -> "ProposalOut":
        assert p.id is not None
        return cls(
            id=p.id,
            scanner=p.scanner,
            kind=ActionKind(p.kind),
            title=p.title,
            reason=p.reason,
            message_count=len(p.message_ids),
            protected_count=len(p.protected_ids),
            total_size=p.total_size,
            status=p.status,
            batch_id=p.batch_id,
            updated_at=p.updated_at,
        )


class ApplyProposalRequest(BaseModel):
    # Messages the user unticked while reviewing the group.
    exclude: list[str] = []
    confirmed: list[str] = []
