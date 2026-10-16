import threading

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from inboxkeeper.db.models import Message, SyncState
from inboxkeeper.db.session import create_db_engine
from inboxkeeper.providers.base import INBOX, SPAM, STARRED
from inboxkeeper.providers.fake import FakeProvider
from inboxkeeper.sync import BackgroundSync, MailboxSync, SyncAlreadyRunningError
from tests.factories import make_message


@pytest.fixture
def engine() -> Engine:
    return create_db_engine(None)


def cached(engine: Engine) -> dict[str, Message]:
    with Session(engine) as session:
        return {m.id: m for m in session.exec(select(Message)).all()}


def test_first_sync_fetches_everything_including_spam(engine: Engine) -> None:
    msgs = [make_message(), make_message(labels={SPAM})]
    result = MailboxSync(FakeProvider(msgs), engine).run()

    assert result.mode == "full"
    assert result.fetched == 2
    assert set(cached(engine)) == {m.id for m in msgs}


def test_incremental_sync_picks_up_changes(engine: Engine) -> None:
    keep, star, gone = make_message(), make_message(), make_message()
    provider = FakeProvider([keep, star, gone])
    sync = MailboxSync(provider, engine)
    sync.run()

    provider.modify_labels([star.id], add=[STARRED])
    provider.delete_forever(gone.id)
    new = make_message()
    provider.deliver(new)
    provider.calls.clear()

    result = sync.run()

    assert result.mode == "incremental"
    assert result.removed == 1
    assert ("get_messages", tuple(sorted([star.id, new.id]))) in provider.calls
    cache = cached(engine)
    assert set(cache) == {keep.id, star.id, new.id}
    assert STARRED in cache[star.id].labels


def test_trashed_messages_leave_the_cache(engine: Engine) -> None:
    msg = make_message()
    provider = FakeProvider([msg])
    sync = MailboxSync(provider, engine)
    sync.run()

    provider.trash([msg.id])
    sync.run()

    assert cached(engine) == {}


def test_expired_cursor_falls_back_to_full_sync(engine: Engine) -> None:
    a, b = make_message(), make_message()
    provider = FakeProvider([a, b])
    sync = MailboxSync(provider, engine)
    sync.run()

    provider.delete_forever(b.id)
    provider.modify_labels([a.id], remove=[INBOX])
    provider.expire_history()

    result = sync.run()

    assert result.mode == "full"
    cache = cached(engine)
    assert set(cache) == {a.id}
    assert cache[a.id].labels == []


def test_interrupted_first_sync_resumes(engine: Engine) -> None:
    msgs = [make_message() for _ in range(5)]
    provider = FakeProvider(msgs)

    class SimulatedCrashError(Exception):
        pass

    def blow_up(done: int, total: int) -> None:
        if done >= 2:
            raise SimulatedCrashError

    with pytest.raises(SimulatedCrashError):
        MailboxSync(provider, engine, batch_size=2).run(on_progress=blow_up)
    assert len(cached(engine)) == 2

    provider.calls.clear()
    result = MailboxSync(provider, engine, batch_size=2).run()

    assert result.mode == "resume"
    assert result.fetched == 3
    fetched_ids = {i for name, ids in provider.calls if name == "get_messages" for i in ids}
    assert len(fetched_ids) == 3
    assert len(cached(engine)) == 5


def test_limited_sync_takes_newest_and_never_removes(engine: Engine) -> None:
    msgs = [make_message() for _ in range(4)]
    provider = FakeProvider(msgs)
    sync = MailboxSync(provider, engine)

    sync.run(limit=2)
    assert set(cached(engine)) == {msgs[3].id, msgs[2].id}

    with Session(engine) as session:
        state = session.exec(select(SyncState)).one()
        assert not state.full_sync_complete


def test_switching_accounts_clears_the_cache(engine: Engine) -> None:
    MailboxSync(FakeProvider([make_message()], email="old@example.com"), engine).run()
    other = make_message()
    MailboxSync(FakeProvider([other], email="new@example.com"), engine).run()

    assert set(cached(engine)) == {other.id}
    with Session(engine) as session:
        assert [s.account for s in session.exec(select(SyncState))] == ["new@example.com"]


def test_progress_is_reported(engine: Engine) -> None:
    provider = FakeProvider([make_message() for _ in range(5)])
    seen: list[tuple[int, int]] = []

    MailboxSync(provider, engine, batch_size=2).run(on_progress=lambda d, t: seen.append((d, t)))

    assert seen == [(0, 5), (2, 5), (4, 5), (5, 5)]


def test_switching_accounts_clears_cache_even_if_new_account_has_state(engine: Engine) -> None:
    MailboxSync(FakeProvider([make_message()], email="old@example.com"), engine).run()
    with Session(engine) as session:
        session.add(SyncState(account="new@example.com"))
        session.commit()

    other = make_message()
    MailboxSync(FakeProvider([other], email="new@example.com"), engine).run()

    assert set(cached(engine)) == {other.id}


def test_background_sync_reports_completion(engine: Engine) -> None:
    provider = FakeProvider([make_message() for _ in range(3)])
    runner = BackgroundSync(engine, lambda: provider)

    assert runner.start().state == "running"
    runner.join(timeout=5)

    status = runner.status
    assert status.state == "done"
    assert status.processed == status.total == 3
    assert status.result is not None
    assert status.result.fetched == 3
    assert status.finished_at is not None


def test_background_sync_captures_errors(engine: Engine) -> None:
    def broken() -> FakeProvider:
        raise RuntimeError("token revoked")

    runner = BackgroundSync(engine, broken)
    runner.start()
    runner.join(timeout=5)

    assert runner.status.state == "error"
    assert runner.status.error == "token revoked"


def test_background_sync_refuses_concurrent_runs(engine: Engine) -> None:
    gate = threading.Event()
    provider = FakeProvider([make_message()])

    def slow_factory() -> FakeProvider:
        gate.wait(timeout=5)
        return provider

    runner = BackgroundSync(engine, slow_factory)
    runner.start()
    with pytest.raises(SyncAlreadyRunningError):
        runner.start()
    gate.set()
    runner.join(timeout=5)

    assert runner.status.state == "done"
    runner.start()
    runner.join(timeout=5)


def test_catch_up_applies_recent_changes(engine: Engine) -> None:
    msg = make_message()
    provider = FakeProvider([msg])
    sync = MailboxSync(provider, engine)
    sync.run()
    provider.modify_labels([msg.id], add=[STARRED])

    assert sync.catch_up()
    assert STARRED in cached(engine)[msg.id].labels


def test_catch_up_never_starts_a_full_sync(engine: Engine) -> None:
    provider = FakeProvider([make_message()])
    sync = MailboxSync(provider, engine)
    assert not sync.catch_up()

    sync.run(limit=1)
    assert not sync.catch_up()

    sync.run()
    provider.deliver(make_message())
    provider.expire_history()
    provider.calls.clear()
    assert not sync.catch_up()
    assert provider.calls == []
