"""Review queue (blueprint §8.7) and the audit log."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from legal_workspace.db.pool import Conn

from ...db import audit as audit_repo
from ...db import matters as matter_repo
from ...deps import Deps
from ...memory import review
from ..deps import audit, get_conn, get_deps
from ..security import User, current_user, require

router = APIRouter(tags=["review"])


class ReviewIn(BaseModel):
    action: str = Field(pattern="^(CONFIRM|SUPERSEDE_OTHERS|DISPUTE|EVIDENCE_ONLY|CORRECT_VALUE|WITHDRAW)$")
    reason: str = Field(min_length=1, max_length=1000)
    value: str | None = Field(default=None, max_length=500)


@router.get("/matters/{matter_id}/review-queue")
def review_queue(
    matter_id: UUID,
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    matter_repo.get_matter(conn, str(matter_id))
    items = review.list_items(conn, str(matter_id), deps.settings.ocr_low_confidence)
    return {"count": len(items), "items": items}


@router.post("/facts/{assertion_id}/review")
def review_fact(
    assertion_id: UUID,
    body: ReviewIn,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> dict[str, Any]:  # noqa: B008
    row = conn.execute(
        "SELECT matter_id FROM matter_fact_assertions WHERE assertion_id = %s", (str(assertion_id),)
    ).fetchone()
    if row is None:
        from ...errors import NotFound

        raise NotFound("fact not found")
    out = review.resolve_fact(
        conn,
        str(row["matter_id"]),
        str(assertion_id),
        action=body.action,
        reviewer=user.username,
        reason=body.reason,
        value=body.value,
    )
    audit(
        conn,
        request,
        user,
        "fact.review",
        matter_id=row["matter_id"],
        entity="fact",
        entity_id=assertion_id,
        detail={"action": body.action},
    )
    return out


@router.post("/documents/{document_id}/review-confirm", status_code=204)
def confirm_document(
    document_id: UUID,
    request: Request,
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("analyst")),
) -> None:  # noqa: B008
    row = conn.execute(
        "SELECT matter_id FROM documents WHERE document_id = %s", (str(document_id),)
    ).fetchone()
    if row is None:
        from ...errors import NotFound

        raise NotFound("document not found")
    review.confirm_document(conn, str(row["matter_id"]), str(document_id))
    audit(
        conn,
        request,
        user,
        "document.review_confirm",
        matter_id=row["matter_id"],
        entity="document",
        entity_id=document_id,
    )


@router.get("/audit")
def audit_log(
    matter_id: UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
    conn: Conn = Depends(get_conn),
    user: User = Depends(require("admin")),
) -> list[dict[str, Any]]:  # noqa: B008
    return audit_repo.list_entries(conn, str(matter_id) if matter_id else None, limit)
