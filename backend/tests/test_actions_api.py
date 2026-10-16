from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from inboxkeeper.actions.kinds import ActionKind
from inboxkeeper.api.context import AppContext
from inboxkeeper.proposals import ProposalDraft, save_proposals
from inboxkeeper.providers.base import INBOX, STARRED, TRASH, MessageMeta
from inboxkeeper.providers.fake import FakeProvider
from inboxkeeper.sync import MailboxSync
from tests.factories import make_message

pytestmark = pytest.mark.usefixtures("connected")


def deliver(ctx: AppContext, provider: FakeProvider, *msgs: MessageMeta) -> None:
    for msg in msgs:
        provider.deliver(msg)
    MailboxSync(provider, ctx.engine).run()


def labels(provider: FakeProvider, msg_id: str) -> frozenset[str]:
    return provider.get_messages([msg_id])[0].labels


def test_preview_reports_protected_mail(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    plain = make_message(size_estimate=3_000)
    starred = make_message(labels={INBOX, STARRED}, subject="Keep me")
    deliver(ctx, provider, plain, starred)

    resp = client.post(
        "/api/actions/preview", json={"kind": "trash", "message_ids": [plain.id, starred.id]}
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "kind": "trash",
        "count": 1,
        "total_size": 3_000,
        "skipped": [
            {
                "message_id": starred.id,
                "reason": "Protected: Starred",
                "protected": True,
                "sender_email": starred.sender_email,
                "subject": "Keep me",
            }
        ],
    }


def test_apply_list_detail_and_undo(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    msg = make_message()
    deliver(ctx, provider, msg)

    resp = client.post("/api/actions", json={"kind": "archive", "message_ids": [msg.id]})
    assert resp.status_code == 201
    batch = resp.json()
    assert batch["status"] == "applied"
    assert batch["can_undo"]
    assert INBOX not in labels(provider, msg.id)

    [listed] = client.get("/api/actions").json()
    assert listed["id"] == batch["id"]

    detail = client.get(f"/api/actions/{batch['id']}").json()
    assert detail["items"] == [
        {
            "message_id": msg.id,
            "sender_email": msg.sender_email,
            "subject": msg.subject,
            "size_estimate": msg.size_estimate,
            "skipped_reason": None,
        }
    ]

    undone = client.post(f"/api/actions/{batch['id']}/undo").json()
    assert undone["status"] == "undone"
    assert not undone["can_undo"]
    assert INBOX in labels(provider, msg.id)

    again = client.post(f"/api/actions/{batch['id']}/undo")
    assert again.status_code == 400
    assert again.json()["detail"] == "This action has already been undone."


def test_unknown_action_is_404(client: TestClient) -> None:
    assert client.get("/api/actions/42").status_code == 404
    assert client.post("/api/actions/42/undo").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "archive", "message_ids": []},
        {"kind": "delete_forever", "message_ids": ["m1"]},
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/actions", json=body).status_code == 422


def test_actions_require_connection(client: TestClient, ctx: AppContext) -> None:
    ctx.auth.token_path.unlink()
    body = {"kind": "archive", "message_ids": ["m1"]}
    assert client.post("/api/actions", json=body).status_code == 401
    assert client.post("/api/actions/preview", json=body).status_code == 401


def test_one_mailbox_change_at_a_time(client: TestClient, ctx: AppContext) -> None:
    body = {"kind": "archive", "message_ids": ["m1"]}
    with ctx.action_lock:
        assert client.post("/api/actions", json=body).status_code == 409
        assert client.post("/api/sync").status_code == 409
        assert client.post("/api/auth/disconnect").status_code == 409


def test_cross_origin_actions_are_blocked(client: TestClient) -> None:
    resp = client.post(
        "/api/actions",
        json={"kind": "trash", "message_ids": ["m1"]},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


def make_proposal(ctx: AppContext, *msgs: MessageMeta, key: str = "news") -> int:
    draft = ProposalDraft(
        key, ActionKind.ARCHIVE, "Archive News", "Never read", [m.id for m in msgs]
    )
    with Session(ctx.engine) as session:
        [proposal] = save_proposals(session, "cleanup", [draft])
        assert proposal.id is not None
        return proposal.id


def test_apply_proposal_with_exclusions_and_confirmations(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    keep, archive = make_message(), make_message()
    starred = make_message(labels={INBOX, STARRED})
    deliver(ctx, provider, keep, archive, starred)
    pid = make_proposal(ctx, keep, archive, starred)

    [listed] = client.get("/api/proposals", params={"scanner": "cleanup"}).json()
    assert listed["message_count"] == 2
    assert listed["protected_count"] == 1

    resp = client.post(
        f"/api/proposals/{pid}/apply", json={"exclude": [keep.id], "confirmed": [starred.id]}
    )
    assert resp.status_code == 201
    assert resp.json()["applied_count"] == 2
    assert INBOX in labels(provider, keep.id)
    assert INBOX not in labels(provider, archive.id)
    assert INBOX not in labels(provider, starred.id)

    [applied] = client.get("/api/proposals").json()
    assert applied["status"] == "applied"
    assert applied["batch_id"] == resp.json()["id"]
    assert client.post(f"/api/proposals/{pid}/apply", json={}).status_code == 409

    client.post(f"/api/actions/{applied['batch_id']}/undo")
    [reopened] = client.get("/api/proposals").json()
    assert reopened["status"] == "pending"
    assert reopened["batch_id"] is None


def test_confirming_messages_outside_the_proposal_does_nothing(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    plain = make_message()
    outsider = make_message(labels={INBOX, STARRED})
    deliver(ctx, provider, plain, outsider)
    pid = make_proposal(ctx, plain)

    resp = client.post(f"/api/proposals/{pid}/apply", json={"confirmed": [outsider.id]})
    assert resp.json()["applied_count"] == 1
    assert TRASH not in labels(provider, outsider.id)
    assert INBOX in labels(provider, outsider.id)


def test_excluding_everything_is_rejected(
    client: TestClient, ctx: AppContext, provider: FakeProvider
) -> None:
    msg = make_message()
    deliver(ctx, provider, msg)
    pid = make_proposal(ctx, msg)
    resp = client.post(f"/api/proposals/{pid}/apply", json={"exclude": [msg.id]})
    assert resp.status_code == 400


def test_dismiss_and_restore(client: TestClient, ctx: AppContext, provider: FakeProvider) -> None:
    msg = make_message()
    deliver(ctx, provider, msg)
    pid = make_proposal(ctx, msg)

    assert client.post(f"/api/proposals/{pid}/dismiss").json()["status"] == "dismissed"
    assert client.post(f"/api/proposals/{pid}/dismiss").status_code == 409
    assert client.post(f"/api/proposals/{pid}/apply", json={}).status_code == 409
    assert client.get("/api/proposals", params={"status": "pending"}).json() == []
    assert client.post(f"/api/proposals/{pid}/restore").json()["status"] == "pending"
    assert client.post("/api/proposals/999/dismiss").status_code == 404
