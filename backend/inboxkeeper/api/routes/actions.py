from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session, col, select

from inboxkeeper.actions.executor import ActionError, ActionExecutor
from inboxkeeper.api.context import AppContext, Ctx
from inboxkeeper.api.schemas import (
    ActionBatchOut,
    ActionDetailOut,
    ActionItemOut,
    ActionPreviewOut,
    ActionRequest,
)
from inboxkeeper.db.models import ActionBatch, ActionItem, Proposal

router = APIRouter(prefix="/api/actions")


@contextmanager
def mailbox_change(ctx: AppContext) -> Iterator[ActionExecutor]:
    """Guard for anything that modifies the mailbox: one change at a time, and
    never while a sync is rewriting the cache underneath it."""
    if not ctx.connected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connect an account first.")
    if ctx.sync.status.state == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait for the current sync to finish.")
    if not ctx.action_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "Another action is still running.")
    try:
        yield ActionExecutor(ctx.provider_factory(), ctx.engine)
    except ActionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        ctx.action_lock.release()


@router.post("/preview")
def preview_action(ctx: Ctx, body: ActionRequest) -> ActionPreviewOut:
    if not ctx.connected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connect an account first.")
    executor = ActionExecutor(ctx.provider_factory(), ctx.engine)
    try:
        plan = executor.preview(body.kind, body.message_ids, body.confirmed)
    except ActionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ActionPreviewOut.from_plan(plan)


@router.post("", status_code=status.HTTP_201_CREATED)
def apply_action(ctx: Ctx, body: ActionRequest) -> ActionBatchOut:
    with mailbox_change(ctx) as executor:
        batch = executor.apply(body.kind, body.message_ids, body.confirmed)
    return ActionBatchOut.from_batch(batch)


@router.get("")
def list_actions(ctx: Ctx, limit: int = 20) -> list[ActionBatchOut]:
    with Session(ctx.engine) as session:
        batches = session.exec(
            select(ActionBatch).order_by(col(ActionBatch.id).desc()).limit(limit)
        ).all()
    return [ActionBatchOut.from_batch(b) for b in batches]


@router.get("/{batch_id}")
def get_action(ctx: Ctx, batch_id: int) -> ActionDetailOut:
    with Session(ctx.engine) as session:
        batch = session.get(ActionBatch, batch_id)
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such action.")
        items = session.exec(
            select(ActionItem).where(ActionItem.batch_id == batch_id).order_by(col(ActionItem.id))
        ).all()
    return ActionDetailOut(
        **ActionBatchOut.from_batch(batch).model_dump(),
        items=[ActionItemOut.model_validate(i, from_attributes=True) for i in items],
    )


@router.post("/{batch_id}/undo")
def undo_action(ctx: Ctx, batch_id: int) -> ActionBatchOut:
    with mailbox_change(ctx) as executor:
        try:
            batch = executor.undo(batch_id)
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such action.") from exc

    # A proposal the user applied goes back up for review once it's undone.
    with Session(ctx.engine) as session:
        for proposal in session.exec(select(Proposal).where(Proposal.batch_id == batch_id)):
            proposal.status = "pending"
            proposal.batch_id = None
            session.add(proposal)
        session.commit()
    return ActionBatchOut.from_batch(batch)
