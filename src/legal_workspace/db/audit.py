from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from legal_workspace.db.pool import Conn


def record(
    conn: Conn,
    *,
    actor: str,
    action: str,
    role: str | None = None,
    matter_id: str | None = None,
    entity: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, role, action, matter_id, entity, entity_id, detail, request_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (actor, role, action, matter_id, entity, entity_id, Jsonb(detail or {}), request_id),
    )


def list_entries(conn: Conn, matter_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    if matter_id:
        return conn.execute(
            "SELECT * FROM audit_log WHERE matter_id = %s ORDER BY audit_id DESC LIMIT %s", (matter_id, limit)
        ).fetchall()
    return conn.execute("SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT %s", (limit,)).fetchall()
