import pytest

from inboxkeeper.providers.base import INBOX, SPAM, TRASH, CursorExpiredError
from inboxkeeper.providers.fake import FakeProvider
from tests.factories import make_message


def test_iter_ids_is_newest_first_and_skips_trash() -> None:
    old, new, trashed = make_message(), make_message(), make_message(labels={TRASH})
    provider = FakeProvider([old, new, trashed])

    assert list(provider.iter_message_ids()) == [new.id, old.id]


def test_iter_ids_can_exclude_spam() -> None:
    ham, spam = make_message(), make_message(labels={SPAM})
    provider = FakeProvider([ham, spam])

    assert set(provider.iter_message_ids()) == {ham.id, spam.id}
    assert list(provider.iter_message_ids(include_spam=False)) == [ham.id]


def test_changes_since_tracks_updates_and_deletes() -> None:
    a, b = make_message(), make_message()
    provider = FakeProvider([a, b])
    cursor = provider.get_cursor()

    provider.modify_labels([a.id], remove=[INBOX])
    provider.delete_forever(b.id)
    c = make_message()
    provider.deliver(c)

    changes = provider.changes_since(cursor)
    assert changes.changed == {a.id, c.id}
    assert changes.deleted == {b.id}
    assert provider.changes_since(changes.cursor).changed == frozenset()


def test_expired_cursor_raises() -> None:
    provider = FakeProvider([make_message()])
    cursor = provider.get_cursor()
    provider.deliver(make_message())
    provider.expire_history()

    with pytest.raises(CursorExpiredError):
        provider.changes_since(cursor)


def test_trash_and_untrash_round_trip() -> None:
    msg = make_message()
    provider = FakeProvider([msg])

    provider.trash([msg.id])
    assert list(provider.iter_message_ids()) == []

    provider.untrash([msg.id])
    assert provider.get_messages([msg.id])[0].labels == {INBOX}
