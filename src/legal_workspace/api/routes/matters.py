"""Matters, parties, batches, uploads, commit and the What-Changed report."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from legal_workspace.db.pool import Conn

from ...db import documents as doc_repo
from ...db import jobs as job_repo
from ...db import matters as matter_repo
from ...deps import Deps
from ...errors import Conflict, PayloadTooLarge, UnsupportedMedia, ValidationFailed
from ...ingestion import service
from ...memory import queries, review
from ...memory.reports import build_changes, render_text
from .. import metrics
from ..deps import audit, get_conn, get_deps
from ..security import User, current_user, require

router = APIRouter(tags=["matters"])
PartyRoleName = str


class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="OTHER", pattern="^(PLAINTIFF|DEFENDANT|PETITIONER|RESPONDENT|OTHER)$")
    aliases: list[str] = Field(default_factory=list, max_length=20)


class MatterIn(BaseModel):
    matter_number: str = Field(min_length=1, max_length=100, examples=["CS(COMM) 123/2025"])
    title: str = Field(min_length=1, max_length=300)
    matter_type: str = Field(pattern="^(BREACH|PAYMENT_RECOVERY|TERMINATION_INJUNCTION)$")
    forum: str | None = Field(default=None, max_length=150)
    parties: list[PartyIn] = Field(default_factory=list, max_length=20)


class BatchIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("storage_uri", "pdf_uri")}


def matter_or_404(conn: Conn, matter_id: UUID) -> dict[str, Any]:
    return matter_repo.get_matter(conn, str(matter_id))


@router.post("/matters", status_code=201)
def create_matter(
    body: MatterIn,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    m = matter_repo.create_matter(conn, matter_number=body.matter_number, title=body.title, matter_type=body.matter_type, forum=body.forum,
                                  created_by=user.username, parties=[p.model_dump() for p in body.parties])  # fmt: skip
    audit(
        conn,
        request,
        user,
        "matter.create",
        matter_id=m["matter_id"],
        entity="matter",
        entity_id=m["matter_id"],
        detail={"number": m["matter_number"]},
    )
    return {**m, "parties": matter_repo.list_parties(conn, str(m["matter_id"]))}


@router.get("/matters")
def list_matters(conn: Conn = Depends(get_conn), user: User = Depends(current_user)) -> list[dict[str, Any]]:  # noqa: B008
    return matter_repo.list_matters(conn)


@router.get("/matters/{matter_id}")
def get_matter(
    matter_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> dict[str, Any]:  # noqa: B008
    m = matter_or_404(conn, matter_id)
    return {**m, "parties": matter_repo.list_parties(conn, str(matter_id)), "batches": matter_repo.list_batches(conn, str(matter_id)),
            "latest_batch": matter_repo.latest_committed_seq(conn, str(matter_id))}  # fmt: skip


@router.delete("/matters/{matter_id}", status_code=204)
def delete_matter(
    matter_id: UUID,
    request: Request,
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(require("admin")),
) -> None:  # noqa: B008
    m = matter_or_404(conn, matter_id)
    busy = conn.execute(
        "SELECT count(*) AS n FROM ingestion_jobs WHERE matter_id = %s AND status = 'RUNNING'",
        (str(matter_id),),
    ).fetchone()
    if busy and busy["n"]:
        raise Conflict("documents of this matter are being processed; try again in a moment")
    audit(
        conn,
        request,
        user,
        "matter.delete",
        matter_id=matter_id,
        entity="matter",
        entity_id=matter_id,
        detail={"number": m["matter_number"]},
    )
    conn.execute("DELETE FROM matters WHERE matter_id = %s", (str(matter_id),))
    conn.commit()
    deps.storage.delete_prefix(f"matters/{matter_id}")


@router.get("/matters/{matter_id}/overview")
def overview(
    matter_id: UUID,
    today: date | None = None,
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    """Numbers for the matter header: documents, facts, disputes, overdue directions, review items, next hearing."""
    mid = str(matter_id)
    m = matter_or_404(conn, matter_id)
    latest = matter_repo.latest_committed_seq(conn, mid)
    out: dict[str, Any] = {
        "matter_id": mid,
        "title": m["title"],
        "latest_batch": latest,
        "documents": 0,
        "facts": 0,
        "disputed": 0,
        "overdue": 0,
        "review_items": 0,
        "next_hearing": None,
    }
    docs = conn.execute(
        "SELECT status, count(*) AS n FROM documents WHERE matter_id = %s GROUP BY status", (mid,)
    ).fetchall()
    out["documents"] = sum(r["n"] for r in docs)
    out["documents_by_status"] = {r["status"]: r["n"] for r in docs}
    if latest:
        facts = queries.facts_as_of(conn, mid, latest)
        out["facts"] = len(facts)
        out["disputed"] = sum(1 for f in facts if f["state"] == "DISPUTED")
        ds = queries.directions(conn, mid, latest, today or deps.settings.today())
        out["overdue"] = sum(1 for d in ds if d["status"] == "OVERDUE")
        hearings = [d for d in ds if d["kind"] == "NEXT_HEARING" and not d["superseded"] and d["due_date"]]
        if hearings:
            h = max(hearings, key=lambda d: d["order_date"])
            out["next_hearing"] = {"date": h["due_date"].isoformat(), "text": h["assertion_text"]}
    out["review_items"] = len(review.list_items(conn, mid, deps.settings.ocr_low_confidence))
    return out


# ------------------------------------------------------------------------------------------ parties
@router.get("/matters/{matter_id}/parties")
def parties(
    matter_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> list[dict[str, Any]]:  # noqa: B008
    matter_or_404(conn, matter_id)
    return matter_repo.list_parties(conn, str(matter_id))


@router.post("/matters/{matter_id}/parties", status_code=201)
def add_party(
    matter_id: UUID,
    body: PartyIn,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    matter_or_404(conn, matter_id)
    p = matter_repo.add_party(conn, str(matter_id), body.name, body.role, body.aliases)
    audit(
        conn,
        request,
        user,
        "party.add",
        matter_id=matter_id,
        entity="party",
        entity_id=p["party_id"],
        detail={"name": body.name, "role": body.role},
    )
    return p


# ------------------------------------------------------------------------------------------ batches
@router.post("/matters/{matter_id}/batches", status_code=201)
def open_batch(
    matter_id: UUID,
    request: Request,
    body: BatchIn | None = None,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    matter_or_404(conn, matter_id)
    b = matter_repo.open_batch(conn, str(matter_id), body.label if body else None)
    audit(conn, request, user, "batch.open", matter_id=matter_id, entity="batch", entity_id=b["batch_seq"])
    return b


@router.get("/matters/{matter_id}/batches")
def list_batches(
    matter_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> list[dict[str, Any]]:  # noqa: B008
    matter_or_404(conn, matter_id)
    return matter_repo.list_batches(conn, str(matter_id))


@router.get("/matters/{matter_id}/batches/{batch_seq}")
def get_batch(
    matter_id: UUID,
    batch_seq: int,
    conn: Conn = Depends(get_conn),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    matter_or_404(conn, matter_id)
    b = matter_repo.get_batch(conn, str(matter_id), batch_seq)
    docs = doc_repo.list_documents(conn, str(matter_id), batch_seq)
    jobs = conn.execute(
        "SELECT document_id, stage, status, attempts, last_error FROM ingestion_jobs WHERE matter_id = %s AND batch_seq = %s ORDER BY job_id",
        (str(matter_id), batch_seq),
    ).fetchall()
    stage_by_doc: dict[str, str] = {}
    for j in jobs:
        if j["document_id"] and j["status"] in ("QUEUED", "RUNNING"):
            stage_by_doc.setdefault(str(j["document_id"]), f"{j['stage']} ({j['status'].lower()})")
    return {
        **b, "documents": [{**_clean(d), "current_step": stage_by_doc.get(str(d["document_id"]))} for d in docs],
        "duplicates": doc_repo.list_duplicates(conn, str(matter_id), batch_seq), "progress": job_repo.batch_progress(conn, str(matter_id), batch_seq),
        "reconcile": next((j["status"] for j in jobs if j["stage"] == "RECONCILE"), None),
    }  # fmt: skip


async def _read_limited(f: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        part = await f.read(1024 * 1024)
        if not part:
            break
        size += len(part)
        if size > limit:
            raise PayloadTooLarge(f"{f.filename!r} is larger than {limit // (1024 * 1024)} MB")
        chunks.append(part)
    return b"".join(chunks)


@router.post("/matters/{matter_id}/batches/{batch_seq}/documents", status_code=202)
async def upload_documents(
    matter_id: UUID, batch_seq: int, request: Request, files: list[UploadFile] = File(...),  # noqa: B008
    conn: Conn = Depends(get_conn), deps: Deps = Depends(get_deps), user: User = Depends(require("analyst")),  # noqa: B008
) -> JSONResponse:  # fmt: skip
    """Upload one or more files into an open batch. Duplicates (same SHA-256) are skipped and listed; unreadable types are rejected."""
    matter_or_404(conn, matter_id)
    if not files:
        raise ValidationFailed("no files were uploaded")
    if len(files) > 100:
        raise ValidationFailed("at most 100 files per request")
    limit = deps.settings.max_upload_mb * 1024 * 1024
    accepted, duplicates, rejected = [], [], []
    for f in files:
        name = f.filename or "document"
        try:
            data = await _read_limited(f, limit)
            res = service.register_upload(
                conn, deps, matter_id=str(matter_id), batch_seq=batch_seq, filename=name, data=data
            )
        except (PayloadTooLarge, UnsupportedMedia, ValidationFailed) as e:
            conn.rollback()
            rejected.append({"filename": name, "code": e.code, "reason": e.detail})
            metrics.UPLOADS.labels("rejected").inc()
            continue
        if res.duplicate:
            duplicates.append({"filename": res.filename, "duplicate_of": res.duplicate_of})
            metrics.UPLOADS.labels("duplicate").inc()
        else:
            accepted.append({"document_id": str(res.document["document_id"]), "filename": res.filename})  # type: ignore[index]
            metrics.UPLOADS.labels("accepted").inc()
    if accepted or duplicates:
        audit(conn, request, user, "document.upload", matter_id=matter_id, entity="batch", entity_id=batch_seq,
              detail={"accepted": [a["filename"] for a in accepted], "duplicates": [d["filename"] for d in duplicates], "rejected": [r["filename"] for r in rejected]})  # fmt: skip
    body = {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}
    if accepted:
        return JSONResponse(body, status_code=202)
    if duplicates and not rejected:
        return JSONResponse({**body, "detail": "every file is already in this matter"}, status_code=409)
    code = (
        415
        if any(r["code"] == "unsupported_media_type" for r in rejected)
        else (413 if any(r["code"] == "payload_too_large" for r in rejected) else 422)
    )
    return JSONResponse({**body, "detail": "no file could be accepted"}, status_code=code)


@router.post("/matters/{matter_id}/batches/{batch_seq}/commit", status_code=202)
def commit(
    matter_id: UUID,
    batch_seq: int,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    matter_or_404(conn, matter_id)
    out = service.commit_batch(conn, str(matter_id), batch_seq)
    audit(conn, request, user, "batch.commit", matter_id=matter_id, entity="batch", entity_id=batch_seq)
    return out


@router.post("/matters/{matter_id}/batches/{batch_seq}/retry", status_code=202)
def retry(
    matter_id: UUID,
    batch_seq: int,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    matter_or_404(conn, matter_id)
    n = service.retry_batch(conn, str(matter_id), batch_seq)
    audit(
        conn,
        request,
        user,
        "batch.retry",
        matter_id=matter_id,
        entity="batch",
        entity_id=batch_seq,
        detail={"jobs": n},
    )
    return {"requeued": n}


@router.get("/matters/{matter_id}/batches/{batch_seq}/changes", response_model=None)
def changes(
    matter_id: UUID,
    batch_seq: int,
    format: str = Query("json", pattern="^(json|text)$"),
    conn: Conn = Depends(get_conn),
    user: User = Depends(current_user),
):  # noqa: B008, A002, ANN201
    matter_or_404(conn, matter_id)
    batch = matter_repo.get_batch(conn, str(matter_id), batch_seq)
    if batch["status"] != "COMMITTED":
        raise Conflict(
            f"batch {batch_seq} is {batch['status']}: the report is available once it is committed"
        )
    report = build_changes(conn, str(matter_id), batch_seq)
    return PlainTextResponse(render_text(report)) if format == "text" else report
