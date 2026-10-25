"""Ingestion services: register an upload, then PARSE (steps 2-5) and EXTRACT (steps 6-7) as queued jobs."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from legal_workspace.db.pool import Conn

from ..db import chunks as chunk_repo
from ..db import documents as doc_repo
from ..db import jobs as job_repo
from ..db import matters as matter_repo
from ..deps import Deps
from ..domain.authority import CONTRACT_LIKE, authority_for
from ..domain.normalise import fmt_date
from ..domain.subjects import make_contract_ref
from ..domain.types import DocType, PartyRole
from ..errors import BadRequest, DuplicateDocument, ModelOutputInvalid, NotFound, ParseError
from ..storage import sha256_hex
from .chunk import chunk_document
from .classify import Classification, classify_document
from .convert import to_pdf
from .extract import ChunkInput, extract_document
from .pdfio import PageContent, parse_pdf
from .validate import sniff

log = logging.getLogger(__name__)


@dataclass
class RegisterResult:
    document: dict[str, Any] | None = None
    duplicate: bool = False
    duplicate_of: str | None = None
    filename: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------------- 1. register
def register_upload(
    conn: Conn, deps: Deps, *, matter_id: str, batch_seq: int, filename: str | None, data: bytes,
    queue: bool = True,
) -> RegisterResult:  # fmt: skip
    """Validate, de-duplicate (SHA-256), store the original and queue PARSE. Duplicates are recorded, not errors."""
    matter_repo.get_matter(conn, matter_id)
    info = sniff(data, filename, deps.settings.max_upload_mb * 1024 * 1024)
    sha = sha256_hex(data)
    doc_id_placeholder = sha[:12]
    key = f"matters/{matter_id}/{doc_id_placeholder}-{info.clean_name}".replace(" ", "_")
    uri = deps.storage.put(re.sub(r"[^A-Za-z0-9_./\-]", "_", key), data)
    try:
        doc = doc_repo.create_document(
            conn, matter_id=matter_id, batch_seq=batch_seq, title=info.clean_name, original_filename=info.clean_name,
            mime_type=info.mime, storage_uri=uri, sha256=sha,
        )  # fmt: skip
    except DuplicateDocument as e:
        conn.commit()  # keep the duplicate record
        return RegisterResult(
            duplicate=True, duplicate_of=e.extra.get("document_id"), filename=info.clean_name
        )
    if queue:
        job_repo.enqueue(conn, matter_id, batch_seq, "PARSE", str(doc["document_id"]))
    return RegisterResult(document=doc, filename=info.clean_name)


# ------------------------------------------------------------------------------------ 2. parse
def _ensure_party(
    conn: Conn, matter_id: str, name: str, role: str, aliases: list[str]
) -> dict[str, Any] | None:
    name = (name or "").strip()
    if not name:
        return None
    try:
        role = PartyRole(role.upper()).value
    except ValueError:
        role = PartyRole.OTHER.value
    existing = matter_repo.resolve_party(conn, matter_id, name)
    if existing:
        if existing["role"] == "OTHER" and role != "OTHER":
            conn.execute("UPDATE parties SET role = %s WHERE party_id = %s", (role, existing["party_id"]))
            existing["role"] = role
        matter_repo.add_aliases(conn, matter_id, existing["party_id"], [name, *aliases])
        return existing
    return matter_repo.add_party(conn, matter_id, name, role, aliases)


def _unique_contract_id(conn: Conn, matter_id: str, document_id: str, wanted: str) -> str:
    taken = {
        r["contract_id"]
        for r in conn.execute(
            "SELECT contract_id FROM documents WHERE matter_id = %s AND contract_id IS NOT NULL AND document_id <> %s",
            (matter_id, document_id),
        ).fetchall()
    }
    if wanted not in taken:
        return wanted
    n = 2
    while f"{wanted}-{n}" in taken:
        n += 1
    return f"{wanted}-{n}"


def text_fingerprint(pages: list[PageContent]) -> str:
    norm = "\n".join(" ".join(p.text.split()).lower() for p in pages)
    return hashlib.sha256(norm.encode()).hexdigest()


def _context_header(title: str, doc_date: Any, matter_title: str, ref: str | None) -> str:
    bits = [title, fmt_date(doc_date) if doc_date else None, matter_title, ref]
    return "[" + " | ".join(b for b in bits if b) + "]"


def run_parse(conn: Conn, deps: Deps, document_id: str) -> dict[str, Any]:
    """Convert -> parse/OCR -> classify -> chunk -> embed. Idempotent: safe to re-run after a crash."""
    t0 = time.monotonic()
    s = deps.settings
    doc = doc_repo.get_document(conn, document_id)
    matter = matter_repo.get_matter(conn, str(doc["matter_id"]))
    matter_id = str(doc["matter_id"])
    doc_repo.update_document(conn, document_id, status="PROCESSING", error_message=None)
    conn.commit()

    data = deps.storage.read(doc["storage_uri"])
    info = sniff(data, doc["original_filename"], s.max_upload_mb * 1024 * 1024)
    converted = to_pdf(info, data)
    pdf_uri = deps.storage.put(f"matters/{matter_id}/{str(document_id)[:8]}-document.pdf", converted.pdf)
    t_conv = time.monotonic()

    pages, warnings = parse_pdf(converted.pdf, ocr_min_chars=s.ocr_min_chars)
    if sum(len(p.text.strip()) for p in pages) < 20:
        raise ParseError("no readable text was found (blank pages, or a scan and OCR is not installed)")
    text_sha = text_fingerprint(pages)
    t_parse = time.monotonic()

    known = [
        {"name": p["canonical_name"], "role": p["role"]} for p in matter_repo.list_parties(conn, matter_id)
    ]
    try:
        cls: Classification = classify_document(
            deps.llm, first_pages_text="\n".join(p.text for p in pages[:2]), last_page_text=pages[-1].text,
            filename=doc["original_filename"], known_parties=known, fixture_key=text_sha,
            fixture_alt=f"file:{doc['original_filename']}",
        )  # fmt: skip
    except ModelOutputInvalid as e:  # pragma: no cover - classify swallows this; belt and braces
        raise ParseError(f"classification failed: {e.detail}") from e
    t_cls = time.monotonic()

    # parties and aliases (resolved against the matter's party list; new parties are added)
    for p in cls.parties:
        _ensure_party(conn, matter_id, p["name"], p.get("role", "OTHER"), list(p.get("aliases") or []))
    for t in cls.defined_terms:
        owner = matter_repo.resolve_party(conn, matter_id, t["party"])
        if owner:
            matter_repo.add_aliases(conn, matter_id, str(owner["party_id"]), [t["term"]])
    author = matter_repo.resolve_party(conn, matter_id, cls.author) if cls.author else None

    authority, low_conf = authority_for(cls.doc_type, cls.confidence, s.classification_min_confidence)
    reasons = list(cls.notes)
    needs_review = low_conf
    if low_conf:
        reasons.append(
            f"classification confidence {cls.confidence:.2f} below {s.classification_min_confidence}: treated as correspondence"
        )
    low_ocr = [
        p.number for p in pages if p.ocr_confidence is not None and p.ocr_confidence < s.ocr_low_confidence
    ]
    if low_ocr:
        needs_review = True
        reasons.append(f"low OCR confidence on page(s) {low_ocr}")
    if cls.doc_type == DocType.AMENDMENT and not cls.amends:
        reasons.append("amendment does not say which agreement it amends")
    reasons += warnings

    contract_id, aliases = None, []
    if cls.doc_type in CONTRACT_LIKE:
        ref = make_contract_ref(cls.title, cls.doc_type, cls.document_date)
        contract_id = _unique_contract_id(conn, matter_id, document_id, ref.contract_id)
        aliases = sorted(ref.aliases | {contract_id})

    doc_repo.update_document(
        conn, document_id, title=cls.title[:300] or doc["original_filename"], document_type=cls.doc_type.value,
        authority_class=authority.value, document_date=cls.document_date,
        author_party_id=str(author["party_id"]) if author else None, signed_by_all_parties=cls.signed_by_all,
        classification_confidence=cls.confidence, contract_id=contract_id, contract_aliases=aliases,
        amends_ref=cls.amends or None, defined_terms=cls.defined_terms, pdf_uri=pdf_uri, text_sha=text_sha,
        total_pages=len(pages), needs_review=needs_review, review_reason="; ".join(reasons) or None,
    )  # fmt: skip
    doc_repo.save_pages(
        conn, document_id,
        [
            {"page_number": p.number, "page_text": p.text, "extraction_method": p.method, "ocr_confidence": p.ocr_confidence,
             "page_width": p.width, "page_height": p.height}
            for p in pages
        ],
    )  # fmt: skip

    drafts = chunk_document(cls.doc_type, pages)
    if not drafts:
        raise ParseError("the document produced no text chunks")
    title = cls.title[:120] or doc["original_filename"]
    rows: list[dict[str, Any]] = []
    for d in drafts:
        rows.append(
            {
                "level": d.level, "ordinal": d.ordinal, "ref": d.ref, "heading": d.heading, "text": d.text,
                "header": _context_header(title, cls.document_date, matter["title"], d.ref), "page_start": d.page_start,
                "page_end": d.page_end, "char_start": d.char_start, "char_end": d.char_end, "bboxes": d.bboxes,
                "tokens": d.tokens, "parent": d.parent, "embedding": None,
            }
        )  # fmt: skip
    child_idx = [i for i, r in enumerate(rows) if r["level"] == "CHILD"]
    vectors = deps.embedder.embed(
        [rows[i]["header"] + "\n" + " ".join(rows[i]["text"].split()) for i in child_idx]
    )
    for i, v in zip(child_idx, vectors, strict=True):
        rows[i]["embedding"] = v
    t_emb = time.monotonic()

    chunk_repo.delete_for_document(conn, document_id)
    chunk_repo.insert_chunks(
        conn, matter_id=matter_id, document_id=document_id, batch_seq=doc["batch_seq"], drafts=rows
    )
    job_repo.enqueue(conn, matter_id, doc["batch_seq"], "EXTRACT", document_id)

    for fname, payload in converted.attachments:  # e-mail attachments become documents in the same batch
        res = register_upload(
            conn, deps, matter_id=matter_id, batch_seq=doc["batch_seq"], filename=fname, data=payload
        )
        log.info("attachment %s registered (duplicate=%s)", fname, res.duplicate)

    return {
        "convert": int((t_conv - t0) * 1000), "parse": int((t_parse - t_conv) * 1000),
        "classify": int((t_cls - t_parse) * 1000), "chunk_embed": int((t_emb - t_cls) * 1000), "pages": len(pages),
        "chunks": len(rows),
    }  # fmt: skip


# ---------------------------------------------------------------------------------- 3. extract
def run_extract(conn: Conn, deps: Deps, document_id: str) -> dict[str, Any]:
    doc = doc_repo.get_document(conn, document_id)
    if not doc["document_type"]:
        raise NotFound("document has not been parsed yet")
    matter_id = str(doc["matter_id"])
    children = chunk_repo.list_children(conn, document_id)
    pages = {p["page_number"]: p["page_text"] for p in doc_repo.get_pages(conn, document_id)}
    parties = [p["canonical_name"] for p in matter_repo.list_parties(conn, matter_id)]
    result = extract_document(
        deps.llm, doc_type=DocType(doc["document_type"]), title=doc["title"],
        doc_date=fmt_date(doc["document_date"]) if doc["document_date"] else "", parties=parties,
        chunks=[ChunkInput(c["structural_ref"], c["page_start"], c["chunk_text"]) for c in children], pages=pages,
        window_tokens=deps.settings.extract_window_tokens, quote_threshold=deps.settings.quote_match_threshold,
        fixture_key=doc["text_sha"], fixture_alt=f"file:{doc['original_filename']}",
    )  # fmt: skip
    doc_repo.save_extraction(conn, document_id, result.items, result.dropped, result.model_info)
    flags = {}
    if result.failed_windows:
        flags = {
            "needs_review": True,
            "review_reason": f"{result.failed_windows} of {result.windows} extraction windows failed",
        }
    doc_repo.update_document(conn, document_id, status="EXTRACTED", **flags)
    return {
        "items": len(result.items),
        "dropped": len(result.dropped),
        "windows": result.windows,
        **result.model_info,
    }


# ---------------------------------------------------------------------------------- 4. commit
def commit_batch(conn: Conn, matter_id: str, batch_seq: int) -> dict[str, Any]:
    """Close the batch for uploads and queue its RECONCILE job (it waits for every other job of the batch)."""
    batch = matter_repo.get_batch(conn, matter_id, batch_seq)
    if batch["status"] != "OPEN":
        raise BadRequest(f"batch {batch_seq} is already {batch['status']}")
    n = conn.execute(
        "SELECT count(*) AS n FROM documents WHERE matter_id = %s AND batch_seq = %s", (matter_id, batch_seq)
    ).fetchone()
    assert n is not None
    if n["n"] == 0:
        raise BadRequest("the batch has no documents; upload at least one file before committing")
    with conn.transaction():
        matter_repo.set_batch_status(conn, matter_id, batch_seq, "PROCESSING")
        job_repo.enqueue(conn, matter_id, batch_seq, "RECONCILE")
    return {"batch_seq": batch_seq, "status": "PROCESSING", "documents": n["n"]}


@dataclass
class UploadSummary:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


def retry_batch(conn: Conn, matter_id: str, batch_seq: int) -> int:
    """Re-queue every failed job of a batch (e.g. after the model server was restored). Returns jobs re-queued."""
    batch = matter_repo.get_batch(conn, matter_id, batch_seq)
    if batch["status"] not in ("PROCESSING", "FAILED"):
        raise BadRequest(
            f"batch {batch_seq} is {batch['status']}; only a processing or failed batch can be retried"
        )
    with conn.transaction():
        rows = conn.execute(
            "UPDATE ingestion_jobs SET status = 'QUEUED', attempts = 0, last_error = NULL, locked_at = NULL, finished_at = NULL "
            "WHERE matter_id = %s AND batch_seq = %s AND status = 'FAILED' RETURNING document_id, stage",
            (matter_id, batch_seq),
        ).fetchall()
        for r in rows:
            if r["document_id"]:
                doc_repo.update_document(
                    conn,
                    str(r["document_id"]),
                    status="PENDING" if r["stage"] == "PARSE" else "PROCESSING",
                    error_message=None,
                )
        if rows and batch["status"] == "FAILED":
            matter_repo.set_batch_status(conn, matter_id, batch_seq, "PROCESSING")
        if rows and not any(r["stage"] == "RECONCILE" for r in rows):
            job_repo.enqueue(conn, matter_id, batch_seq, "RECONCILE")  # no-op when it still exists
    return len(rows)
