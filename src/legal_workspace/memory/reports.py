"""What-Changed report (blueprint §8.5): read from the ledger, never recomputed by a model."""

from __future__ import annotations

from typing import Any

from legal_workspace.db.pool import Conn

from ..db import documents as doc_repo

_TYPE_ORDER = {
    "SUPERSEDED": 0, "NARROWED": 1, "DISPUTED": 2, "CONTRADICTED_BY_EVIDENCE": 3, "NEW": 4, "COMPLIED": 5, "CORROBORATED": 6,
    "WITHDRAWN": 7,
}  # fmt: skip


def build_changes(conn: Conn, matter_id: str, batch_seq: int) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT l.change_id, l.change_type, l.rule_id, l.reason, l.new_state, l.previous_state, l.assertion_id, l.related_assertion_id, "
        "l.reviewer, a.assertion_text, a.fact_key, a.source_page, a.source_quote, a.evidence_only, a.originating_document_id, "
        "a.originating_document_id AS doc_id, ad.title AS document_title, r.assertion_text AS related_text, r.source_page AS related_page, r.fact_key AS related_key, "
        "r.source_quote AS related_quote, r.originating_document_id AS related_doc_id, "
        "rd.title AS related_title, cd.title AS caused_by_title "
        "FROM fact_change_log l JOIN matter_fact_assertions a ON a.assertion_id = l.assertion_id "
        "JOIN documents ad ON ad.document_id = a.originating_document_id "
        "LEFT JOIN matter_fact_assertions r ON r.assertion_id = l.related_assertion_id "
        "LEFT JOIN documents rd ON rd.document_id = r.originating_document_id "
        "LEFT JOIN documents cd ON cd.document_id = l.caused_by_document_id "
        "WHERE l.matter_id = %s AND l.batch_seq = %s ORDER BY l.change_id",
        (matter_id, batch_seq),
    ).fetchall()
    related_ids = {
        str(r["related_assertion_id"])
        for r in rows
        if r["related_assertion_id"] and r["change_type"] != "NEW"
    }
    changes: list[dict[str, Any]] = []
    for r in rows:
        ct = r["change_type"]
        if ct == "NEW" and str(r["assertion_id"]) in related_ids:
            continue  # grouped with the change it caused
        if ct == "CORROBORATED" and r["related_text"] is None:
            continue
        if ct in ("SUPERSEDED", "NARROWED", "DISPUTED") or (
            ct == "CONTRADICTED_BY_EVIDENCE" and r["related_text"]
        ):
            before, after = r["assertion_text"], r["related_text"]
            title, page = r["related_title"] or r["caused_by_title"], r["related_page"]
            quote, doc_id = r["related_quote"], r["related_doc_id"]
        else:
            before, after = (r["related_text"] if ct == "CORROBORATED" else None), r["assertion_text"]
            title, page = r["document_title"], r["source_page"]
            quote, doc_id = r["source_quote"], r["doc_id"]
        changes.append(
            {
                "change_id": r["change_id"], "change_type": ct, "rule_id": r["rule_id"], "before": before, "after": after,
                "reason": r["reason"], "source_document_title": title, "page": page, "assertion_id": str(r["assertion_id"]),
                "fact_key": r["fact_key"], "evidence_only": bool(r["evidence_only"]) and ct == "NEW", "reviewer": r["reviewer"],
                "quote": quote, "source_document_id": str(doc_id) if doc_id else None,
            }
        )  # fmt: skip
    changes.sort(key=lambda c: (_TYPE_ORDER.get(c["change_type"], 9), c["change_id"]))
    docs = doc_repo.list_documents(conn, matter_id, batch_seq)
    return {
        "batch_seq": batch_seq,
        "documents_processed": sum(1 for d in docs if d["status"] == "PROCESSED"),
        "documents_failed": [
            {"title": d["original_filename"], "error": d["error_message"]}
            for d in docs
            if d["status"] == "FAILED"
        ],
        "duplicates_skipped": [
            d["original_filename"] for d in doc_repo.list_duplicates(conn, matter_id, batch_seq)
        ],
        "changes": changes,
    }


def render_text(report: dict[str, Any]) -> str:
    """Plain-text rendering (blueprint §8.5 example), used by exports and tests."""
    head = (
        f"WHAT CHANGED IN BATCH {report['batch_seq']}   ({report['documents_processed']} documents processed, "
        f"{len(report['documents_failed'])} failed, {len(report['duplicates_skipped'])} duplicates)"
    )
    lines = [head, ""]
    for i, c in enumerate(report["changes"], 1):
        if c["before"] and c["after"]:
            what = f"{c['before']} -> {c['after']}"
        else:
            what = c["after"] or c["before"] or ""
        lines.append(f"{i}. {c['change_type']:<10} {what}   [{c['source_document_title']}, p.{c['page']}]")
    return "\n".join(lines)
