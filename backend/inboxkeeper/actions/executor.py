"""Applies approved actions to the mailbox, records them, and undoes them.

Every action goes through the same steps:

1. Bring the cache up to date, so decisions use the mailbox as it is now and
   not as it was at the last sync.
2. Re-check each message: skip ones that are gone, already in the target state,
   or protected (unless the user confirmed that exact message).
3. Write the batch and each message's current labels to the action log.
4. Only then touch the mailbox.
"""

import logging
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from inboxkeeper.actions.kinds import CHANGES, ActionKind
from inboxkeeper.db.models import ActionBatch, ActionItem, Message, utcnow
from inboxkeeper.providers.base import TRASH, MailProvider, MessageMeta
from inboxkeeper.safety.protection import ProtectionPolicy, load_correspondents
from inboxkeeper.sync import MailboxSync

log = logging.getLogger(__name__)

MAX_MESSAGES = 2000
TRASH_RETENTION = timedelta(days=30)
# System labels the API won't let us add back, so undo doesn't try.
_UNRESTORABLE = {"SENT", "DRAFT", "CHAT", TRASH}


class ActionError(Exception):
    """An action couldn't run. The message is meant for the user."""


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    labels: frozenset[str]
    sender_email: str = ""
    subject: str = ""
    snippet: str = ""
    size_estimate: int = 0

    @classmethod
    def from_row(cls, row: Message) -> "Candidate":
        return cls(
            row.id,
            frozenset(row.labels),
            row.sender_email,
            row.subject,
            row.snippet,
            row.size_estimate,
        )

    @classmethod
    def from_meta(cls, meta: MessageMeta) -> "Candidate":
        return cls(
            meta.id, meta.labels, meta.sender_email, meta.subject, meta.snippet, meta.size_estimate
        )


@dataclass(frozen=True, slots=True)
class Skipped:
    message_id: str
    reason: str
    candidate: Candidate | None = None
    # Protected messages can still be included by confirming them one by one.
    protected: bool = False


@dataclass(frozen=True, slots=True)
class ActionPlan:
    kind: ActionKind
    to_apply: list[Candidate] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(c.size_estimate for c in self.to_apply)


