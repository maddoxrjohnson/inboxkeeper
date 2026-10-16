from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from inboxkeeper.actions.executor import ActionError, ActionExecutor
from inboxkeeper.actions.kinds import ActionKind
from inboxkeeper.db.models import ActionBatch, ActionItem, Message
from inboxkeeper.db.session import create_db_engine
from inboxkeeper.providers.base import INBOX, SENT, SPAM, STARRED, TRASH, UNREAD, MessageMeta
from inboxkeeper.providers.fake import FakeProvider
from inboxkeeper.sync import MailboxSync
from tests.factories import make_message


@pytest.fixture
def engine() -> Engine:
    return create_db_engine(None)


def setup(engine: Engine, *msgs: MessageMeta) -> tuple[FakeProvider, ActionExecutor]:
    provider = FakeProvider(msgs)
    MailboxSync(provider, engine).run()
    provider.calls.clear()
    return provider, ActionExecutor(provider, engine)


def labels(provider: FakeProvider, msg_id: str) -> frozenset[str]:
    return provider.get_messages([msg_id])[0].labels


def cached(engine: Engine) -> dict[str, Message]:
    with Session(engine) as session:
        return {m.id: m for m in session.exec(select(Message)).all()}


def items(engine: Engine, batch_id: int | None) -> list[ActionItem]:
    with Session(engine) as session:
        return list(session.exec(select(ActionItem).where(ActionItem.batch_id == batch_id)))


def test_archive_removes_inbox_and_logs_previous_labels(engine: Engine) -> None:
    msg = make_message(labels={INBOX, UNREAD})
    provider, executor = setup(engine, msg)

    batch = executor.apply(ActionKind.ARCHIVE, [msg.id])

    assert batch.status == "applied"
    assert batch.applied_count == 1
    assert labels(provider, msg.id) == {UNREAD}
    assert cached(engine)[msg.id].labels == [UNREAD]
    [item] = items(engine, batch.id)
    assert item.prev_labels == [INBOX, UNREAD]
    assert item.skipped_reason is None


def test_undo_archive_restores_inbox(engine: Engine) -> None:
    msg = make_message(labels={INBOX})
    provider, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.ARCHIVE, [msg.id])
    assert batch.id is not None

    undone = executor.undo(batch.id)

    assert undone.status == "undone"
    assert undone.undone_at is not None
    assert labels(provider, msg.id) == {INBOX}
    assert cached(engine)[msg.id].labels == [INBOX]


def test_undo_only_reverses_what_changed(engine: Engine) -> None:
    unread, read = make_message(labels={INBOX, UNREAD}), make_message(labels={INBOX})
    provider, executor = setup(engine, unread, read)
    # `read` is already read, so it's skipped and undo must not mark it unread.
    batch = executor.apply(ActionKind.MARK_READ, [unread.id, read.id])
    assert batch.id is not None
    executor.undo(batch.id)

    assert labels(provider, unread.id) == {INBOX, UNREAD}
    assert labels(provider, read.id) == {INBOX}


def test_trash_and_undo(engine: Engine) -> None:
    msg = make_message(labels={INBOX, UNREAD})
    provider, executor = setup(engine, msg)

    batch = executor.apply(ActionKind.TRASH, [msg.id])
    assert batch.id is not None
    assert TRASH in labels(provider, msg.id)
    assert msg.id not in cached(engine)

    executor.undo(batch.id)
    assert labels(provider, msg.id) == {INBOX, UNREAD}
    assert cached(engine)[msg.id].labels == [INBOX, UNREAD]


def test_undo_trash_restores_labels_the_provider_dropped(engine: Engine) -> None:
    msg = make_message(labels={INBOX, UNREAD})
    provider, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.TRASH, [msg.id])
    assert batch.id is not None
    # Gmail removes INBOX when a message is trashed.
    provider.modify_labels([msg.id], remove=[INBOX])

    executor.undo(batch.id)
    assert labels(provider, msg.id) == {INBOX, UNREAD}
    assert cached(engine)[msg.id].labels == [INBOX, UNREAD]


