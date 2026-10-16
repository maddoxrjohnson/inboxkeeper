import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlmodel import Session, delete, func, select

from inboxkeeper.api.context import Ctx
from inboxkeeper.api.schemas import AccountOut
from inboxkeeper.auth.google import AuthError
from inboxkeeper.db.models import Message, SyncState

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/account")
def get_account(ctx: Ctx) -> AccountOut:
    with Session(ctx.engine) as session:
        message_count = session.exec(select(func.count()).select_from(Message)).one()
        state = session.exec(select(SyncState)).first()
    return AccountOut(
        connected=ctx.connected,
        email=ctx.account_email(),
        has_client_secrets=ctx.auth.has_client_secrets(),
        last_synced_at=state.last_synced_at if state else None,
        message_count=message_count,
    )


@router.get("/api/auth/google/start")
def start_google_auth(ctx: Ctx) -> RedirectResponse:
    try:
        url = ctx.auth.start(ctx.settings.oauth_redirect_uri)
    except AuthError as exc:
        return _back_to_frontend(ctx, auth_error=str(exc))
    return RedirectResponse(url)


@router.get("/", include_in_schema=False)
def oauth_callback(
    ctx: Ctx, code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    """Google's redirect target. Anything else hitting / is sent to the UI."""
    if error:
        message = "Sign-in was cancelled." if error == "access_denied" else f"Google said: {error}"
        return _back_to_frontend(ctx, auth_error=message)
    if not (code and state):
        return _back_to_frontend(ctx)

    try:
        ctx.auth.finish(state, code)
    except AuthError as exc:
        return _back_to_frontend(ctx, auth_error=str(exc))
    except Exception:
        log.exception("token exchange failed")
        return _back_to_frontend(ctx, auth_error="Couldn't finish signing in. Please try again.")

    ctx.forget_account()
    return _back_to_frontend(ctx, connected="1")


@router.post("/api/auth/disconnect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(ctx: Ctx) -> None:
    if ctx.sync.status.state == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait for the current sync to finish.")
    ctx.auth.disconnect()
    ctx.forget_account()
    # Disconnecting also forgets the cached headers; nothing about the mailbox
    # should linger on disk once the user has cut access.
    with Session(ctx.engine) as session:
        session.exec(delete(Message))
        session.exec(delete(SyncState))
        session.commit()


def _back_to_frontend(ctx: Ctx, **params: str) -> RedirectResponse:
    url = ctx.settings.frontend_url
    if params:
        url = f"{url}/?{urlencode(params)}"
    return RedirectResponse(url)
