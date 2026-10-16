from sqlmodel import Session, func, select

from inboxkeeper.db.models import ActionBatch, ActionItem, Message, SyncState
from inboxkeeper.db.queries import clear_mailbox_data, has_label
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


def test_clear_mailbox_data() -> None:
    engine = create_db_engine(None)
    with Session(engine) as session:
        session.add(Message.from_meta(make_message()))
        session.add(SyncState(account="old@example.com"))
        session.add(SyncState(account="new@example.com"))
        batch = ActionBatch(kind="archive")
        session.add(batch)
        session.flush()
        assert batch.id is not None
        session.add(ActionItem(batch_id=batch.id, message_id="m1"))
        session.commit()

        clear_mailbox_data(session, keep_account="new@example.com")
        session.commit()

        assert session.exec(select(Message)).all() == []
        assert session.exec(select(ActionBatch)).all() == []
        assert session.exec(select(ActionItem)).all() == []
        assert [s.account for s in session.exec(select(SyncState))] == ["new@example.com"]

        clear_mailbox_data(session)
        session.commit()
        assert session.exec(select(SyncState)).all() == []