class ActionExecutor:
    def __init__(
        self,
        provider: MailProvider,
        engine: Engine,
        policy: ProtectionPolicy | None = None,
        *,
        max_messages: int = MAX_MESSAGES,
    ) -> None:
        self.provider = provider
        self.engine = engine
        self.policy = policy or ProtectionPolicy()
        self.max_messages = max_messages

    def preview(
        self, kind: ActionKind, ids: Sequence[str], confirmed: Collection[str] = ()
    ) -> ActionPlan:
        """What apply() would do, judged from the cache. Doesn't contact the provider."""
        self._check_size(ids)
        return self._plan(kind, ids, self._load_cached(ids), confirmed)

    def apply(
        self, kind: ActionKind, ids: Sequence[str], confirmed: Collection[str] = ()
    ) -> ActionBatch:
        self._check_size(ids)
        if MailboxSync(self.provider, self.engine).catch_up():
            current = self._load_cached(ids)
        else:
            # No usable sync cursor, so ask the provider about each message.
            current = {m.id: Candidate.from_meta(m) for m in self.provider.get_messages(ids)}

        plan = self._plan(kind, ids, current, confirmed)
        batch = self._record(plan)
        assert batch.id is not None
        applied_ids = [c.id for c in plan.to_apply]

        try:
            if applied_ids:
                self._run(kind, applied_ids)
        except Exception as exc:
            log.exception("action %s failed", batch.id)
            self._finish(batch.id, status="failed", error=str(exc) or type(exc).__name__)
            raise ActionError(
                "The mailbox rejected part of this action. Anything that did change "
                "can be undone from the activity log."
            ) from exc

        self._update_cache(kind, plan.to_apply)
        return self._finish(batch.id, status="applied")

    def undo(self, batch_id: int) -> ActionBatch:
        with Session(self.engine) as session:
            batch = session.get(ActionBatch, batch_id)
            if batch is None:
                raise LookupError(batch_id)
            items = session.exec(
                select(ActionItem).where(
                    ActionItem.batch_id == batch_id, col(ActionItem.skipped_reason).is_(None)
                )
            ).all()

        if batch.status == "undone":
            raise ActionError("This action has already been undone.")
        if batch.status == "pending":
            raise ActionError("This action is still running.")
        kind = ActionKind(batch.kind)
        if kind is ActionKind.TRASH and utcnow() - batch.created_at > TRASH_RETENTION:
            raise ActionError("Gmail empties the trash after 30 days, so these can't be restored.")

        if kind is ActionKind.TRASH:
            self._undo_trash(items)
        else:
            self._undo_labels(kind, items)

        with Session(self.engine) as session:
            stored = session.get(ActionBatch, batch_id)
            assert stored is not None
            stored.status = "undone"
            stored.undone_at = utcnow()
            session.add(stored)
            session.commit()
            session.refresh(stored)
            return stored

    def _check_size(self, ids: Sequence[str]) -> None:
        if not ids:
            raise ActionError("No messages were selected.")
        if len(ids) > self.max_messages:
            raise ActionError(
                f"That's {len(ids):,} messages; the limit for one action is "
                f"{self.max_messages:,}. Split it into smaller batches."
            )

    def _load_cached(self, ids: Sequence[str]) -> dict[str, Candidate]:
        found: dict[str, Candidate] = {}
        with Session(self.engine) as session:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                rows = session.exec(select(Message).where(col(Message.id).in_(chunk))).all()
                found.update((r.id, Candidate.from_row(r)) for r in rows)
        return found

    def _plan(
        self,
        kind: ActionKind,
        ids: Sequence[str],
        current: dict[str, Candidate],
        confirmed: Collection[str],
    ) -> ActionPlan:
        change = CHANGES[kind]
        confirmed = set(confirmed)
        with Session(self.engine) as session:
            correspondents = load_correspondents(session) if change.guarded else set()

        plan = ActionPlan(kind)
        for msg_id in dict.fromkeys(ids):
            cand = current.get(msg_id)
            if cand is None:
                plan.skipped.append(Skipped(msg_id, "No longer in the mailbox"))
                continue
            if not change.would_change(cand.labels):
                plan.skipped.append(Skipped(msg_id, "Already done", cand))
                continue
            if change.guarded and msg_id not in confirmed:
                reasons = self.policy.reasons(cand, correspondents)
                if reasons:
                    reason = "Protected: " + "; ".join(reasons)
                    plan.skipped.append(Skipped(msg_id, reason, cand, protected=True))
                    continue
            plan.to_apply.append(cand)
        return plan

    def _record(self, plan: ActionPlan) -> ActionBatch:
        with Session(self.engine) as session:
            batch = ActionBatch(
                kind=plan.kind,
                applied_count=len(plan.to_apply),
                skipped_count=len(plan.skipped),
                total_size=plan.total_size,
            )
            session.add(batch)
            session.flush()
            assert batch.id is not None
            for cand in plan.to_apply:
                session.add(_item(batch.id, cand))
            for skip in plan.skipped:
                item = _item(batch.id, skip.candidate) if skip.candidate else None
                item = item or ActionItem(batch_id=batch.id, message_id=skip.message_id)
                item.skipped_reason = skip.reason
                session.add(item)
            session.commit()
            session.refresh(batch)
            return batch

    def _run(self, kind: ActionKind, ids: list[str]) -> None:
        if kind is ActionKind.TRASH:
            self.provider.trash(ids)
        else:
            change = CHANGES[kind]
            self.provider.modify_labels(ids, add=sorted(change.add), remove=sorted(change.remove))

    def _finish(self, batch_id: int, *, status: str, error: str | None = None) -> ActionBatch:
        with Session(self.engine) as session:
            batch = session.get(ActionBatch, batch_id)
            assert batch is not None
            batch.status = status
            batch.error = error
            session.add(batch)
            session.commit()
            session.refresh(batch)
            return batch

    def _update_cache(self, kind: ActionKind, applied: Iterable[Candidate]) -> None:
        # Patch the cache locally instead of re-fetching: it keeps the overview
        # accurate right away, and the next sync confirms it anyway.
        change = CHANGES[kind]
        ids = [c.id for c in applied]
        with Session(self.engine) as session:
            if kind is ActionKind.TRASH:
                session.exec(delete(Message).where(col(Message.id).in_(ids)))
            else:
                for row in session.exec(select(Message).where(col(Message.id).in_(ids))):
                    row.labels = sorted(change.apply_to(frozenset(row.labels)))
                    session.add(row)
            session.commit()

    def _undo_labels(self, kind: ActionKind, items: Sequence[ActionItem]) -> None:
        change = CHANGES[kind]
        # Only reverse what the action actually changed for each message.
        groups: dict[tuple[frozenset[str], frozenset[str]], list[str]] = defaultdict(list)
        for item in items:
            prev = frozenset(item.prev_labels)
            groups[(change.remove & prev, change.add - prev)].append(item.message_id)
        for (add, remove), ids in groups.items():
            if add or remove:
                self.provider.modify_labels(ids, add=sorted(add), remove=sorted(remove))

        with Session(self.engine) as session:
            ids_by_group = {i: key for key, ids in groups.items() for i in ids}
            rows = session.exec(select(Message).where(col(Message.id).in_(ids_by_group)))
            for row in rows:
                add, remove = ids_by_group[row.id]
                row.labels = sorted((set(row.labels) | add) - remove)
                session.add(row)
            session.commit()

    def _undo_trash(self, items: Sequence[ActionItem]) -> None:
        ids = [i.message_id for i in items]
        self.provider.untrash(ids)

        # Gmail may drop INBOX and other labels when something is trashed, so
        # put back whatever the message had before.
        restored = {m.id: m for m in self.provider.get_messages(ids)}
        groups: dict[frozenset[str], list[str]] = defaultdict(list)
        for item in items:
            meta = restored.get(item.message_id)
            if meta is None:
                continue
            missing = frozenset(item.prev_labels) - meta.labels - _UNRESTORABLE
            if missing:
                groups[missing].append(item.message_id)
                restored[meta.id] = replace(meta, labels=meta.labels | missing)
        for add, group_ids in groups.items():
            self.provider.modify_labels(group_ids, add=sorted(add))

        with Session(self.engine) as session:
            for meta in restored.values():
                if TRASH not in meta.labels:
                    session.merge(Message.from_meta(meta))
            session.commit()


def _item(batch_id: int, cand: Candidate) -> ActionItem:
    return ActionItem(
        batch_id=batch_id,
        message_id=cand.id,
        prev_labels=sorted(cand.labels),
        sender_email=cand.sender_email,
        subject=cand.subject,
        size_estimate=cand.size_estimate,
    )
