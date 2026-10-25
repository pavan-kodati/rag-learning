"""Chunk persistence (evidence layer)."""

from __future__ import annotations

from typing import Any

from pgvector import Vector
from psycopg.types.json import Jsonb

from legal_workspace.db.pool import Conn

Row = dict[str, Any]


def delete_for_document(conn: Conn, document_id: str) -> None:
    conn.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))


def insert_chunks(
    conn: Conn, *, matter_id: str, document_id: str, batch_seq: int, drafts: list[dict[str, Any]],
) -> list[str]:  # fmt: skip
    """Insert chunks (parents first). Each draft: level, ordinal, ref, heading, header, text, page_start, page_end,
    char_start, char_end, bboxes, tokens, parent (index into `drafts`), embedding (list[float] | None)."""
    ids: list[str] = []
    for d in drafts:
        parent_id = ids[d["parent"]] if d.get("parent") is not None else None
        emb = Vector(d["embedding"]) if d.get("embedding") is not None else None
        row = conn.execute(
            "INSERT INTO document_chunks (matter_id, document_id, batch_seq, parent_chunk_id, chunk_level, ordinal, "
            "structural_ref, heading, context_header, chunk_text, page_start, page_end, char_start, char_end, bboxes, "
            "token_count, dense_embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING chunk_id",
            (
                matter_id, document_id, batch_seq, parent_id, d["level"], d["ordinal"], d["ref"], d["heading"], d["header"],
                d["text"], d["page_start"], d["page_end"], d["char_start"], d["char_end"], Jsonb(d["bboxes"]), d["tokens"], emb,
            ),
        ).fetchone()  # fmt: skip
        assert row is not None
        ids.append(str(row["chunk_id"]))
    return ids


def list_children(conn: Conn, document_id: str) -> list[Row]:
    return conn.execute(
        "SELECT chunk_id, parent_chunk_id, ordinal, structural_ref, chunk_text, page_start, page_end "
        "FROM document_chunks WHERE document_id = %s AND chunk_level = 'CHILD' ORDER BY ordinal",
        (document_id,),
    ).fetchall()


def get_chunks(conn: Conn, chunk_ids: list[str]) -> list[Row]:
    if not chunk_ids:
        return []
    return conn.execute(
        "SELECT c.*, d.title AS document_title, d.document_type, d.document_date FROM document_chunks c "
        "JOIN documents d USING (document_id) WHERE c.chunk_id = ANY(%s::uuid[])",
        (chunk_ids,),
    ).fetchall()


def count_for_document(conn: Conn, document_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT chunk_level, count(*) AS n FROM document_chunks WHERE document_id = %s GROUP BY chunk_level",
        (document_id,),
    ).fetchall()
    out = {"PARENT": 0, "CHILD": 0}
    for r in rows:
        out[r["chunk_level"]] = int(r["n"])
    return out
