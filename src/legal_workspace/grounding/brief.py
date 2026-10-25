"""Hearing brief (blueprint §9.4): a fixed template, every line cited, built from the retrieval plans."""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

from legal_workspace.db.pool import Conn

from ..db import matters as matter_repo
from ..db import traces as trace_repo
from ..deps import Deps
from ..domain.normalise import fmt_date
from ..errors import ValidationFailed
from ..memory import queries, review
from ..retrieval import plans
from ..retrieval.types import Citation, Statement
from .answer import sentences_from_statements
from .narrative import narrate

SECTIONS = [
    (1, "Matter snapshot"), (2, "Current position"), (3, "Issues in dispute"), (4, "Evidence for and against"),
    (5, "Directions and compliance"), (6, "Changes since the last hearing"), (7, "Authorities"), (8, "Open risks and to-do"),
]  # fmt: skip


def _last_order_batch(conn: Conn, matter_id: str, as_of: int) -> int:
    row = conn.execute(
        "SELECT batch_seq FROM documents WHERE matter_id = %s AND document_type = 'ORDER' AND batch_seq <= %s AND status = 'PROCESSED' "
        "ORDER BY document_date DESC NULLS LAST, batch_seq DESC LIMIT 1",
        (matter_id, as_of),
    ).fetchone()
    return int(row["batch_seq"]) if row else 1


def _snapshot(conn: Conn, matter: dict[str, Any], as_of: int, directions: list[Statement]) -> list[Statement]:
    mid = str(matter["matter_id"])
    parties = queries.party_summary(conn, mid)
    out = [Statement("S-1", f"{matter['title']} ({matter['matter_number']}), {matter['current_forum'] or 'forum not stated'}. "
                     + "; ".join(f"{p['canonical_name']} ({p['role'].title()})" for p in parties), state="INFO", kind="meta")]  # fmt: skip
    filed = conn.execute(
        "SELECT title, document_type, document_date, document_id FROM documents WHERE matter_id = %s AND status = 'PROCESSED' AND batch_seq <= %s "
        "AND document_type IN ('PLAINT','WRITTEN_STATEMENT','REPLICATION','REJOINDER','COUNTERCLAIM','AMENDED_PLEADING','AFFIDAVIT','APPLICATION','ORDER') "
        "ORDER BY document_date NULLS LAST",
        (mid, as_of),
    ).fetchall()
    for d in filed:
        if d["document_date"]:
            out.append(
                Statement(
                    f"S-{len(out) + 1}",
                    f"{fmt_date(d['document_date'])}: {d['title']}",
                    [Citation(str(d["document_id"]), d["title"], 1, None)],
                    kind="stage",
                )
            )
    nxt = [s for s in directions if s.meta.get("kind") == "NEXT_HEARING" and s.state != "SUPERSEDED"]
    if nxt:
        latest = max(nxt, key=lambda s: s.meta.get("order_date") or "")
        out.append(
            Statement(
                "S-NH",
                f"Next hearing: {latest.text.replace('Next hearing listed on ', '')}",
                latest.citations,
                kind="next_hearing",
                meta=latest.meta,
            )
        )
    return out


def _risks(
    conn: Conn,
    matter: dict[str, Any],
    as_of: int,
    today: date,
    directions: list[Statement],
    claims: Any,
) -> list[Statement]:
    mid = str(matter["matter_id"])
    out: list[Statement] = []
    for s in directions:
        if s.state == "SUPERSEDED" or s.meta.get("kind") == "NEXT_HEARING":
            continue
        st = s.meta.get("status")
        due = s.meta.get("due_date")
        if st == "OVERDUE":
            out.append(
                Statement(
                    f"R-{len(out) + 1}",
                    f"OVERDUE: {s.text}",
                    s.citations,
                    kind="risk",
                    fact_id=s.fact_id,
                    meta={"risk": "overdue"},
                )
            )
        elif st == "PENDING" and due and date.fromisoformat(due) <= today + timedelta(days=14):
            out.append(
                Statement(
                    f"R-{len(out) + 1}",
                    f"Due within 14 days: {s.text}",
                    s.citations,
                    kind="risk",
                    fact_id=s.fact_id,
                    meta={"risk": "due_soon"},
                )
            )
        elif st == "NO_DATE":
            out.append(
                Statement(
                    f"R-{len(out) + 1}",
                    f"Due date not known: {s.text}",
                    s.citations,
                    kind="risk",
                    fact_id=s.fact_id,
                    meta={"risk": "no_date"},
                )
            )
    for st in claims.statements:
        if (
            st.state == "DISPUTED"
            and not st.meta.get("evidence", {}).get("for")
            and not st.meta.get("evidence", {}).get("against")
        ):
            out.append(
                Statement(
                    f"R-{len(out) + 1}",
                    f"No evidence is linked to this disputed point yet: {st.text}",
                    st.citations,
                    kind="risk",
                    fact_id=st.fact_id,
                    meta={"risk": "no_evidence"},
                )
            )
    items = review.list_items(conn, mid)
    if items:
        out.append(
            Statement(
                f"R-{len(out) + 1}",
                f"{len(items)} item(s) are waiting in the review queue ({', '.join(sorted({i['kind'] for i in items}))}).",
                state="INFO",
                kind="risk",
                meta={"risk": "review"},
            )
        )
    return out


