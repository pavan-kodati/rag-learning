"""Documents, pages, duplicates and the contract / notice registries."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from legal_workspace.db.pool import Conn

from ..domain.subjects import ContractRef, NoticeRef, party_slug
from ..errors import BatchClosed, DuplicateDocument, NotFound

Row = dict[str, Any]


def create_document(
    conn: Conn,
    *,
    matter_id: str,
    batch_seq: int,
    title: str,
    original_filename: str,
    mime_type: str | None,
    storage_uri: str,
    sha256: str,
) -> Row:
    """Register an upload. Raises DuplicateDocument (and records it for the batch report) on a repeat."""
    duplicate_of = None
    row: Row | None = None
    with conn.transaction():
        batch = conn.execute(
            "SELECT status FROM ingestion_batches WHERE matter_id = %s AND batch_seq = %s FOR SHARE",
            (matter_id, batch_seq),
        ).fetchone()
        if batch is None:
            raise NotFound(f"batch {batch_seq} not found")
        if batch["status"] != "OPEN":
            raise BatchClosed(f"batch {batch_seq} is {batch['status']}")
        existing = conn.execute(
            "SELECT document_id, status FROM documents WHERE matter_id = %s AND sha256 = %s",
            (matter_id, sha256),
        ).fetchone()
        if existing and existing["status"] == "FAILED":
            # a file that failed earlier may be uploaded again (e.g. after the model server was fixed)
            conn.execute("DELETE FROM documents WHERE document_id = %s", (existing["document_id"],))
            existing = None
        if existing:
            duplicate_of = existing["document_id"]
        else:
            try:
                with conn.transaction():
                    row = conn.execute(
                        "INSERT INTO documents (matter_id, batch_seq, title, original_filename, mime_type, storage_uri, sha256) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (matter_id, batch_seq, title, original_filename, mime_type, storage_uri, sha256),
                    ).fetchone()
            except UniqueViolation:  # lost a race with a parallel identical upload
                other = conn.execute(
                    "SELECT document_id FROM documents WHERE matter_id = %s AND sha256 = %s",
                    (matter_id, sha256),
                ).fetchone()
                assert other is not None
                duplicate_of = other["document_id"]
        if duplicate_of is not None:
            _record_duplicate(conn, matter_id, batch_seq, original_filename, sha256, duplicate_of)
    if duplicate_of is not None:  # raised after commit so the duplicate record is kept
        raise DuplicateDocument(
            f"{original_filename!r} is already in this matter", document_id=str(duplicate_of)
        )
    assert row is not None
    return row


def _record_duplicate(conn: Conn, matter_id: str, batch_seq: int, filename: str, sha: str, of: Any) -> None:
    conn.execute(
        "INSERT INTO batch_duplicates (matter_id, batch_seq, original_filename, sha256, duplicate_of_document_id) "
        "VALUES (%s,%s,%s,%s,%s)",
        (matter_id, batch_seq, filename, sha, of),
    )


def get_document(conn: Conn, document_id: str) -> Row:
    try:
        row = conn.execute("SELECT * FROM documents WHERE document_id = %s", (document_id,)).fetchone()
    except psycopg.errors.InvalidTextRepresentation as e:
        raise NotFound(f"document {document_id!r} not found") from e
    if row is None:
        raise NotFound(f"document {document_id} not found")
    return row


def list_documents(conn: Conn, matter_id: str, batch_seq: int | None = None) -> list[Row]:
    if batch_seq is None:
        return conn.execute(
            "SELECT * FROM documents WHERE matter_id = %s ORDER BY batch_seq, document_date NULLS LAST, created_at",
            (matter_id,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM documents WHERE matter_id = %s AND batch_seq = %s ORDER BY document_date NULLS LAST, created_at",
        (matter_id, batch_seq),
    ).fetchall()


def list_duplicates(conn: Conn, matter_id: str, batch_seq: int) -> list[Row]:
    return conn.execute(
        "SELECT * FROM batch_duplicates WHERE matter_id = %s AND batch_seq = %s ORDER BY duplicate_id",
        (matter_id, batch_seq),
    ).fetchall()


_UPDATABLE = {
    "title", "document_type", "authority_class", "document_date", "author_party_id", "signed_by_all_parties",
    "classification_confidence", "contract_id", "contract_aliases", "amends_ref", "amends_contract_id", "defined_terms",
    "pdf_uri", "text_sha", "total_pages", "status", "needs_review", "review_reason", "error_message", "mime_type",
}  # fmt: skip


def update_document(conn: Conn, document_id: str, **fields: Any) -> None:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"cannot update columns {sorted(bad)}")
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    values = [Jsonb(v) if k == "defined_terms" else v for k, v in fields.items()]
    conn.execute(f"UPDATE documents SET {sets} WHERE document_id = %s", (*values, document_id))  # noqa: S608


def save_pages(conn: Conn, document_id: str, pages: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM document_pages WHERE document_id = %s", (document_id,))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO document_pages (document_id, page_number, page_text, extraction_method, ocr_confidence, "
            "page_width, page_height) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    document_id,
                    p["page_number"],
                    p["page_text"],
                    p["extraction_method"],
                    p.get("ocr_confidence"),
                    p.get("page_width"),
                    p.get("page_height"),
                )
                for p in pages
            ],
        )


def get_pages(conn: Conn, document_id: str) -> list[Row]:
    return conn.execute(
        "SELECT * FROM document_pages WHERE document_id = %s ORDER BY page_number", (document_id,)
    ).fetchall()


def get_page(conn: Conn, document_id: str, page: int) -> Row:
    row = conn.execute(
        "SELECT * FROM document_pages WHERE document_id = %s AND page_number = %s", (document_id, page)
    ).fetchone()
    if row is None:
        raise NotFound(f"page {page} of document {document_id} not found")
    return row


def save_extraction(
    conn: Conn, document_id: str, items: list[Any], dropped: list[Any], model_info: dict
) -> None:
    conn.execute(
        "INSERT INTO document_extractions (document_id, items, dropped, model_info) VALUES (%s,%s,%s,%s) "
        "ON CONFLICT (document_id) DO UPDATE SET items = EXCLUDED.items, dropped = EXCLUDED.dropped, "
        "model_info = EXCLUDED.model_info, created_at = now()",
        (document_id, Jsonb(items), Jsonb(dropped), Jsonb(model_info)),
    )


def get_extraction(conn: Conn, document_id: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM document_extractions WHERE document_id = %s", (document_id,)
    ).fetchone()


# ------------------------------------------------------------------------------------- registries
def contract_registry(conn: Conn, matter_id: str) -> list[ContractRef]:
    rows = conn.execute(
        "SELECT contract_id, title, document_date, contract_aliases FROM documents "
        "WHERE matter_id = %s AND contract_id IS NOT NULL AND status <> 'FAILED' ORDER BY document_date NULLS LAST",
        (matter_id,),
    ).fetchall()
    return [
        ContractRef(r["contract_id"], r["title"], r["document_date"], set(r["contract_aliases"]))
        for r in rows
    ]


def notice_registry(conn: Conn, matter_id: str) -> list[NoticeRef]:
    rows = conn.execute(
        "SELECT d.document_date, p.canonical_name FROM documents d JOIN parties p ON p.party_id = d.author_party_id "
        "WHERE d.matter_id = %s AND d.document_type IN ('LEGAL_NOTICE','REPLY_NOTICE') AND d.document_date IS NOT NULL "
        "AND d.status <> 'FAILED'",
        (matter_id,),
    ).fetchall()
    out = []
    for r in rows:
        slug = party_slug(r["canonical_name"])
        d: date = r["document_date"]
        out.append(NoticeRef(f"{d.isoformat()}-{slug}", d, slug))
    return out
