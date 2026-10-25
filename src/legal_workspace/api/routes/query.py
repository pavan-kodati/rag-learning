"""Views and questions: gist, chronology, claims, directions, evidence, legal research, ask, hearing brief, facts, traces."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from legal_workspace.db.pool import Conn

from ...corpus.search import search_corpus
from ...db import matters as matter_repo
from ...db import traces as trace_repo
from ...deps import Deps
from ...errors import NotFound, ValidationFailed
from ...grounding.answer import ask as run_ask
from ...grounding.answer import sentences_from_statements
from ...grounding.brief import generate_brief
from ...memory import queries
from ...retrieval import plans
from ...retrieval.types import PlanResult
from .. import metrics
from ..deps import audit, get_conn, get_deps
from ..security import User, current_user

router = APIRouter(tags=["query"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_batch_seq: int | None = Field(default=None, ge=1)
    intent_hint: str | None = Field(default=None, max_length=30)
    today: date | None = None


class BriefIn(BaseModel):
    as_of_batch_seq: int | None = Field(default=None, ge=1)
    today: date | None = None


def _ctx(conn: Conn, matter_id: UUID, as_of: int | None) -> tuple[dict[str, Any], int]:
    m = matter_repo.get_matter(conn, str(matter_id))
    latest = matter_repo.latest_committed_seq(conn, str(matter_id))
    if as_of is not None and not 1 <= as_of <= max(latest, 1):
        raise ValidationFailed(f"as_of must be between 1 and {latest}")
    return m, (as_of or latest)


def _render(conn: Conn, res: PlanResult, deps: Deps) -> dict[str, Any]:
    sents, rejected = sentences_from_statements(
        conn, res.statements, plan=res.plan, threshold=deps.settings.quote_match_threshold
    )
    return {
        "plan": res.plan,
        "title": res.title,
        "sentences": sents,
        "unverified": rejected,
        "notes": res.notes,
        "extras": {k: v for k, v in res.extras.items() if k != "report"}
        | ({"report": res.extras["report"]} if "report" in res.extras else {}),
    }


@router.get("/matters/{matter_id}/gist")
def gist(
    matter_id: UUID,
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    return (
        {"as_of_batch_seq": n, **_render(conn, plans.plan_gist(conn, m, n), deps)}
        if n
        else {
            "as_of_batch_seq": 0,
            "plan": "GIST",
            "sentences": [],
            "notes": ["No batch has been committed yet."],
            "extras": {},
        }
    )


@router.get("/matters/{matter_id}/chronology")
def chronology(
    matter_id: UUID,
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    return (
        {"as_of_batch_seq": n, **_render(conn, plans.plan_chronology(conn, m, n), deps)}
        if n
        else {
            "as_of_batch_seq": 0,
            "plan": "CHRONOLOGY",
            "sentences": [],
            "notes": ["No batch has been committed yet."],
            "extras": {},
        }
    )


@router.get("/matters/{matter_id}/claims")
def claims(
    matter_id: UUID,
    party_id: UUID | None = None,
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    if not n:
        return {
            "as_of_batch_seq": 0,
            "plan": "CLAIMS",
            "sentences": [],
            "notes": ["No batch has been committed yet."],
            "extras": {"by_party": {}},
        }
    party = None
    if party_id:
        row = conn.execute(
            "SELECT canonical_name FROM parties WHERE party_id = %s AND matter_id = %s",
            (str(party_id), str(matter_id)),
        ).fetchone()
        if row is None:
            raise NotFound("party not found in this matter")
        party = row["canonical_name"]
    res = plans.plan_claims(conn, m, n, party)
    out = _render(conn, res, deps)
    for s in out["sentences"]:  # keep the linked evidence (plan meta) on each sentence for the claims board
        s["meta"] = next((st.meta for st in res.statements if st.id == s["id"]), s["meta"])
    return {"as_of_batch_seq": n, **out}


@router.get("/matters/{matter_id}/directions")
def directions(
    matter_id: UUID,
    status: str | None = Query(None, pattern="^(?i)(PENDING|OVERDUE|COMPLIED|NO_DATE|SUPERSEDED)$"),
    today: date | None = None,
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    if not n:
        return {
            "as_of_batch_seq": 0,
            "plan": "DIRECTIONS",
            "sentences": [],
            "notes": ["No batch has been committed yet."],
            "extras": {},
        }
    res = plans.plan_directions(conn, m, n, today or deps.settings.today(), status)
    return {
        "as_of_batch_seq": n,
        "today": (today or deps.settings.today()).isoformat(),
        **_render(conn, res, deps),
    }


@router.get("/matters/{matter_id}/evidence")
def evidence(
    matter_id: UUID,
    q: str = Query("", max_length=500),
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    if not n:
        return {
            "as_of_batch_seq": 0,
            "plan": "EVIDENCE",
            "sentences": [],
            "notes": ["No batch has been committed yet."],
            "extras": {},
        }
    return {
        "as_of_batch_seq": n,
        **_render(conn, plans.plan_evidence(conn, deps.embedder, deps.reranker, m, n, q), deps),
    }


@router.get("/matters/{matter_id}/legal")
def matter_legal(
    matter_id: UUID,
    q: str = Query("", max_length=500),
    as_of: int | None = Query(None, ge=1),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    m, n = _ctx(conn, matter_id, as_of)
    return {
        "as_of_batch_seq": n,
        **_render(conn, plans.plan_legal(conn, deps.embedder, m, max(n, 1), q), deps),
    }


@router.get("/legal/search")
def legal_search(
    q: str = Query("", max_length=500),
    tags: str = Query("", max_length=300),
    k: int = Query(8, ge=1, le=25),
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:  # noqa: B008
    taglist = [t.strip() for t in tags.split(",") if t.strip()]
    rows = search_corpus(conn, deps.embedder, q, tags=taglist, k=k)
    return [{k2: v for k2, v in r.items() if k2 != "tsv"} for r in rows]


@router.post("/matters/{matter_id}/ask")
def ask(
    matter_id: UUID,
    body: AskIn,
    request: Request,
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    out = run_ask(
        conn,
        deps,
        str(matter_id),
        body.question,
        as_of=body.as_of_batch_seq,
        intent_hint=body.intent_hint,
        actor=user.username,
        today=body.today,
    )
    metrics.ANSWERS.labels(out["mode"]).inc()
    metrics.UNVERIFIED.inc(len(out["unverified"]))
    audit(
        conn,
        request,
        user,
        "ask",
        matter_id=matter_id,
        entity="trace",
        entity_id=out["trace_id"],
        detail={"intents": out["intents"]},
    )
    return out


@router.post("/matters/{matter_id}/hearing-brief", response_model=None)
def hearing_brief(
    matter_id: UUID,
    body: BriefIn | None = None,
    format: str = Query("json", pattern="^(json|markdown)$"),
    request: Request = None,  # type: ignore[assignment]
    conn: Conn = Depends(get_conn),
    deps: Deps = Depends(get_deps),
    user: User = Depends(current_user),
):  # noqa: B008, A002, ANN201
    body = body or BriefIn()
    out = generate_brief(
        conn, deps, str(matter_id), as_of=body.as_of_batch_seq, today=body.today, actor=user.username
    )
    audit(
        conn, request, user, "hearing_brief", matter_id=matter_id, entity="trace", entity_id=out["trace_id"]
    )
    return PlainTextResponse(out["markdown"], media_type="text/markdown") if format == "markdown" else out


@router.get("/matters/{matter_id}/facts")
def list_facts(
    matter_id: UUID,
    as_of: int | None = Query(None, ge=1),
    include_evidence: bool = False,
    conn: Conn = Depends(get_conn),
    user: User = Depends(current_user),
) -> dict[str, Any]:  # noqa: B008
    _, n = _ctx(conn, matter_id, as_of)
    if not n:
        return {"as_of_batch_seq": 0, "facts": []}
    rows = queries.facts_as_of(conn, str(matter_id), n, include_evidence=include_evidence)
    return {
        "as_of_batch_seq": n,
        "facts": [
            {
                k: v
                for k, v in r.items()
                if k
                in (
                    "assertion_id",
                    "fact_key",
                    "subject_type",
                    "slot",
                    "assertion_category",
                    "assertion_text",
                    "state",
                    "evidence_only",
                    "derived",
                    "needs_review",
                    "document_title",
                    "source_page",
                    "party_name",
                    "learned_in_batch_seq",
                    "ended_in_batch_seq",
                )
            }
            for r in rows
        ],
    }


@router.get("/facts/{assertion_id}")
def fact_detail(
    assertion_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> dict[str, Any]:  # noqa: B008
    f = conn.execute(
        "SELECT a.*, d.title AS document_title, p.canonical_name AS party_name FROM matter_fact_assertions a JOIN documents d ON d.document_id = a.originating_document_id "
        "LEFT JOIN parties p ON p.party_id = a.asserting_party_id WHERE a.assertion_id = %s", (str(assertion_id),),
    ).fetchone()  # fmt: skip
    if f is None:
        raise NotFound("fact not found")
    history = conn.execute(
        "SELECT l.change_id, l.batch_seq, l.change_type, l.rule_id, l.previous_state, l.new_state, l.reason, l.reviewer, l.created_at, d.title AS caused_by FROM fact_change_log l LEFT JOIN documents d ON d.document_id = l.caused_by_document_id WHERE l.assertion_id = %s ORDER BY l.change_id",
        (str(assertion_id),),
    ).fetchall()
    links = queries.links_for(conn, str(f["matter_id"]), [str(assertion_id)]).get(str(assertion_id), [])
    return {**f, "history": history, "evidence_links": links}


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> dict[str, Any]:  # noqa: B008
    return trace_repo.get_trace(conn, str(trace_id))


@router.get("/matters/{matter_id}/traces")
def list_traces(
    matter_id: UUID, conn: Conn = Depends(get_conn), user: User = Depends(current_user)
) -> list[dict[str, Any]]:  # noqa: B008
    matter_repo.get_matter(conn, str(matter_id))
    return trace_repo.list_traces(conn, str(matter_id))
