from fastapi import APIRouter, HTTPException, status

from inboxkeeper.api.context import Ctx
from inboxkeeper.api.schemas import SyncRequest, SyncStatusOut
from inboxkeeper.sync import SyncAlreadyRunningError

router = APIRouter(prefix="/api/sync")


@router.get("")
def get_sync_status(ctx: Ctx) -> SyncStatusOut:
    return SyncStatusOut.from_status(ctx.sync.status)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_sync(ctx: Ctx, body: SyncRequest | None = None) -> SyncStatusOut:
    body = body or SyncRequest()
    if not ctx.connected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connect an account first.")
    try:
        sync_status = ctx.sync.start(force_full=body.full, limit=body.limit)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already running.") from exc
    return SyncStatusOut.from_status(sync_status)
