from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import Session, col, select

from inboxkeeper.actions.kinds import ActionKind
from inboxkeeper.api.context import Ctx
from inboxkeeper.api.routes.actions import mailbox_change
from inboxkeeper.api.schemas import ActionBatchOut, ApplyProposalRequest, ProposalOut
from inboxkeeper.db.models import Proposal

router = APIRouter(prefix="/api/proposals")


@router.get("")
def list_proposals(
    ctx: Ctx,
    scanner: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[ProposalOut]:
    query = select(Proposal).order_by(col(Proposal.total_size).desc())
    if scanner:
        query = query.where(Proposal.scanner == scanner)
    if status_filter:
        query = query.where(Proposal.status == status_filter)
    with Session(ctx.engine) as session:
        return [ProposalOut.from_proposal(p) for p in session.exec(query)]


@router.post("/{proposal_id}/dismiss")
def dismiss_proposal(ctx: Ctx, proposal_id: int) -> ProposalOut:
    return _set_status(ctx, proposal_id, "dismissed", expect="pending")


@router.post("/{proposal_id}/restore")
def restore_proposal(ctx: Ctx, proposal_id: int) -> ProposalOut:
    return _set_status(ctx, proposal_id, "pending", expect="dismissed")


@router.post("/{proposal_id}/apply", status_code=status.HTTP_201_CREATED)
def apply_proposal(ctx: Ctx, proposal_id: int, body: ApplyProposalRequest) -> ActionBatchOut:
    with Session(ctx.engine) as session:
        proposal = _get(session, proposal_id)
        if proposal.status != "pending":
            raise HTTPException(status.HTTP_409_CONFLICT, f"This suggestion is {proposal.status}.")
        exclude = set(body.exclude)
        # Only protected messages that belong to this proposal can be confirmed.
        confirmed = [i for i in body.confirmed if i in proposal.protected_ids and i not in exclude]
        ids = [i for i in proposal.message_ids if i not in exclude] + confirmed
        kind = ActionKind(proposal.kind)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No messages are selected.")

    with mailbox_change(ctx) as executor:
        batch = executor.apply(kind, ids, confirmed)

    with Session(ctx.engine) as session:
        proposal = _get(session, proposal_id)
        proposal.status = "applied"
        proposal.batch_id = batch.id
        session.add(proposal)
        session.commit()
    return ActionBatchOut.from_batch(batch)


def _get(session: Session, proposal_id: int) -> Proposal:
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such suggestion.")
    return proposal


def _set_status(ctx: Ctx, proposal_id: int, new: str, *, expect: str) -> ProposalOut:
    with Session(ctx.engine) as session:
        proposal = _get(session, proposal_id)
        if proposal.status != expect:
            raise HTTPException(status.HTTP_409_CONFLICT, f"This suggestion is {proposal.status}.")
        proposal.status = new
        session.add(proposal)
        session.commit()
        session.refresh(proposal)
        return ProposalOut.from_proposal(proposal)