def test_not_spam_moves_to_inbox_and_undo_puts_it_back(engine: Engine) -> None:
    msg = make_message(labels={SPAM})
    provider, executor = setup(engine, msg)

    batch = executor.apply(ActionKind.NOT_SPAM, [msg.id])
    assert batch.id is not None
    assert labels(provider, msg.id) == {INBOX}

    executor.undo(batch.id)
    assert labels(provider, msg.id) == {SPAM}


def test_protected_mail_is_skipped(engine: Engine) -> None:
    plain = make_message()
    starred = make_message(labels={INBOX, STARRED})
    receipt = make_message(subject="Your receipt")
    provider, executor = setup(engine, plain, starred, receipt)

    batch = executor.apply(ActionKind.TRASH, [plain.id, starred.id, receipt.id])

    assert batch.applied_count == 1
    assert batch.skipped_count == 2
    assert TRASH in labels(provider, plain.id)
    assert TRASH not in labels(provider, starred.id)
    assert TRASH not in labels(provider, receipt.id)
    reasons = {i.message_id: i.skipped_reason for i in items(engine, batch.id)}
    assert reasons[starred.id] == "Protected: Starred"
    assert reasons[receipt.id] == 'Protected: Mentions "receipt"'


def test_mail_from_correspondents_is_protected(engine: Engine) -> None:
    sent = make_message(labels={SENT}, recipients=("friend@example.com",))
    reply = make_message(sender_email="friend@example.com")
    provider, executor = setup(engine, sent, reply)

    batch = executor.apply(ActionKind.ARCHIVE, [reply.id])
    assert batch.applied_count == 0
    assert INBOX in labels(provider, reply.id)


def test_confirmed_protected_mail_is_acted_on(engine: Engine) -> None:
    starred = make_message(labels={INBOX, STARRED})
    provider, executor = setup(engine, starred)

    batch = executor.apply(ActionKind.ARCHIVE, [starred.id], confirmed=[starred.id])
    assert batch.applied_count == 1
    assert labels(provider, starred.id) == {STARRED}


def test_protection_uses_labels_changed_since_last_sync(engine: Engine) -> None:
    msg = make_message()
    provider, executor = setup(engine, msg)
    # Starred in Gmail after our last sync; the cache still says it isn't.
    provider.modify_labels([msg.id], add=[STARRED])

    batch = executor.apply(ActionKind.TRASH, [msg.id])
    assert batch.applied_count == 0
    assert TRASH not in labels(provider, msg.id)


def test_falls_back_to_provider_when_cache_cannot_catch_up(engine: Engine) -> None:
    msg = make_message()
    provider, executor = setup(engine, msg)
    provider.modify_labels([msg.id], add=[STARRED])
    provider.deliver(make_message())
    provider.expire_history()
    provider.calls.clear()

    batch = executor.apply(ActionKind.TRASH, [msg.id])
    assert ("get_messages", (msg.id,)) in provider.calls
    assert batch.applied_count == 0


def test_gone_and_already_done_messages_are_skipped(engine: Engine) -> None:
    archived = make_message(labels=set())
    gone = make_message()
    provider, executor = setup(engine, archived, gone)
    provider.delete_forever(gone.id)

    batch = executor.apply(ActionKind.ARCHIVE, [archived.id, gone.id])
    assert batch.applied_count == 0
    assert not any(name == "modify_labels" for name, _ in provider.calls)
    reasons = {i.message_id: i.skipped_reason for i in items(engine, batch.id)}
    assert reasons == {archived.id: "Already done", gone.id: "No longer in the mailbox"}


def test_duplicate_ids_are_acted_on_once(engine: Engine) -> None:
    msg = make_message()
    _, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.ARCHIVE, [msg.id, msg.id])
    assert batch.applied_count == 1
    assert len(items(engine, batch.id)) == 1


