import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from inboxkeeper.db.models import Message
from inboxkeeper.db.session import create_db_engine
from inboxkeeper.providers.base import IMPORTANT, INBOX, SENT, STARRED
from inboxkeeper.safety.protection import ProtectionPolicy, load_correspondents
from tests.factories import make_message

policy = ProtectionPolicy()


def test_ordinary_newsletter_is_not_protected() -> None:
    msg = make_message(subject="This week's top stories", snippet="Read more on our site")
    assert policy.reasons(msg) == []


@pytest.mark.parametrize(
    ("label", "reason"),
    [(STARRED, "Starred"), (IMPORTANT, "Marked important"), (SENT, "Sent by you")],
)
def test_labels_protect(label: str, reason: str) -> None:
    msg = make_message(labels={INBOX, label})
    assert policy.reasons(msg) == [reason]


def test_mail_from_correspondents_is_protected() -> None:
    msg = make_message(sender_email="friend@example.com")
    assert policy.reasons(msg, {"friend@example.com"}) == ["From someone you've emailed"]


@pytest.mark.parametrize(
    ("subject", "snippet", "term"),
    [
        ("Your receipt from Acme", "", "receipt"),
        ("Hello", "Your W-2 is ready to download", "w-2"),
        ("Action needed", "Here is your verification code: 123456", "verification code"),
        ("Your Monthly STATEMENT", "", "statement"),
        ("Trip details", "Boarding pass attached", "boarding pass"),
    ],
)
def test_sensitive_terms_protect(subject: str, snippet: str, term: str) -> None:
    msg = make_message(subject=subject, snippet=snippet)
    assert policy.reasons(msg) == [f'Mentions "{term}"']


@pytest.mark.parametrize("subject", ["Taxonomy of birds", "Bankside walking tour", "Ticketmaster"])
def test_sensitive_terms_match_whole_words(subject: str) -> None:
    assert policy.reasons(make_message(subject=subject)) == []


def test_reasons_accumulate() -> None:
    msg = make_message(labels={INBOX, STARRED, IMPORTANT}, subject="Invoice #42")
    assert policy.reasons(msg) == ["Starred", "Marked important", 'Mentions "invoice"']


def test_rules_can_be_switched_off() -> None:
    relaxed = ProtectionPolicy(
        starred=False, important=False, correspondents=False, sensitive_terms=False
    )
    msg = make_message(
        labels={INBOX, STARRED, IMPORTANT}, sender_email="friend@example.com", subject="Receipt"
    )
    assert relaxed.reasons(msg, {"friend@example.com"}) == []


def test_sent_mail_is_always_protected() -> None:
    relaxed = ProtectionPolicy(
        starred=False, important=False, correspondents=False, sensitive_terms=False
    )
    assert relaxed.reasons(make_message(labels={SENT})) == ["Sent by you"]


def test_works_on_cached_rows() -> None:
    row = Message.from_meta(make_message(labels={INBOX, STARRED}))
    assert policy.reasons(row) == ["Starred"]


@pytest.fixture
def engine() -> Engine:
    return create_db_engine(None)


def test_load_correspondents_reads_sent_mail(engine: Engine) -> None:
    sent = make_message(labels={SENT}, recipients=("a@example.com", "b@example.com"))
    received = make_message(recipients=("me@example.com", "c@example.com"))
    with Session(engine) as session:
        session.add(Message.from_meta(sent))
        session.add(Message.from_meta(received))
        session.commit()
        assert load_correspondents(session) == {"a@example.com", "b@example.com"}
