"""Storage for scanner suggestions.

Scanners describe what they'd do as drafts. Saving a scanner's drafts replaces
its previous results, while keeping what the user already decided: a dismissed
group stays dismissed when the next scan finds it again.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import Session, col, select

from inboxkeeper.actions.kinds import CHANGES, ActionKind
from inboxkeeper.db.models import Message, Proposal, utcnow
from inboxkeeper.safety.protection import ProtectionPolicy, load_correspondents


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    key: str
    kind: ActionKind
    title: str
    reason: str
    message_ids: Sequence[str]


def save_proposals(
    session: Session,
    scanner: str,
    drafts: Sequence[ProposalDraft],
    policy: ProtectionPolicy | None = None,
) -> list[Proposal]:
    policy = policy or ProtectionPolicy()
    correspondents = load_correspondents(session)
    existing = {p.key: p for p in session.exec(select(Proposal).where(Proposal.scanner == scanner))}

    saved: list[Proposal] = []
    for draft in drafts:
        rows = session.exec(select(Message).where(col(Message.id).in_(draft.message_ids))).all()
        by_id = {r.id: r for r in rows}
        allowed: list[str] = []
        protected: list[str] = []
        for msg_id in dict.fromkeys(draft.message_ids):
            row = by_id.get(msg_id)
            if row is None:
                continue
            if CHANGES[draft.kind].guarded and policy.reasons(row, correspondents):
                protected.append(msg_id)
            else:
                allowed.append(msg_id)
        if not allowed and not protected:
            continue

        proposal = existing.pop(draft.key, None) or Proposal(
            scanner=scanner, key=draft.key, kind=draft.kind, title=draft.title, reason=draft.reason
        )
        if proposal.status == "applied" and allowed:
            # New matching mail arrived after the user acted on this group.
            proposal.status = "pending"
            proposal.batch_id = None
        proposal.kind = draft.kind
        proposal.title = draft.title
        proposal.reason = draft.reason
        proposal.message_ids = allowed
        proposal.protected_ids = protected
        proposal.total_size = sum(by_id[i].size_estimate for i in allowed)
        proposal.updated_at = utcnow()
        session.add(proposal)
        saved.append(proposal)

    # Pending groups the scan no longer finds are stale. Decisions are kept.
    for leftover in existing.values():
        if leftover.status == "pending":
            session.delete(leftover)

    session.commit()
    for proposal in saved:
        session.refresh(proposal)
    return saved
