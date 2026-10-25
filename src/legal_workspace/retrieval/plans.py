"""The retrieval plans (blueprint §9.2). Plans 1-6 read the case memory directly: every statement they return is built by
code from a stored fact, so it already carries a verifiable citation. Plan 7 searches the legal corpus; plan 8 (factual
Q&A) lives in `grounding.answer` because it involves the language model."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from legal_workspace.db.pool import Conn

from ..adapters.embed import Embedder
from ..adapters.rerank import Reranker
from ..domain.normalise import fmt_date
from ..memory import queries
from ..memory.reports import build_changes
from .hybrid import keywords, search_chunks
from .types import Citation, PlanResult, Statement

SECTION_ORDER = [
    "CONTRACT",
    "MILESTONE",
    "INVOICE",
    "PAYMENT",
    "NOTICE",
    "CLAIM",
    "RELIEF",
    "ALLEGATION",
    "DIRECTION",
    "HEARING",
]
SECTION_LABEL = {
    "CONTRACT": "Contract terms", "MILESTONE": "Milestones", "INVOICE": "Invoices and amounts", "PAYMENT": "Payments", "NOTICE": "Notices",
    "CLAIM": "Claims", "RELIEF": "Relief sought", "ALLEGATION": "Allegations, admissions and denials", "DIRECTION": "Court directions",
    "HEARING": "Hearings",
}  # fmt: skip
CLAIM_CATEGORIES = ["CLAIM", "COUNTERCLAIM", "DEFENCE", "DENIAL", "ADMISSION", "RELIEF_SOUGHT"]


def fact_citation(row: dict[str, Any]) -> Citation:
    return Citation(
        document_id=str(row["originating_document_id"]), document_title=row["document_title"], page=row["source_page"],
        quote=row["source_quote"], chunk_id=str(row["source_chunk_id"]) if row.get("source_chunk_id") else None,
    )  # fmt: skip


def _state(row: dict[str, Any]) -> str:
    s = row.get("state") or row.get("state_now") or "ACTIVE"
    return {"ACTIVE": "CURRENT", "DISPUTED": "DISPUTED", "SUPERSEDED": "SUPERSEDED"}.get(s, s)


def fact_statement(row: dict[str, Any], **meta: Any) -> Statement:
    return Statement(
        id=f"F-{str(row['assertion_id'])[:8]}", text=row["assertion_text"], citations=[fact_citation(row)], state=_state(row),
        kind="fact", fact_id=str(row["assertion_id"]),
        meta={"fact_key": row["fact_key"], "subject_type": row["subject_type"], "party": row.get("party_name"), "needs_review": row.get("needs_review"),
              "derived": row.get("derived"), "evidence_only": row.get("evidence_only"), **meta},
    )  # fmt: skip


# ------------------------------------------------------------------------------------------- 1. gist
def plan_gist(conn: Conn, matter: dict[str, Any], as_of: int) -> PlanResult:
    mid = str(matter["matter_id"])
    parties = queries.party_summary(conn, mid)
    res = PlanResult("GIST", "Current position")
    res.statements.append(
        Statement(
            "M-0",
            f"{matter['title']} ({matter['matter_number']}), {matter['current_forum'] or 'forum not stated'}. Parties: "
            + "; ".join(f"{p['canonical_name']} ({p['role'].title()})" for p in parties)
            + f". Position as of batch {as_of}.",
            state="INFO",
            kind="meta",
        )  # fmt: skip
    )
    facts = queries.facts_as_of(conn, mid, as_of)
    sections: dict[str, list[str]] = {}
    for st in SECTION_ORDER:
        for row in (f for f in facts if f["subject_type"] == st):
            stmt = fact_statement(row, section=SECTION_LABEL[st])
            res.statements.append(stmt)
            sections.setdefault(SECTION_LABEL[st], []).append(stmt.id)
    res.extras["sections"] = sections
    res.extras["superseded"] = [
        {**fact_statement(r).to_dict(), "superseded_by": r.get("superseded_by_text"), "superseded_by_doc": f"{r.get('superseded_by_title')}, p.{r.get('superseded_by_page')}"}
        for r in queries.superseded_as_of(conn, mid, as_of)
    ]  # fmt: skip
    res.extras["disputed"] = [s.id for s in res.statements if s.state == "DISPUTED"]
    if len(res.statements) == 1:
        res.notes.append("No facts have been extracted yet for this matter.")
    return res


# ------------------------------------------------------------------------------------ 2. chronology
def plan_chronology(conn: Conn, matter: dict[str, Any], as_of: int) -> PlanResult:
    mid = str(matter["matter_id"])
    res = PlanResult("CHRONOLOGY", "Chronology")
    for e in queries.chronology(conn, mid, as_of):
        state = (
            "EVIDENCE"
            if e["evidence_only"] and e["state"] != "SUPERSEDED"
            else {"ACTIVE": "CURRENT"}.get(e["state"], e["state"])
        )
        cite = Citation(
            str(e["document_id"]),
            e["document_title"],
            e["source_page"],
            e.get("source_quote"),
            chunk_id=str(e["source_chunk_id"]) if e.get("source_chunk_id") else None,
        )
        res.statements.append(
            Statement(
                id=f"E-{str(e['event_id'])[:8]}",
                text=f"{fmt_date(e['event_date'])}: {e['description']}",
                citations=[cite],
                state=state or "CURRENT",
                kind="event",
                fact_id=str(e["assertion_id"]) if e["assertion_id"] else None,
                superseded_by=e.get("superseded_by"),
                meta={
                    "date": e["event_date"].isoformat(),
                    "event_type": e["event_type"],
                    "party": e["party_name"],
                    "learned_in_batch": e["learned_in_batch_seq"],
                },
            )  # fmt: skip
        )
    if not res.statements:
        res.notes.append("No dated events are known yet.")
    return res


# ----------------------------------------------------------------------------------------- 3. claims
def plan_claims(conn: Conn, matter: dict[str, Any], as_of: int, party: str | None = None) -> PlanResult:
    mid = str(matter["matter_id"])
    rows = queries.facts_as_of(conn, mid, as_of, categories=CLAIM_CATEGORIES)
    if party:
        p = party.lower()
        rows = [
            r
            for r in rows
            if r.get("party_name")
            and (p in r["party_name"].lower() or r["party_name"].lower().split()[0] in p)
        ] or rows
    links = queries.links_for(conn, mid, [str(r["assertion_id"]) for r in rows])
    res = PlanResult("CLAIMS", "Claims, defences and relief by party")
    by_party: dict[str, list[str]] = {}
    for r in rows:
        ev = links.get(str(r["assertion_id"]), [])
        stmt = fact_statement(r, category=r["assertion_category"])
        stmt.meta["evidence"] = {
            "for": [_ev(x) for x in ev if x["link_type"] == "SUPPORTS"],
            "against": [_ev(x) for x in ev if x["link_type"] == "CONTRADICTS"],
        }
        res.statements.append(stmt)
        by_party.setdefault(r.get("party_name") or "Unattributed", []).append(stmt.id)
    res.extras["by_party"] = by_party
    if not rows:
        res.notes.append("No claims, defences or reliefs have been extracted yet.")
    return res


def _ev(link: dict[str, Any]) -> dict[str, Any]:
    return {"fact_id": str(link["target_id"]), "text": link["target_text"], "document": link["target_document"], "document_id": str(link["target_document_id"]),
            "page": link["target_page"], "quote": link["target_quote"], "rule": link["rule_id"]}  # fmt: skip


# --------------------------------------------------------------------------------------- 4. evidence
def plan_evidence(
    conn: Conn, embedder: Embedder, reranker: Reranker, matter: dict[str, Any], as_of: int, question: str = "",
    *, candidates_per_claim: int = 3, max_targets: int = 5,
) -> PlanResult:  # fmt: skip
    mid = str(matter["matter_id"])
    rows = queries.facts_as_of(
        conn, mid, as_of, categories=CLAIM_CATEGORIES + ["EVENT_FACT", "TERM", "PAYMENT"]
    )
    kws = set(keywords(question))
    scored = []
    for r in rows:
        overlap = len(
            kws
            & set(
                keywords(
                    r["assertion_text"]
                    + " "
                    + r["fact_key"].replace("/", " ").replace("-", " ").replace("_", " ")
                )
            )
        )
        priority = (overlap, r["state"] == "DISPUTED", r["assertion_category"] in CLAIM_CATEGORIES)
        scored.append((priority, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    targets = [r for p, r in scored if p[0] > 0][:max_targets] or [r for p, r in scored if p[1] or p[2]][
        :max_targets
    ]
    links = queries.links_for(conn, mid, [str(r["assertion_id"]) for r in targets])
    res = PlanResult("EVIDENCE", "Evidence for and against")
    for r in targets:
        tgt = fact_statement(r, role="assertion")
        res.statements.append(tgt)
        ev = links.get(str(r["assertion_id"]), [])
        seen_chunks: set[str] = set()
        for kind, label in (("SUPPORTS", "evidence_for"), ("CONTRADICTS", "evidence_against")):
            for x in (e for e in ev if e["link_type"] == kind):
                res.statements.append(
                    Statement(
                        id=f"V-{str(x['target_id'])[:8]}-{label[-3:]}",
                        text=x["target_text"],
                        state="EVIDENCE",
                        kind=label,
                        fact_id=str(x["target_id"]),
                        citations=[
                            Citation(
                                str(x["target_document_id"]),
                                x["target_document"],
                                x["target_page"],
                                x["target_quote"],
                            )
                        ],
                        meta={"target_id": tgt.id, "rule": x["rule_id"]},
                    )  # fmt: skip
                )
        for h in search_chunks(
            conn,
            embedder,
            reranker,
            matter_id=mid,
            query=r["assertion_text"],
            as_of=as_of,
            final=candidates_per_claim + 2,
        ):
            if h.chunk_id in seen_chunks or (
                str(h.document_id) == str(r["originating_document_id"]) and h.page_start == r["source_page"]
            ):
                continue
            seen_chunks.add(h.chunk_id)
            if len(seen_chunks) > candidates_per_claim:
                break
            res.statements.append(
                Statement(
                    id=f"P-{h.chunk_id[:8]}-{str(r['assertion_id'])[:4]}",
                    text=" ".join(h.text.split())[:300],
                    state="EVIDENCE",
                    kind="possible_evidence",
                    citations=[
                        Citation(
                            h.document_id,
                            h.document_title,
                            h.page_start,
                            " ".join(h.text.split())[:300],
                            h.structural_ref,
                            h.chunk_id,
                        )
                    ],
                    meta={"target_id": tgt.id, "note": "possible evidence, not yet linked"},
                )  # fmt: skip
            )
    if not targets:
        res.notes.append("No assertions matched the question.")
    return res


# ------------------------------------------------------------------------------------- 5. directions
def plan_directions(
    conn: Conn, matter: dict[str, Any], as_of: int, today: date, status: str | None = None
) -> PlanResult:
    mid = str(matter["matter_id"])
    res = PlanResult("DIRECTIONS", "Court directions, deadlines and undertakings")
    for r in queries.directions(conn, mid, as_of, today):
        if status and r["status"] != status.upper():
            continue
        bits = []
        if r["responsible_party"]:
            bits.append(f"responsible: {r['responsible_party']}")
        bits.append(f"status: {r['status']}")
        if r["compliance_status"] == "COMPLIED":
            bits.append(f"complied by {r['complied_by_title']}" + (" (late)" if r["complied_late"] else ""))
        if r["weekend_flag"]:
            bits.append("falls on a weekend; General Clauses Act s.10 may allow the next working day")
        stmt = Statement(
            id=f"D-{str(r['direction_id'])[:8]}", text=f"{r['assertion_text']} ({'; '.join(bits)})",
            citations=[Citation(str(r["order_document_id"]), r["order_title"], r["source_page"], r["direction_text"])],
            state="SUPERSEDED" if r["superseded"] else "CURRENT", kind="direction", fact_id=str(r["assertion_id"]), superseded_by=r.get("superseded_by"),
            meta={"step": r["procedural_step"], "kind": r["kind"], "due_date": r["due_date"].isoformat() if r["due_date"] else None,
                  "status": r["status"], "order_date": r["order_date"].isoformat(), "responsible": r["responsible_party"],
                  "evidence_only": r["evidence_only"]},
        )  # fmt: skip
        res.statements.append(stmt)
    if not res.statements:
        res.notes.append("The court has not given any directions in the documents received so far.")
    return res


# ------------------------------------------------------------------------------------ 6. what changed
def plan_what_changed(conn: Conn, matter: dict[str, Any], batch_seq: int) -> PlanResult:
    mid = str(matter["matter_id"])
    report = build_changes(conn, mid, batch_seq)
    res = PlanResult("WHAT_CHANGED", f"What changed in batch {batch_seq}", extras={"report": report})
    for c in report["changes"]:
        if c["before"] and c["after"]:
            text = f"{c['change_type'].replace('_', ' ')}: {c['before']} → {c['after']}"
        else:
            text = f"{c['change_type'].replace('_', ' ')}: {c['after'] or c['before']}"
        res.statements.append(
            Statement(
                id=f"C-{c['change_id']}",
                text=text,
                citations=[
                    Citation(c["source_document_id"], c["source_document_title"], c["page"], c["quote"])
                ]
                if c["source_document_id"]
                else [],
                state="EVIDENCE" if c["evidence_only"] else "CURRENT",
                kind="change",
                fact_id=c["assertion_id"],
                meta={
                    "change_type": c["change_type"],
                    "rule": c["rule_id"],
                    "reason": c["reason"],
                    "fact_key": c["fact_key"],
                },
            )  # fmt: skip
        )
    for f in report["documents_failed"]:
        res.statements.append(
            Statement(
                f"X-{len(res.statements)}",
                f"Could not be read: {f['title']} ({f['error']})",
                state="INFO",
                kind="info",
            )
        )
    for d in report["duplicates_skipped"]:
        res.statements.append(
            Statement(f"X-{len(res.statements)}", f"Duplicate skipped: {d}", state="INFO", kind="info")
        )
    if not report["changes"]:
        res.notes.append("This batch did not change the understanding of the matter.")
    return res


# ----------------------------------------------------------------------------------- 7. legal research
SLOT_TAGS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"^notice/[^/]+/(received|received_date|mode_of_service)$"), ["service_of_notice"]),
    (re.compile(r"^contract/[^/]+/(delivery_date|effective_date)$"), ["time_essence", "delay"]),
    (re.compile(r"^contract/[^/]+/(ld_rate|ld_cap)$"), ["liquidated_damages", "penalty"]),
    (
        re.compile(r"^invoice/[^/]+/(amount_outstanding|deduction|invoice_amount)$"),
        ["recovery_of_price", "part_payment"],
    ),
    (re.compile(r"^payment/"), ["part_payment"]),
    (re.compile(r"^claim/interest/"), ["interest"]),
    (
        re.compile(
            r"^contract/[^/]+/(termination_notice_days|cure_period_days|termination_for_convenience)$"
        ),
        ["termination", "cure_period"],
    ),
    (re.compile(r"^contract/[^/]+/arbitration_clause$"), ["arbitration_clause", "interim_measures"]),
    (re.compile(r"^allegation/delay/"), ["delay", "time_essence"]),
    (re.compile(r"^allegation/wrongful[-_]termination/"), ["termination"]),
    (re.compile(r"^relief/injunction/"), ["interim_injunction"]),
    (re.compile(r"^relief/specific[-_]performance/"), ["specific_performance"]),
    (re.compile(r"^direction/(interim_relief|written[-_]statement)/"), ["amendment_of_pleadings"]),
]
MATTER_TYPE_TAGS = {
    "BREACH": ["delay", "liquidated_damages", "time_essence"],
    "PAYMENT_RECOVERY": ["recovery_of_price", "interest", "pre_institution_mediation", "summary_suit"],
    "TERMINATION_INJUNCTION": ["termination", "interim_injunction", "arbitration_clause"],
}


def issue_tags(conn: Conn, matter: dict[str, Any], as_of: int) -> list[str]:
    """Issue tags for the matter's disputed and claimed slots (code maps slots to tags, blueprint §11)."""
    tags: list[str] = []
    for r in queries.facts_as_of(conn, str(matter["matter_id"]), as_of, include_evidence=True):
        for pat, ts in SLOT_TAGS:
            if pat.search(r["fact_key"]) and (
                r["state"] == "DISPUTED"
                or r["assertion_category"] in (*CLAIM_CATEGORIES, "TERM", "PAYMENT", "EVENT_FACT")
            ):
                tags += [t for t in ts if t not in tags]
    return tags + [t for t in MATTER_TYPE_TAGS.get(matter["matter_type"], []) if t not in tags]


