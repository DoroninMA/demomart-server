import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Query, Request

SQLITE_MAX_INT = 2**63 - 1
PageLimit = Annotated[int, Query(ge=1, le=SQLITE_MAX_INT)]


def connect(path: str) -> sqlite3.Connection:
    # Sync dependencies for a single request can run on different worker threads.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(connect(request.app.state.settings.database_path)) as conn:
        yield conn


Db = Annotated[sqlite3.Connection, Depends(get_db)]


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        yield


def timestamp(at: datetime | None = None) -> str:
    if at is None:
        at = datetime.now(timezone.utc)
    return at.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
