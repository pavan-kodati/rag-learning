from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from legal_workspace.db.pool import Conn

from ..errors import NotFound


def insert_trace(conn: Conn, *, matter_id: str, as_of: int, question: str, intents: list[str], routed_by: str, plans: Any,
                 retrieved: Any, citation_checks: Any, timings: dict, model_versions: dict, answer: Any, actor: str | None) -> str:  # fmt: skip
    row = conn.execute(
        "INSERT INTO query_traces (matter_id, as_of_batch_seq, question, intents, routed_by, plans, retrieved, citation_checks, timings_ms, "
        "model_versions, answer, actor) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING trace_id",
        (matter_id, as_of, question, intents, routed_by, Jsonb(plans), Jsonb(retrieved), Jsonb(citation_checks), Jsonb(timings),
         Jsonb(model_versions), Jsonb(answer), actor),
    ).fetchone()  # fmt: skip
    assert row is not None
    return str(row["trace_id"])


def get_trace(conn: Conn, trace_id: str) -> dict[str, Any]:
    try:
        row = conn.execute("SELECT * FROM query_traces WHERE trace_id = %s", (trace_id,)).fetchone()
    except psycopg.errors.InvalidTextRepresentation as e:
        conn.rollback()
        raise NotFound(f"trace {trace_id!r} not found") from e
    if row is None:
        raise NotFound(f"trace {trace_id} not found")
    return row


def list_traces(conn: Conn, matter_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT trace_id, as_of_batch_seq, question, intents, routed_by, created_at, actor FROM query_traces WHERE matter_id = %s "
        "ORDER BY created_at DESC LIMIT %s",
        (matter_id, limit),
    ).fetchall()
