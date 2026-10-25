"""Read side of case memory: current position, as-of views, chronology, directions, claims board (blueprint §8.5, §9.2)."""

from __future__ import annotations

from datetime import date
from typing import Any

from legal_workspace.db.pool import Conn

from ..domain.deadlines import status_of

Row = dict[str, Any]

_FACT_COLS = (
    "a.assertion_id, a.fact_key, a.subject_type, a.slot, a.assertion_category, a.assertion_text, a.value_text, a.value_date, "
    "a.value_amount, a.value_bool, a.value_number, a.originating_document_id, a.source_chunk_id, a.source_page, a.source_quote, "
    "a.assertion_date, a.learned_in_batch_seq, a.ended_in_batch_seq, a.evidence_only, a.derived, a.needs_review, a.review_reason, "
    "a.superseded_by_assertion_id, a.asserting_party_id, a.state AS state_now, a.created_at, "
    "d.title AS document_title, d.document_type, d.document_date, d.authority_class, p.canonical_name AS party_name, p.role AS party_role"
)


def facts_as_of(
    conn: Conn, matter_id: str, as_of: int, *, include_evidence: bool = False, keys_like: str | None = None,
    categories: list[str] | None = None,
) -> list[Row]:  # fmt: skip
    """Facts the system believed after batch `as_of`, each with its state at that time (blueprint query b)."""
    sql = (
        f"SELECT {_FACT_COLS}, s.new_state AS state "  # noqa: S608
        "FROM matter_fact_assertions a JOIN documents d ON d.document_id = a.originating_document_id "
        "LEFT JOIN parties p ON p.party_id = a.asserting_party_id "
        "JOIN LATERAL (SELECT l.new_state FROM fact_change_log l WHERE l.assertion_id = a.assertion_id AND l.batch_seq <= %s "
        "              ORDER BY l.batch_seq DESC, l.change_id DESC LIMIT 1) s ON TRUE "
        "WHERE a.matter_id = %s AND a.learned_in_batch_seq <= %s AND (a.ended_in_batch_seq IS NULL OR a.ended_in_batch_seq > %s)"
    )
    params: list[Any] = [as_of, matter_id, as_of, as_of]
    if not include_evidence:
        sql += " AND a.evidence_only = FALSE"
    if keys_like:
        sql += " AND a.fact_key LIKE %s"
        params.append(keys_like)
    if categories:
        sql += " AND a.assertion_category = ANY(%s)"
        params.append(categories)
    sql += " ORDER BY a.subject_type, a.fact_key, a.created_at"
    return conn.execute(sql, params).fetchall()


def superseded_as_of(conn: Conn, matter_id: str, as_of: int) -> list[Row]:
    """Facts that have been superseded after `as_of` (still shown in change views, struck through)."""
    return conn.execute(
        f"SELECT {_FACT_COLS}, 'SUPERSEDED' AS state, "  # noqa: S608
        "(SELECT d2.title FROM matter_fact_assertions n JOIN documents d2 ON d2.document_id = n.originating_document_id "
        " WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by_title, "
        "(SELECT n.source_page FROM matter_fact_assertions n WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by_page, "
        "(SELECT n.assertion_text FROM matter_fact_assertions n WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by_text "
        "FROM matter_fact_assertions a JOIN documents d ON d.document_id = a.originating_document_id "
        "LEFT JOIN parties p ON p.party_id = a.asserting_party_id "
        "WHERE a.matter_id = %s AND a.ended_in_batch_seq IS NOT NULL AND a.ended_in_batch_seq <= %s AND a.state = 'SUPERSEDED' "
        "ORDER BY a.ended_in_batch_seq DESC, a.created_at",
        (matter_id, as_of),
    ).fetchall()


def chronology(conn: Conn, matter_id: str, as_of: int) -> list[Row]:
    """Events known after batch `as_of`, sorted by real-world date, with the state of the fact behind each."""
    rows = conn.execute(
        "SELECT e.event_id, e.event_date, e.event_type, e.description, e.source_page, e.learned_in_batch_seq, e.assertion_id, "
        "d.title AS document_title, d.document_id, p.canonical_name AS party_name, a.fact_key, a.evidence_only, a.state AS fact_state_now, "
        "a.ended_in_batch_seq, a.superseded_by_assertion_id, a.source_quote, a.source_chunk_id, a.source_page AS fact_page, a.assertion_text AS fact_text, "
        "(SELECT l.new_state FROM fact_change_log l WHERE l.assertion_id = a.assertion_id AND l.batch_seq <= %s "
        "  ORDER BY l.batch_seq DESC, l.change_id DESC LIMIT 1) AS state_as_of, "
        "(SELECT d2.title || ', p.' || n.source_page FROM matter_fact_assertions n JOIN documents d2 ON d2.document_id = n.originating_document_id "
        "  WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by "
        "FROM matter_events e JOIN documents d ON d.document_id = e.source_document_id "
        "LEFT JOIN parties p ON p.party_id = e.party_id LEFT JOIN matter_fact_assertions a ON a.assertion_id = e.assertion_id "
        "WHERE e.matter_id = %s AND e.learned_in_batch_seq <= %s ORDER BY e.event_date, e.created_at",
        (as_of, matter_id, as_of),
    ).fetchall()
    for r in rows:
        ended = r["ended_in_batch_seq"]
        if r["assertion_id"] is None or r["state_as_of"] is None:
            r["state"] = "ACTIVE"
        elif ended is not None and ended <= as_of:
            r["state"] = "SUPERSEDED"
        else:
            r["state"] = r["state_as_of"]
    return rows


