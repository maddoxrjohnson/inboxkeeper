import pytest
from sqlmodel import Session, select

from inboxkeeper.actions.kinds import ActionKind
from inboxkeeper.db.models import Message, Proposal
from inboxkeeper.db.session import create_db_engine
from inboxkeeper.proposals import ProposalDraft, save_proposals
from inboxkeeper.providers.base import INBOX, SPAM, STARRED, MessageMeta
from tests.factories import make_message


@pytest.fixture
def session() -> Session:
    return Session(create_db_engine(None))


def store(session: Session, *msgs: MessageMeta) -> None:
    for msg in msgs:
        session.add(Message.from_meta(msg))
    session.commit()


def draft(key: str, *msgs: MessageMeta, kind: ActionKind = ActionKind.ARCHIVE) -> ProposalDraft:
    return ProposalDraft(key, kind, f"Archive {key}", "Never opened", [m.id for m in msgs])


def proposals(session: Session) -> dict[str, Proposal]:
    return {p.key: p for p in session.exec(select(Proposal))}


def test_protected_mail_is_held_back(session: Session) -> None:
    plain = make_message(size_estimate=1_000)
    starred = make_message(labels={INBOX, STARRED}, size_estimate=9_000)
    store(session, plain, starred)

    [saved] = save_proposals(session, "cleanup", [draft("news", plain, starred)])

    assert saved.message_ids == [plain.id]
    assert saved.protected_ids == [starred.id]
    assert saved.total_size == 1_000
    assert saved.status == "pending"


def test_unguarded_actions_skip_protection(session: Session) -> None:
    msg = make_message(labels={SPAM}, subject="Invoice")
    store(session, msg)
    [saved] = save_proposals(session, "spam", [draft("x", msg, kind=ActionKind.NOT_SPAM)])
    assert saved.message_ids == [msg.id]


def test_uncached_ids_and_empty_groups_are_dropped(session: Session) -> None:
    ghost = make_message()
    assert save_proposals(session, "cleanup", [draft("ghost", ghost)]) == []


def test_rescan_updates_in_place_and_drops_stale_pending(session: Session) -> None:
    a, b, c = make_message(), make_message(), make_message()
    store(session, a, b, c)
    save_proposals(session, "cleanup", [draft("one", a), draft("two", b)])
    first_id = proposals(session)["one"].id

    save_proposals(session, "cleanup", [draft("one", a, c)])

    current = proposals(session)
    assert set(current) == {"one"}
    assert current["one"].id == first_id
    assert current["one"].message_ids == [a.id, c.id]


def test_dismissed_proposals_stay_dismissed(session: Session) -> None:
    a, b = make_message(), make_message()
    store(session, a, b)
    [saved] = save_proposals(session, "cleanup", [draft("one", a)])
    saved.status = "dismissed"
    session.add(saved)
    session.commit()

    save_proposals(session, "cleanup", [draft("one", a, b)])
    assert proposals(session)["one"].status == "dismissed"

    # Even when the scan stops finding it, the decision is remembered.
    save_proposals(session, "cleanup", [])
    assert proposals(session)["one"].status == "dismissed"


def test_applied_proposal_reopens_when_new_mail_matches(session: Session) -> None:
    a, b = make_message(), make_message()
    store(session, a, b)
    [saved] = save_proposals(session, "cleanup", [draft("one", a)])
    saved.status = "applied"
    session.add(saved)
    session.commit()

    save_proposals(session, "cleanup", [draft("one", b)])
    assert proposals(session)["one"].status == "pending"


def test_scanners_do_not_touch_each_other(session: Session) -> None:
    a = make_message()
    store(session, a)
    save_proposals(session, "cleanup", [draft("one", a)])
    save_proposals(session, "unsubscribe", [])
    assert set(proposals(session)) == {"one"}
