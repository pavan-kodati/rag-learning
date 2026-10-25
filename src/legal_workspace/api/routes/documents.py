"""Documents: metadata, the normalised PDF, page text, page images and quote highlights (click-to-source)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from legal_workspace.db.pool import Conn

from ...db import documents as doc_repo
from ...deps import Deps
from ...errors import NotFound
from ...ingestion.pdfio import highlight_rects, page_png
from ..deps import get_conn, get_deps
from ..security import User, current_user

router = APIRouter(tags=["documents"])


def _doc(conn: Conn, document_id: UUID) -> dict[str, Any]:
    return doc_repo.get_document(conn, str(document_id))


def _pdf_bytes(deps: Deps, doc: dict[str, Any]) -> bytes:
    if not doc["pdf_uri"]:
        raise NotFound("this document has not been converted to PDF yet")
    return deps.storage.read(doc["pdf_uri"])


@router.get("/documents/{document_id}")
def get_document(
    document_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> dict[str, Any]:  # noqa: B008
    d = _doc(conn, document_id)
    pages = conn.execute(
        "SELECT page_number, extraction_method, ocr_confidence FROM document_pages WHERE document_id = %s ORDER BY page_number",
        (str(document_id),),
    ).fetchall()
    return {k: v for k, v in d.items() if k not in ("storage_uri", "pdf_uri", "text_sha")} | {"pages": pages}


@router.get("/documents/{document_id}/pdf")
def get_pdf(
    document_id: UUID,
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> Response:  # noqa: B008
    d = _doc(conn, document_id)
    name = (d["original_filename"].rsplit(".", 1)[0] or "document") + ".pdf"
    return Response(
        _pdf_bytes(deps, d),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{name}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/documents/{document_id}/pages/{page}")
def get_page(
    document_id: UUID,
    page: int,
    conn: Conn = Depends(get_conn),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    """Page text, size, the chunks on the page (with boxes) and the facts that cite it."""
    d = _doc(conn, document_id)
    p = doc_repo.get_page(conn, str(document_id), page)
    chunks = conn.execute(
        "SELECT chunk_id, structural_ref, chunk_level, page_start, page_end, bboxes FROM document_chunks WHERE document_id = %s AND chunk_level = 'CHILD' "
        "AND page_start <= %s AND page_end >= %s ORDER BY ordinal",
        (str(document_id), page, page),
    ).fetchall()
    facts = conn.execute(
        "SELECT assertion_id, assertion_text, source_quote, state, evidence_only FROM matter_fact_assertions WHERE originating_document_id = %s AND source_page = %s ORDER BY created_at",
        (str(document_id), page),
    ).fetchall()
    return {
        "document_id": str(document_id), "title": d["title"], "page": page, "total_pages": d["total_pages"], "text": p["page_text"],
        "extraction_method": p["extraction_method"], "ocr_confidence": p["ocr_confidence"], "width": p["page_width"], "height": p["page_height"],
        "chunks": [{**c, "bboxes": [b for b in (c["bboxes"] or []) if b["page"] == page]} for c in chunks], "facts": facts,
    }  # fmt: skip


@router.get("/documents/{document_id}/pages/{page}/image")
def get_page_image(
    document_id: UUID,
    page: int,
    scale: float = Query(1.6, ge=0.5, le=3.0),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> Response:  # noqa: B008
    d = _doc(conn, document_id)
    doc_repo.get_page(conn, str(document_id), page)  # 404 for a page that does not exist
    return Response(
        page_png(_pdf_bytes(deps, d), page, scale),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/documents/{document_id}/pages/{page}/highlight")
def get_highlight(
    document_id: UUID,
    page: int,
    quote: str = Query(..., min_length=3, max_length=1000),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    """Rectangles (PDF points, top-left origin) covering `quote` on the page; falls back to the containing chunk's boxes."""
    d = _doc(conn, document_id)
    doc_repo.get_page(conn, str(document_id), page)
    out = highlight_rects(_pdf_bytes(deps, d), page, quote)
    if not out["found"]:
        from ...grounding.verify import norm

        q = norm(quote)
        for c in conn.execute(
            "SELECT chunk_text, bboxes FROM document_chunks WHERE document_id = %s AND chunk_level = 'CHILD' AND page_start <= %s AND page_end >= %s",
            (str(document_id), page, page),
        ).fetchall():
            if q and q in norm(c["chunk_text"]):
                out["rects"] = [b for b in (c["bboxes"] or []) if b["page"] == page]
                out["found"] = bool(out["rects"])
                out["approximate"] = True
                break
    return out