def directions(conn: Conn, matter_id: str, as_of: int, today: date) -> list[Row]:
    rows = conn.execute(
        "SELECT cd.*, a.assertion_text, a.state AS fact_state, a.ended_in_batch_seq, a.evidence_only, a.fact_key, a.source_quote, "
        "d.title AS order_title, pr.canonical_name AS responsible_party, cb.title AS complied_by_title, "
        "(SELECT d2.title || ', p.' || n.source_page FROM matter_fact_assertions n JOIN documents d2 ON d2.document_id = n.originating_document_id "
        "  WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by "
        "FROM court_directions cd JOIN matter_fact_assertions a ON a.assertion_id = cd.assertion_id "
        "JOIN documents d ON d.document_id = cd.order_document_id LEFT JOIN parties pr ON pr.party_id = cd.responsible_party_id "
        "LEFT JOIN documents cb ON cb.document_id = cd.complied_by_document_id "
        "WHERE cd.matter_id = %s AND a.learned_in_batch_seq <= %s AND NOT a.evidence_only ORDER BY cd.due_date NULLS LAST, cd.order_date",
        (matter_id, as_of),
    ).fetchall()
    out = []
    for r in rows:
        superseded = r["ended_in_batch_seq"] is not None and r["ended_in_batch_seq"] <= as_of
        r["superseded"] = superseded
        r["status"] = (
            "SUPERSEDED" if superseded else status_of(r["due_date"], r["compliance_status"], today).value
        )
        out.append(r)
    return out


def links_for(conn: Conn, matter_id: str, assertion_ids: list[str]) -> dict[str, list[Row]]:
    """Evidence links per claim: SUPPORTS / CONTRADICTS targets with their source."""
    if not assertion_ids:
        return {}
    rows = conn.execute(
        "SELECT l.assertion_id, l.link_type, l.rule_id, l.batch_seq, t.assertion_id AS target_id, t.assertion_text AS target_text, "
        "t.source_page AS target_page, t.source_quote AS target_quote, td.title AS target_document, td.document_id AS target_document_id "
        "FROM fact_links l JOIN matter_fact_assertions t ON t.assertion_id = l.target_assertion_id "
        "JOIN documents td ON td.document_id = t.originating_document_id "
        "WHERE l.matter_id = %s AND l.assertion_id = ANY(%s::uuid[]) AND l.link_type IN ('SUPPORTS','CONTRADICTS') "
        "ORDER BY l.created_at",
        (matter_id, assertion_ids),
    ).fetchall()
    out: dict[str, list[Row]] = {}
    for r in rows:
        out.setdefault(str(r["assertion_id"]), []).append(r)
    # also the reverse direction of CONTRADICTS (pleading -> record) so both sides see the conflict
    rev = conn.execute(
        "SELECT l.target_assertion_id AS assertion_id, 'CONTRADICTS' AS link_type, l.rule_id, l.batch_seq, s.assertion_id AS target_id, "
        "s.assertion_text AS target_text, s.source_page AS target_page, s.source_quote AS target_quote, sd.title AS target_document, "
        "sd.document_id AS target_document_id FROM fact_links l JOIN matter_fact_assertions s ON s.assertion_id = l.assertion_id "
        "JOIN documents sd ON sd.document_id = s.originating_document_id "
        "WHERE l.matter_id = %s AND l.target_assertion_id = ANY(%s::uuid[]) AND l.link_type = 'CONTRADICTS'",
        (matter_id, assertion_ids),
    ).fetchall()
    for r in rev:
        out.setdefault(str(r["assertion_id"]), []).append(r)
    return out


def party_summary(conn: Conn, matter_id: str) -> list[Row]:
    return conn.execute(
        "SELECT party_id, canonical_name, role FROM parties WHERE matter_id = %s ORDER BY role, canonical_name",
        (matter_id,),
    ).fetchall()
