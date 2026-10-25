"""Question answering: route -> plan(s) -> verify -> trace (blueprint §9, §10)."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from legal_workspace.db.pool import Conn

from ..db import matters as matter_repo
from ..db import traces as trace_repo
from ..deps import Deps
from ..errors import ValidationFailed
from ..retrieval import plans
from ..retrieval.router import route
from ..retrieval.types import Intent, PlanResult, Statement
from .factual import answer_factual, page_texts
from .narrative import narrate
from .verify import verify_law_citation, verify_statement_citation

log = logging.getLogger(__name__)
MAX_QUESTION_CHARS = 2000
OUT_OF_SCOPE_TEXT = (
    "This workspace covers Indian commercial and contract litigation (breach, payment / recovery, termination / injunction). "
    "That question is outside its scope, so it has not been answered."
)
# plans whose statements may legitimately show superseded items (struck through)
_SHOW_SUPERSEDED = {"CHRONOLOGY", "WHAT_CHANGED"}


def sentences_from_statements(
    conn: Conn, statements: list[Statement], *, plan: str, threshold: int = 90,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:  # fmt: skip
    """Verify every citation of every statement; returns (verified sentences, rejected)."""
    pairs = {
        (c.document_id, c.page)
        for s in statements
        for c in s.citations
        if c.source_kind == "matter" and c.document_id and c.page
    }
    pages = page_texts(conn, {(str(d), int(p)) for d, p in pairs})
    known: dict[str, Any] | None = None
    out: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for s in statements:
        if s.state == "SUPERSEDED" and plan not in _SHOW_SUPERSEDED:
            continue
        reasons: list[str] = []
        for c in s.citations:
            if c.source_kind == "law":
                if known is None:
                    from ..corpus.search import known_authorities

                    known = known_authorities(conn)
                reasons += verify_law_citation(c.source_id, known).reasons
            else:
                reasons += verify_statement_citation(
                    pages, str(c.document_id) if c.document_id else None, c.page, c.quote, threshold
                ).reasons
        if reasons:
            rejected.append({"id": s.id, "text": s.text, "reasons": reasons})
            continue
        status = "INFO" if not s.citations else ("POSSIBLE" if s.kind == "possible_evidence" else "VERIFIED")
        out.append({"id": s.id, "text": s.text, "status": status, "state": s.state, "kind": s.kind, "plan": plan,
                    "citations": [c.to_dict() for c in s.citations], "superseded_by": s.superseded_by, "meta": s.meta})  # fmt: skip
    return out, rejected


def run_plan(
    conn: Conn,
    deps: Deps,
    matter: dict[str, Any],
    intent: Intent,
    question: str,
    as_of: int,
    today: date,
) -> PlanResult:
    if intent == Intent.GIST:
        return plans.plan_gist(conn, matter, as_of)
    if intent == Intent.CHRONOLOGY:
        return plans.plan_chronology(conn, matter, as_of)
    if intent == Intent.CLAIMS:
        return plans.plan_claims(conn, matter, as_of)
    if intent == Intent.EVIDENCE:
        return plans.plan_evidence(conn, deps.embedder, deps.reranker, matter, as_of, question)
    if intent == Intent.DIRECTIONS:
        return plans.plan_directions(conn, matter, as_of, today)
    if intent == Intent.WHAT_CHANGED:
        return plans.plan_what_changed(conn, matter, as_of)
    if intent == Intent.LEGAL_RESEARCH:
        return plans.plan_legal(conn, deps.embedder, matter, as_of, question)
    raise ValueError(f"no structured plan for {intent}")


def ask(
    conn: Conn, deps: Deps, matter_id: str, question: str, *, as_of: int | None = None, intent_hint: str | None = None,
    actor: str | None = None, today: date | None = None,
) -> dict[str, Any]:  # fmt: skip
    q = " ".join((question or "").split())
    if not q:
        raise ValidationFailed("the question is empty")
    if len(q) > MAX_QUESTION_CHARS:
        raise ValidationFailed(f"the question is longer than {MAX_QUESTION_CHARS} characters")
    t0 = time.monotonic()
    matter = matter_repo.get_matter(conn, matter_id)
    latest = matter_repo.latest_committed_seq(conn, matter_id)
    if as_of is not None and not 1 <= as_of <= max(latest, 1):
        raise ValidationFailed(f"as_of_batch_seq must be between 1 and {latest}")
    as_of = as_of or latest
    today = today or deps.settings.today()

    base: dict[str, Any] = {"question": q, "as_of_batch_seq": as_of, "intents": [], "routed_by": "RULES", "answer_sentences": [], "sections": [], "not_found": [],
            "superseded_notes": [], "unverified": [], "notes": [], "mode": "structured", "trace_id": None}  # fmt: skip
    if latest == 0:
        base["not_found"] = [
            "No documents have been committed to this matter yet. Upload a batch and commit it first."
        ]
        return base

    rt = route(q, deps.llm, intent_hint)
    base["intents"], base["routed_by"], base["notes"] = (
        [i.value for i in rt.intents],
        rt.routed_by,
        list(rt.notes),
    )
    timings = {"route_ms": int((time.monotonic() - t0) * 1000)}
    plan_log: list[dict[str, Any]] = []
    retrieved: list[Any] = []
    checks: list[Any] = []

    for intent in rt.intents:
        t1 = time.monotonic()
        if intent == Intent.OUT_OF_SCOPE:
            base["sections"].append(
                {
                    "plan": intent.value,
                    "title": "Out of scope",
                    "sentences": [
                        {
                            "id": "O-1",
                            "text": OUT_OF_SCOPE_TEXT,
                            "status": "INFO",
                            "state": "INFO",
                            "kind": "decline",
                            "citations": [],
                        }
                    ],
                    "notes": [],
                    "extras": {},
                }
            )
            base["answer_sentences"] += base["sections"][-1]["sentences"]
            plan_log.append({"plan": intent.value})
            continue
        if intent == Intent.FACTUAL_QA:
            fr = answer_factual(conn, deps, matter, q, as_of)
            sents = [
                {**s, "id": f"Q-{i}", "state": "CURRENT", "kind": "answer", "plan": "FACTUAL_QA"}
                for i, s in enumerate(fr.sentences, 1)
            ]
            base["sections"].append(
                {
                    "plan": "FACTUAL_QA",
                    "title": "Answer",
                    "sentences": sents,
                    "notes": fr.notes,
                    "extras": {"mode": fr.mode},
                }
            )
            base["answer_sentences"] += sents
            base["not_found"] += fr.not_found
            base["superseded_notes"] += fr.superseded_notes
            base["unverified"] += fr.unverified
            base["notes"] += fr.notes
            base["mode"] = fr.mode
            retrieved += [h.to_trace() for h in fr.hits]
            checks += [{"text": u["text"], "ok": False, "reasons": u["reasons"]} for u in fr.unverified] + [
                {"text": s["text"], "ok": True} for s in sents
            ]
            plan_log.append({"plan": "FACTUAL_QA", "mode": fr.mode, "hits": len(fr.hits)})
        else:
            res = run_plan(conn, deps, matter, intent, q, as_of, today)
            sents, rejected = sentences_from_statements(
                conn, res.statements, plan=res.plan, threshold=deps.settings.quote_match_threshold
            )
            if res.plan in ("GIST", "CLAIMS", "DIRECTIONS") and deps.settings.narrative_enabled:
                nar = narrate(deps.llm, res.title, res.statements)
                if nar:
                    sents = [*nar, *sents]
            base["sections"].append(
                {
                    "plan": res.plan,
                    "title": res.title,
                    "sentences": sents,
                    "notes": res.notes,
                    "extras": _json_extras(res.extras),
                }
            )
            base["answer_sentences"] += sents
            base["unverified"] += rejected
            base["notes"] += res.notes
            if res.plan == "GIST":
                base["superseded_notes"] += [
                    {
                        "fact": s["text"],
                        "superseded_by": f"{s.get('superseded_by_doc')}",
                        "replaced_by": s.get("superseded_by"),
                    }
                    for s in res.extras.get("superseded", [])
                ]
            checks += [{"id": r["id"], "ok": False, "reasons": r["reasons"]} for r in rejected] + [
                {"id": s["id"], "ok": True} for s in sents if s["status"] != "INFO"
            ]
            plan_log.append({"plan": res.plan, "statements": len(res.statements)})
        timings[f"{intent.value.lower()}_ms"] = int((time.monotonic() - t1) * 1000)

    base["model_used"] = deps.llm.model_names()
    timings["total_ms"] = int((time.monotonic() - t0) * 1000)
    base["timings_ms"] = timings
    base["trace_id"] = trace_repo.insert_trace(
        conn, matter_id=matter_id, as_of=as_of, question=q, intents=base["intents"], routed_by=base["routed_by"], plans=plan_log, retrieved=retrieved,
        citation_checks=checks, timings=timings, model_versions=base["model_used"],
        answer={"sentences": len(base["answer_sentences"]), "not_found": base["not_found"], "unverified": len(base["unverified"])}, actor=actor,
    )  # fmt: skip
    return base


def _json_extras(extras: dict[str, Any]) -> dict[str, Any]:
    """Plan extras safe for JSON (the what-changed report and gist sections are already plain data)."""
    return {
        k: v
        for k, v in extras.items()
        if k in ("sections", "by_party", "issue_tags", "report", "disputed", "superseded")
    }