def test_preview_does_not_touch_the_mailbox(engine: Engine) -> None:
    plain = make_message(size_estimate=1_000)
    starred = make_message(labels={INBOX, STARRED}, size_estimate=5_000)
    provider, executor = setup(engine, plain, starred)

    plan = executor.preview(ActionKind.TRASH, [plain.id, starred.id])

    assert [c.id for c in plan.to_apply] == [plain.id]
    assert plan.total_size == 1_000
    [skipped] = plan.skipped
    assert skipped.protected
    assert skipped.candidate is not None
    assert skipped.candidate.id == starred.id
    assert provider.calls == []
    with Session(engine) as session:
        assert session.exec(select(ActionBatch)).all() == []


def test_not_spam_ignores_protection(engine: Engine) -> None:
    msg = make_message(labels={SPAM}, subject="Your invoice")
    _, executor = setup(engine, msg)
    assert executor.preview(ActionKind.NOT_SPAM, [msg.id]).skipped == []


@pytest.mark.parametrize("ids", [[], [f"m{i}" for i in range(3)]])
def test_rejects_empty_or_oversized_requests(engine: Engine, ids: list[str]) -> None:
    executor = ActionExecutor(FakeProvider(), engine, max_messages=2)
    with pytest.raises(ActionError):
        executor.apply(ActionKind.ARCHIVE, ids)


class FailingProvider(FakeProvider):
    def trash(self, ids: Any) -> None:
        super().trash(ids[:1])
        raise RuntimeError("quota exceeded")


def test_failure_is_logged_and_can_be_undone(engine: Engine) -> None:
    first, second = make_message(), make_message()
    provider = FailingProvider([first, second])
    MailboxSync(provider, engine).run()
    executor = ActionExecutor(provider, engine)

    with pytest.raises(ActionError):
        executor.apply(ActionKind.TRASH, [first.id, second.id])

    with Session(engine) as session:
        batch = session.exec(select(ActionBatch)).one()
    assert batch.status == "failed"
    assert batch.error == "quota exceeded"
    assert batch.id is not None

    executor.undo(batch.id)
    assert TRASH not in labels(provider, first.id)


def test_undo_twice_is_refused(engine: Engine) -> None:
    msg = make_message()
    _, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.ARCHIVE, [msg.id])
    assert batch.id is not None
    executor.undo(batch.id)
    with pytest.raises(ActionError, match="already been undone"):
        executor.undo(batch.id)


def test_undo_unknown_batch(engine: Engine) -> None:
    _, executor = setup(engine)
    with pytest.raises(LookupError):
        executor.undo(999)


def test_trash_older_than_retention_cannot_be_undone(engine: Engine) -> None:
    msg = make_message()
    _, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.TRASH, [msg.id])
    with Session(engine) as session:
        stored = session.get(ActionBatch, batch.id)
        assert stored is not None
        stored.created_at = stored.created_at - timedelta(days=31)
        session.add(stored)
        session.commit()

    assert batch.id is not None
    with pytest.raises(ActionError, match="30 days"):
        executor.undo(batch.id)


def test_undo_skips_messages_deleted_since(engine: Engine) -> None:
    kept, gone = make_message(), make_message()
    provider, executor = setup(engine, kept, gone)
    batch = executor.apply(ActionKind.TRASH, [kept.id, gone.id])
    provider.delete_forever(gone.id)

    assert batch.id is not None
    executor.undo(batch.id)
    assert set(cached(engine)) == {kept.id}


def test_labels_unchanged_by_action_survive_undo(engine: Engine) -> None:
    msg = make_message(labels={INBOX})
    provider, executor = setup(engine, msg)
    batch = executor.apply(ActionKind.ARCHIVE, [msg.id])
    provider.deliver(replace(provider.get_messages([msg.id])[0], labels=frozenset({STARRED})))

    assert batch.id is not None
    executor.undo(batch.id)
    assert labels(provider, msg.id) == {INBOX, STARRED}