def plan_legal(
    conn: Conn,
    embedder: Embedder,
    matter: dict[str, Any],
    as_of: int,
    question: str = "",
    k: int = 6,
) -> PlanResult:
    from ..corpus.search import search_corpus

    tags = issue_tags(conn, matter, as_of)
    res = PlanResult("LEGAL_RESEARCH", "Relevant authorities", extras={"issue_tags": tags})
    for p in search_corpus(conn, embedder, question, tags=tags, k=k):
        label = (
            p["title"]
            + (f", {p['section_ref']}" if p["section_ref"] else "")
            + (f" para {p['paragraph_number']}" if p["paragraph_number"] else "")
        )
        excerpt = " ".join(p["content"].split())
        res.statements.append(
            Statement(
                id=f"L-{str(p['passage_id'])[:8]}",
                text=f"{label}: {excerpt[:420]}{'...' if len(excerpt) > 420 else ''}",
                citations=[
                    Citation(
                        None, label, None, excerpt[:300], source_kind="law", source_id=str(p["passage_id"])
                    )
                ],
                state="CURRENT",
                kind="authority",
                meta={
                    "source_url": p["source_url"],
                    "citation": p["citation"],
                    "treatment_note": p["treatment_note"],
                    "tags": p["issue_tags"],
                    "verification_status": p["verification_status"],
                    "source_key": p["source_key"],
                    "score": p.get("score"),
                },
            )  # fmt: skip
        )
    if not res.statements:
        res.notes.append(
            "No relevant authority was found in the loaded legal corpus. Load more with `make corpus`."
        )
    return res
