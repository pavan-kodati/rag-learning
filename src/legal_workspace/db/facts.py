"""Fact persistence: assertions, links, ledger (knowledge + time layers). Callers own the transaction."""

from __future__ import annotations

from typing import Any

import psycopg

from legal_workspace.db.pool import Conn

from ..domain.types import Authority, CurrentFact, DocType, FactState, FactValue, PartyRole

Row = dict[str, Any]


def _value_of(r: Row) -> FactValue:
    return FactValue(
        text=r["value_text"] or "",
        date=r["value_date"],
        amount=r["value_amount"],
        boolean=r["value_bool"],
        number=r["value_number"],
    )


def current_facts(conn: Conn, matter_id: str, fact_key: str) -> list[CurrentFact]:
    """Facts with this key that have not ended (ended_in_batch_seq IS NULL)."""
    rows = conn.execute(
        "SELECT a.*, d.authority_class, d.document_type, d.document_date, p.role AS party_role "
        "FROM matter_fact_assertions a JOIN documents d ON d.document_id = a.originating_document_id "
        "LEFT JOIN parties p ON p.party_id = a.asserting_party_id "
        "WHERE a.matter_id = %s AND a.fact_key = %s AND a.ended_in_batch_seq IS NULL ORDER BY a.created_at",
        (matter_id, fact_key),
    ).fetchall()
    return [
        CurrentFact(
            assertion_id=str(r["assertion_id"]),
            fact_key=r["fact_key"],
            slot=r["slot"],
            value=_value_of(r),
            party_id=str(r["asserting_party_id"]) if r["asserting_party_id"] else None,
            party_role=PartyRole(r["party_role"]) if r["party_role"] else None,
            authority=Authority(r["authority_class"]),
            doc_type=DocType(r["document_type"]),
            doc_date=r["document_date"],
            state=FactState(r["state"]),
            evidence_only=r["evidence_only"],
            subject_type=r["subject_type"],
        )  # fmt: skip
        for r in rows
    ]


def insert_fact(conn: Conn, **c: Any) -> str:
    cols = (
        "matter_id", "fact_key", "subject_type", "slot", "assertion_category", "asserting_party_id", "assertion_text",
        "value_text", "value_date", "value_amount", "value_bool", "value_number", "originating_document_id",
        "source_chunk_id", "source_page", "source_quote", "assertion_date", "effective_from", "learned_in_batch_seq",
        "ended_in_batch_seq", "state", "evidence_only", "derived", "superseded_by_assertion_id", "needs_review", "review_reason",
    )  # fmt: skip
    row = conn.execute(
        f"INSERT INTO matter_fact_assertions ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING assertion_id",  # noqa: S608
        [c.get(k) for k in cols],
    ).fetchone()
    assert row is not None
    return str(row["assertion_id"])


def end_fact(conn: Conn, assertion_id: str, batch_seq: int, superseded_by: str | None) -> None:
    conn.execute(
        "UPDATE matter_fact_assertions SET state = 'SUPERSEDED', ended_in_batch_seq = %s, superseded_by_assertion_id = %s "
        "WHERE assertion_id = %s",
        (batch_seq, superseded_by, assertion_id),
    )


def set_state(conn: Conn, assertion_id: str, state: str) -> None:
    conn.execute(
        "UPDATE matter_fact_assertions SET state = %s WHERE assertion_id = %s", (state, assertion_id)
    )


def set_evidence_only(conn: Conn, assertion_id: str, value: bool = True) -> None:
    conn.execute(
        "UPDATE matter_fact_assertions SET evidence_only = %s WHERE assertion_id = %s", (value, assertion_id)
    )


def flag_review(conn: Conn, assertion_id: str, reason: str) -> None:
    conn.execute(
        "UPDATE matter_fact_assertions SET needs_review = TRUE, review_reason = COALESCE(review_reason || '; ', '') || %s "
        "WHERE assertion_id = %s",
        (reason, assertion_id),
    )


def insert_link(
    conn: Conn, *, matter_id: str, assertion_id: str, link_type: str, target_assertion_id: str | None,
    target_chunk_id: str | None, batch_seq: int, rule_id: str,
) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO fact_links (matter_id, assertion_id, link_type, target_assertion_id, target_chunk_id, batch_seq, rule_id) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (matter_id, assertion_id, link_type, target_assertion_id, target_chunk_id, batch_seq, rule_id),
    )


def insert_ledger(
    conn: Conn, *, matter_id: str, batch_seq: int, assertion_id: str, change_type: str,
    previous_state: str | None, new_state: str, related_assertion_id: str | None, document_id: str | None, rule_id: str,
    reason: str | None, reviewer: str | None = None,
) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO fact_change_log (matter_id, batch_seq, assertion_id, change_type, previous_state, new_state, "
        "related_assertion_id, caused_by_document_id, rule_id, reviewer, reason) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (matter_id, batch_seq, assertion_id, change_type, previous_state, new_state, related_assertion_id, document_id,
         rule_id, reviewer, reason),
    )  # fmt: skip


def get_fact(conn: Conn, assertion_id: str) -> Row | None:
    try:
        return conn.execute(
            "SELECT * FROM matter_fact_assertions WHERE assertion_id = %s", (assertion_id,)
        ).fetchone()
    except psycopg.errors.InvalidTextRepresentation:
        conn.rollback()
        return None
