from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

# Importing the models registers their tables on SQLModel.metadata.
from inboxkeeper.db import models as _models  # noqa: F401


def create_db_engine(path: Path | None) -> Engine:
    """Create the engine and tables. Pass None for a throwaway in-memory database."""
    if path is None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn: Any, _record: Any) -> None:
        cursor = dbapi_conn.cursor()
        # WAL lets the API read while a sync is writing in the background.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return engine
