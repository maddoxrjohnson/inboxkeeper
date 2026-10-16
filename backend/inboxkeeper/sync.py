"""Keeps the local message cache in step with the mailbox."""

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from inboxkeeper.db.models import Message, SyncState, utcnow
from inboxkeeper.providers.base import TRASH, CursorExpiredError, MailProvider

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    mode: str  # "full", "resume" or "incremental"
    fetched: int
    removed: int


ProgressCallback = Callable[[int, int], None]


class MailboxSync:
    def __init__(self, provider: MailProvider, engine: Engine, *, batch_size: int = 100) -> None:
        self.provider = provider
        self.engine = engine
        self.batch_size = batch_size

    def run(
        self,
        *,
        force_full: bool = False,
        limit: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> SyncResult:
        """Sync the cache.

        `limit` caps a full sync to the newest N messages, which is handy for a
        quick first look at a huge mailbox. A limited sync never removes cached
        messages, since it can't tell "deleted" from "not fetched".
        """
        account = self.provider.get_account_email()
        state = self._load_state(account)

        if state.full_sync_complete and state.cursor and not force_full:
            try:
                return self._incremental(state, on_progress)
            except CursorExpiredError:
                log.info("history cursor expired for %s, falling back to full sync", account)

        return self._full(
            state,
            resume=not state.full_sync_complete and not force_full,
            limit=limit,
            on_progress=on_progress,
        )

    def _load_state(self, account: str) -> SyncState:
        with Session(self.engine) as session:
            others = session.exec(select(SyncState).where(SyncState.account != account)).all()
            if others:
                # A different account was synced before. Its cached mail would
                # only confuse the scanners, so start clean.
                session.exec(delete(Message))
                session.exec(delete(SyncState).where(col(SyncState.account) != account))

            state = session.get(SyncState, account)
            if state is None:
                state = SyncState(account=account)
                session.add(state)
            session.commit()
            session.refresh(state)
            session.expunge(state)
            return state

    def _full(
        self,
        state: SyncState,
        *,
        resume: bool,
        limit: int | None,
        on_progress: ProgressCallback | None,
    ) -> SyncResult:
        # Grab the cursor before listing so anything that changes mid-sync is
        # picked up by the next incremental run.
        cursor = self.provider.get_cursor()

        remote_ids: list[str] = []
        for msg_id in self.provider.iter_message_ids():
            remote_ids.append(msg_id)
            if limit is not None and len(remote_ids) >= limit:
                break

        with Session(self.engine) as session:
            local_ids = set(session.exec(select(Message.id)).all())

        to_fetch = [i for i in remote_ids if i not in local_ids] if resume else remote_ids
        fetched = self._fetch_and_store(to_fetch, on_progress)

        removed = 0
        if limit is None:
            removed = self._remove(local_ids - set(remote_ids))

        self._save_state(state.account, cursor=cursor, full_sync_complete=limit is None)
        return SyncResult(
            mode="resume" if resume and local_ids else "full", fetched=fetched, removed=removed
        )

    def _incremental(self, state: SyncState, on_progress: ProgressCallback | None) -> SyncResult:
        assert state.cursor is not None
        changes = self.provider.changes_since(state.cursor)

        fetched = self._fetch_and_store(sorted(changes.changed), on_progress)
        removed = self._remove(changes.deleted)

        self._save_state(state.account, cursor=changes.cursor, full_sync_complete=True)
        return SyncResult(mode="incremental", fetched=fetched, removed=removed)

    def _fetch_and_store(self, ids: Sequence[str], on_progress: ProgressCallback | None) -> int:
        total = len(ids)
        done = stored = 0
        if on_progress:
            on_progress(0, total)

        for chunk in batched(ids, self.batch_size):
            metas = self.provider.get_messages(chunk)
            returned = {m.id for m in metas}
            with Session(self.engine) as session:
                for meta in metas:
                    if TRASH in meta.labels:
                        # The cache mirrors what's outside the trash.
                        returned.discard(meta.id)
                        continue
                    session.merge(Message.from_meta(meta))
                    stored += 1
                # Anything the provider didn't return (or returned trashed) is
                # gone from the mailbox as far as we're concerned.
                gone = set(chunk) - returned
                if gone:
                    session.exec(delete(Message).where(col(Message.id).in_(gone)))
                session.commit()
            done += len(chunk)
            if on_progress:
                on_progress(done, total)

        return stored

    def _remove(self, ids: Iterable[str]) -> int:
        ids = list(ids)
        if not ids:
            return 0
        removed = 0
        with Session(self.engine) as session:
            for chunk in batched(ids, 500):
                result = session.exec(delete(Message).where(col(Message.id).in_(chunk)))
                removed += result.rowcount
            session.commit()
        return removed

    def _save_state(self, account: str, *, cursor: str, full_sync_complete: bool) -> None:
        with Session(self.engine) as session:
            state = session.get(SyncState, account)
            assert state is not None
            state.cursor = cursor
            state.full_sync_complete = state.full_sync_complete or full_sync_complete
            state.last_synced_at = utcnow()
            session.add(state)
            session.commit()
