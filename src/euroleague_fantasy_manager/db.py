"""SQLite database connectivity and shared connection helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Iterator


def connect_db(
    db_path: str | Path,
    *,
    timeout: float = 30.0,
    row_factory: Any = sqlite3.Row,
) -> sqlite3.Connection:
    """Create and configure a SQLite connection with WAL mode, 30s busy timeout, and foreign keys."""
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path_str, timeout=timeout)
    if row_factory is not None:
        conn.row_factory = row_factory

    # In-memory SQLite does not support WAL mode
    if path_str != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_connection(
    db_path: str | Path,
    *,
    timeout: float = 30.0,
    row_factory: Any = sqlite3.Row,
) -> Iterator[sqlite3.Connection]:
    """Context manager yielding a SQLite connection that is reliably closed upon exit."""
    conn = connect_db(db_path, timeout=timeout, row_factory=row_factory)
    try:
        yield conn
    finally:
        conn.close()
