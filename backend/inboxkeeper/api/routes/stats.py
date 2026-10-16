from fastapi import APIRouter
from sqlmodel import Session, col, func, select

from inboxkeeper.api.context import Ctx
from inboxkeeper.api.schemas import SenderStat, StatsOut
from inboxkeeper.db.models import Message
from inboxkeeper.db.queries import has_label
from inboxkeeper.providers.base import INBOX, SPAM, UNREAD

router = APIRouter(prefix="/api/stats")


@router.get("")
def get_stats(ctx: Ctx, top: int = 10) -> StatsOut:
    with Session(ctx.engine) as session:

        def count(*conditions: object) -> int:
            query = select(func.count()).select_from(Message)
            return session.exec(query.where(*conditions)).one()  # type: ignore[arg-type]

        total_size = session.exec(select(func.coalesce(func.sum(Message.size_estimate), 0))).one()
        senders = session.exec(
            select(
                Message.sender_email,
                func.max(Message.sender_name),
                func.count(),
                func.sum(Message.size_estimate),
            )
            .where(~has_label(SPAM), col(Message.sender_email) != "")
            .group_by(Message.sender_email)
            .order_by(func.count().desc())
            .limit(top)
        ).all()

        return StatsOut(
            total=count(),
            inbox=count(has_label(INBOX)),
            inbox_unread=count(has_label(INBOX), has_label(UNREAD)),
            spam=count(has_label(SPAM)),
            total_size=total_size,
            top_senders=[
                SenderStat(email=email, name=name or "", count=n, total_size=size or 0)
                for email, name, n, size in senders
            ],
        )
