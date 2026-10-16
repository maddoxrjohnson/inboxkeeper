from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from inboxkeeper.db.models import Message
from inboxkeeper.db.session import create_db_engine
from inboxkeeper.mail.headers import AuthResults, UnsubscribeInfo
from tests.factories import make_message


@pytest.fixture
def engine() -> Engine:
    return create_db_engine(None)


def test_message_round_trip(engine: Engine) -> None:
    meta = make_message(
        sender_email="news@shop.example.com",
        unsubscribe=UnsubscribeInfo(http_url="https://shop.example.com/u", one_click=True),
        auth=AuthResults(spf="pass", dkim="pass", dmarc="fail"),
        list_id="<weekly.shop.example.com>",
    )
    with Session(engine) as session:
        session.add(Message.from_meta(meta))
        session.commit()

    with Session(engine) as session:
        stored = session.get(Message, meta.id)
        assert stored is not None
        assert stored.sender_domain == "shop.example.com"
        assert stored.labels == ["INBOX"]
        assert stored.unsubscribe_one_click
        assert stored.auth == AuthResults(spf="pass", dkim="pass", dmarc="fail")
        assert stored.received_at == meta.received_at
        assert stored.received_at.tzinfo is not None


def test_datetimes_are_normalised_to_utc(engine: Engine) -> None:
    eastern = timezone(timedelta(hours=-5))
    meta = make_message(received_at=datetime(2026, 3, 1, 9, 0, tzinfo=eastern))
    with Session(engine) as session:
        session.add(Message.from_meta(meta))
        session.commit()

    with Session(engine) as session:
        stored = session.get(Message, meta.id)
        assert stored is not None
        assert stored.received_at.hour == 14
        assert stored.received_at == meta.received_at


def test_naive_datetimes_are_rejected(engine: Engine) -> None:
    msg = Message.from_meta(make_message())
    msg.received_at = datetime(2026, 1, 1)
    with Session(engine) as session:
        session.add(msg)
        with pytest.raises(Exception, match="naive"):
            session.commit()
