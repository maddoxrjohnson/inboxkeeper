from sqlmodel import Session, func, select

from inboxkeeper.db.models import Message
from inboxkeeper.db.queries import has_label
from inboxkeeper.db.session import create_db_engine
from tests.factories import make_message


def test_has_label() -> None:
    engine = create_db_engine(None)
    inbox_unread = make_message(labels={"INBOX", "UNREAD"})
    inbox = make_message(labels={"INBOX"})
    spam = make_message(labels={"SPAM", "UNREAD"})
    with Session(engine) as session:
        for m in (inbox_unread, inbox, spam):
            session.add(Message.from_meta(m))
        session.commit()

        def ids(*conds: object) -> set[str]:
            return set(session.exec(select(Message.id).where(*conds)).all())  # type: ignore[arg-type]

        assert ids(has_label("INBOX")) == {inbox_unread.id, inbox.id}
        assert ids(has_label("UNREAD")) == {inbox_unread.id, spam.id}
        assert ids(has_label("INBOX"), has_label("UNREAD")) == {inbox_unread.id}
        assert ids(~has_label("UNREAD")) == {inbox.id}
        count = session.exec(
            select(func.count()).select_from(Message).where(has_label("SPAM"))
        ).one()
        assert count == 1