def generate_brief(
    conn: Conn,
    deps: Deps,
    matter_id: str,
    *,
    as_of: int | None = None,
    today: date | None = None,
    actor: str | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    matter = matter_repo.get_matter(conn, matter_id)
    latest = matter_repo.latest_committed_seq(conn, matter_id)
    if latest == 0:
        raise ValidationFailed(
            "no committed batch yet: upload documents and commit a batch before preparing a brief"
        )
    if as_of is not None and not 1 <= as_of <= latest:
        raise ValidationFailed(f"as_of_batch_seq must be between 1 and {latest}")
    as_of = as_of or latest
    today = today or deps.settings.today()
    s = deps.settings

    directions = plans.plan_directions(conn, matter, as_of, today)
    claims = plans.plan_claims(conn, matter, as_of)
    gist = plans.plan_gist(conn, matter, as_of)
    legal = plans.plan_legal(conn, deps.embedder, matter, as_of, "")
    first_batch = _last_order_batch(conn, matter_id, as_of)
    changes: list[Statement] = []
    for b in range(first_batch, as_of + 1):
        for st in plans.plan_what_changed(conn, matter, b).statements:
            st.meta["batch_seq"] = b
            if st.kind == "change" and st.meta.get("change_type") != "CORROBORATED":
                changes.append(st)

    disputed = [st for st in gist.statements if st.state == "DISPUTED"]
    evidence = [
        st
        for st in claims.statements
        if st.meta.get("evidence", {}).get("for") or st.meta.get("evidence", {}).get("against")
    ]
    ev_statements: list[Statement] = []
    for st in evidence:
        ev_statements.append(st)
        for kind, label in (("for", "evidence_for"), ("against", "evidence_against")):
            for e in st.meta["evidence"][kind]:
                ev_statements.append(
                    Statement(
                        f"V-{e['fact_id'][:8]}-{kind}",
                        f"{'Supports' if kind == 'for' else 'Contradicts'}: {e['text']}",
                        [Citation(e["document_id"], e["document"], e["page"], e["quote"])],
                        state="EVIDENCE",
                        kind=label,
                        meta={"target_id": st.id},
                    )
                )
    by_section: dict[int, list[Statement]] = {
        1: _snapshot(conn, matter, as_of, directions.statements),
        2: claims.statements,
        3: disputed,
        4: ev_statements,
        5: [x for x in directions.statements if x.state != "SUPERSEDED"],
        6: changes,
        7: legal.statements,
        8: _risks(conn, matter, as_of, today, directions.statements, claims),
    }
    out_sections: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    for n, title in SECTIONS:
        sents, rejected = sentences_from_statements(
            conn, by_section[n], plan=("CHRONOLOGY" if n == 6 else "BRIEF"), threshold=s.quote_match_threshold
        )
        unverified += rejected
        narrative = narrate(deps.llm, title, by_section[n]) if s.narrative_enabled and n in (2, 3, 8) else []
        note = {1: gist.notes, 5: directions.notes, 7: legal.notes}.get(n, [])
        if not sents and not note:
            note = ["Nothing to report."]
        out_sections.append(
            {"n": n, "title": title, "sentences": sents, "narrative": narrative, "notes": note}
        )
    result = {
        "matter": {"id": matter_id, "title": matter["title"], "number": matter["matter_number"], "forum": matter["current_forum"]},
        "as_of_batch_seq": as_of, "generated_on": today.isoformat(), "changes_from_batch": first_batch, "sections": out_sections,
        "unverified": unverified, "issue_tags": legal.extras.get("issue_tags", []),
    }  # fmt: skip
    result["markdown"] = to_markdown(result)
    timings = {"total_ms": int((time.monotonic() - t0) * 1000)}
    result["timings_ms"] = timings
    result["trace_id"] = trace_repo.insert_trace(
        conn, matter_id=matter_id, as_of=as_of, question="[hearing brief]", intents=["HEARING_BRIEF"], routed_by="HINT",
        plans=[{"plan": "BRIEF", "sections": len(SECTIONS)}], retrieved=[], citation_checks=[{"id": u["id"], "ok": False, "reasons": u["reasons"]} for u in unverified],
        timings=timings, model_versions=deps.llm.model_names(), answer={"sections": len(out_sections)}, actor=actor,
    )  # fmt: skip
    return result


def _cite(c: dict[str, Any]) -> str:
    if c.get("source_kind") == "law":
        return f"[{c['document_title']}]"
    return f"[{c['document_title']}, p.{c['page']}]" if c.get("page") else f"[{c['document_title']}]"


def to_markdown(brief: dict[str, Any]) -> str:
    m = brief["matter"]
    lines = [
        f"# Hearing brief: {m['title']}",
        f"{m['number']} · {m['forum'] or ''} · position as of batch {brief['as_of_batch_seq']} · prepared {brief['generated_on']}",
        "",
    ]
    for sec in brief["sections"]:
        lines.append(f"## {sec['n']}. {sec['title']}")
        for n in sec["narrative"]:
            lines.append(f"> {n['text']}")
        for s in sec["sentences"]:
            tag = {"DISPUTED": " **(disputed)**", "SUPERSEDED": " ~~(superseded)~~", "EVIDENCE": ""}.get(
                s.get("state", ""), ""
            )
            if s.get("kind") == "evidence_for" or s.get("kind") == "evidence_against":
                prefix = "  - "
            else:
                prefix = "- "
            cites = " ".join(_cite(c) for c in s.get("citations", [])[:2])
            lines.append(f"{prefix}{s['text']}{tag} {cites}".rstrip())
        for note in sec["notes"]:
            lines.append(f"_{note}_")
        lines.append("")
    if brief["unverified"]:
        lines.append(
            f"_{len(brief['unverified'])} statement(s) were left out because their citations could not be verified._"
        )
    return "\n".join(lines)
