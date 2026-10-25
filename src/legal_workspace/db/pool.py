"""Connection pool (psycopg 3) with pgvector registered. Callers own transactions."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import get_settings

Conn = psycopg.Connection[dict[str, Any]]
_pool: ConnectionPool | None = None
_lock = threading.Lock()


def _configure(conn: psycopg.Connection) -> None:
    conn.row_factory = dict_row  # type: ignore[assignment]
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:  # extension not created yet (first migration run)
        conn.rollback()


def get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            s = get_settings()
            _pool = ConnectionPool(
                s.database_url,
                min_size=1,
                max_size=s.db_pool_max,
                configure=_configure,
                open=False,
                timeout=15,
            )
            _pool.open(wait=True, timeout=15)
        return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connection() -> Iterator[Conn]:
    """A pooled connection; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        yield cast(Conn, conn)


@contextmanager
def advisory_lock(conn: Conn, key: str) -> Iterator[None]:
    """Transaction-level advisory lock keyed by a string (e.g. the matter id)."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))
    yield


def db_healthy() -> bool:
    try:
        with connection() as c:
            c.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
