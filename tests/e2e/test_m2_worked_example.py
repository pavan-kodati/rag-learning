"""S05: the blueprint's worked example (Vardhan v Kestrel), end to end through upload, worker and reconciliation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from legal_workspace.memory import queries
from legal_workspace.memory.reports import render_text

pytestmark = [pytest.mark.db, pytest.mark.e2e]


def facts(conn, mid, key, as_of=None, evidence=False):
    mid = str(mid)
    if as_of is None:
        rows = conn.execute(
            "SELECT * FROM matter_fact_assertions WHERE matter_id = %s AND fact_key = %s ORDER BY created_at",
            (mid, key),
        ).fetchall()
        return rows
    return [
        f for f in queries.facts_as_of(conn, mid, as_of, include_evidence=evidence) if f["fact_key"] == key
    ]


def test_batch_one_builds_the_initial_position(m2):
    conn, mid = m2["conn"], m2["matter"]["matter_id"]
    report = m2["replay_next"](1)
    assert report["documents_processed"] == 5 and not report["documents_failed"]
    # parties were discovered from the documents, with roles from the pleadings
    roles = {
        p["canonical_name"]: p["role"]
        for p in conn.execute("SELECT * FROM parties WHERE matter_id = %s", (mid,)).fetchall()
    }
    assert roles == {"Vardhan Infotech Private Limited": "PLAINTIFF", "Kestrel Limited": "DEFENDANT"}

    # delivery date: the contract term is current; the plaint's restatement corroborates; two e-mail proposals are evidence only
    rows = facts(conn, mid, "contract/msa-2023/delivery_date")
    by_doc = {(r["originating_document_id"], r["value_date"]): r for r in rows}
    assert len(rows) == 4
    current = [r for r in rows if not r["evidence_only"]]
    assert (
        len(current) == 1
        and current[0]["value_date"] == date(2024, 6, 30)
        and current[0]["state"] == "ACTIVE"
    )
    assert sum(1 for r in rows if r["evidence_only"]) == 3
    assert by_doc

    out = facts(conn, mid, "invoice/inv-014/amount_outstanding")
    assert len(out) == 1 and out[0]["value_amount"] == Decimal("1840000.00") and out[0]["state"] == "ACTIVE"
    notice = facts(conn, mid, "notice/2025-02-05-vardhan/received")
    assert len(notice) == 1 and notice[0]["value_bool"] is True and notice[0]["state"] == "ACTIVE"
    assert (
        conn.execute("SELECT count(*) AS n FROM court_directions WHERE matter_id = %s", (mid,)).fetchone()[
            "n"
        ]
        == 0
    )

    kinds = {
        (r["change_type"], r["rule_id"])
        for r in conn.execute(
            "SELECT change_type, rule_id FROM fact_change_log WHERE batch_seq = 1"
        ).fetchall()
    }
    assert {("NEW", "R0"), ("CORROBORATED", "R1"), ("NEW", "R8")} <= kinds


def test_batch_two_supersedes_narrows_disputes_and_adds_directions(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    report = m2["replay_next"](2)
    assert report["documents_processed"] == 4 and report["duplicates_skipped"] == [
        "07b_Bank_statement_duplicate.pdf"
    ]
    types = {(c["change_type"], c["rule_id"], c["fact_key"]) for c in report["changes"]}
    assert ("SUPERSEDED", "R2", "contract/msa-2023/delivery_date") in types
    assert ("NARROWED", "R5", "invoice/inv-014/amount_outstanding") in types
    assert ("DISPUTED", "R6", "notice/2025-02-05-vardhan/received") in types
    assert ("NEW", "R0", "direction/replication/due_date") in types

    d = [r for r in facts(conn, mid, "contract/msa-2023/delivery_date") if not r["evidence_only"]]
    assert {(r["value_date"], r["state"], r["ended_in_batch_seq"]) for r in d} == {
        (date(2024, 6, 30), "SUPERSEDED", 2),
        (date(2024, 7, 31), "ACTIVE", None),
    }
    out = facts(conn, mid, "invoice/inv-014/amount_outstanding")
    assert {(r["value_amount"], r["state"], r["derived"]) for r in out} == {
        (Decimal("1840000.00"), "SUPERSEDED", False),
        (Decimal("1240000.00"), "ACTIVE", True),
    }
    notice = facts(conn, mid, "notice/2025-02-05-vardhan/received")
    assert {(r["value_bool"], r["state"]) for r in notice} == {(True, "DISPUTED"), (False, "DISPUTED")}

    text = render_text(report)
    assert (
        "SUPERSEDED" in text
        and "NARROWED" in text
        and "DISPUTED" in text
        and "12,40,000" in text
        and "31 Jul 2024" in text
    )


def test_as_of_views_reproduce_each_batch(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    m2["replay_next"](2)
    one = {f["fact_key"]: f for f in queries.facts_as_of(conn, mid, 1)}
    two = {f["fact_key"]: f for f in queries.facts_as_of(conn, mid, 2)}
    assert (
        one["contract/msa-2023/delivery_date"]["value_date"] == date(2024, 6, 30)
        and one["contract/msa-2023/delivery_date"]["state"] == "ACTIVE"
    )
    assert two["contract/msa-2023/delivery_date"]["value_date"] == date(2024, 7, 31)
    assert one["invoice/inv-014/amount_outstanding"]["value_amount"] == Decimal("1840000.00")
    assert two["invoice/inv-014/amount_outstanding"]["value_amount"] == Decimal("1240000.00")
    assert not any(k.startswith("direction/") for k in one) and any(k.startswith("direction/") for k in two)
    # the as-of-1 view contains no fact that was only learned in batch 2
    assert all(
        f["learned_in_batch_seq"] <= 1 for f in queries.facts_as_of(conn, mid, 1, include_evidence=True)
    )
    # a self-check from the blueprint: batch 2 minus batch 1 equals the ledger of batch 2
    first_rows = conn.execute(
        "SELECT count(*) AS n FROM fact_change_log WHERE batch_seq = 2 AND previous_state IS NULL"
    ).fetchone()["n"]
    learned = conn.execute(
        "SELECT count(*) AS n FROM matter_fact_assertions WHERE matter_id = %s AND learned_in_batch_seq = 2",
        (mid,),
    ).fetchone()["n"]
    assert first_rows == learned


def test_directions_have_computed_deadlines_and_statuses(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    m2["replay_next"](2)
    rows = {r["procedural_step"]: r for r in queries.directions(conn, mid, 2, date(2025, 10, 20))}
    assert rows["replication"]["due_date"] == date(2025, 10, 10)  # 12 Sep 2025 + 28 days (blueprint example)
    assert (
        rows["replication"]["status"] == "OVERDUE"
        and rows["replication"]["responsible_party"] == "Vardhan Infotech Private Limited"
    )
    assert (
        rows["admission_denial_of_documents"]["due_date"] == date(2025, 10, 24)
        and rows["admission_denial_of_documents"]["status"] == "PENDING"
    )
    assert rows["next_hearing"]["due_date"] == date(2025, 11, 14)
    assert {r["status"] for r in queries.directions(conn, mid, 2, date(2025, 9, 13))} == {"PENDING"}


def test_chronology_strikes_through_superseded_events(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    ev1 = queries.chronology(conn, mid, 1)
    assert [e["event_date"] for e in ev1] == sorted(e["event_date"] for e in ev1)
    due1 = next(e for e in ev1 if e["event_type"] == "DELIVERY_DUE" and e["event_date"] == date(2024, 6, 30))
    assert due1["state"] == "ACTIVE"
    m2["replay_next"](2)
    ev2 = queries.chronology(conn, mid, 2)
    due2 = next(
        e
        for e in ev2
        if e["event_type"] == "DELIVERY_DUE"
        and e["event_date"] == date(2024, 6, 30)
        and not e["evidence_only"]
    )
    assert due2["state"] == "SUPERSEDED" and "Amendment" in due2["superseded_by"]
    assert any(
        e["event_type"] == "CONTRACT_AMENDED" and e["event_date"] == date(2024, 5, 10) for e in ev2
    )  # learned in batch 2, dated before batch-1 events
    assert any(e["event_type"] == "PAYMENT" and "6,00,000" in e["description"] for e in ev2)


def test_every_fact_has_a_verbatim_source_quote_on_its_page(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    m2["replay_next"](2)
    rows = conn.execute(
        "SELECT a.source_quote, a.source_page, a.derived, p.page_text FROM matter_fact_assertions a "
        "JOIN document_pages p ON p.document_id = a.originating_document_id AND p.page_number = a.source_page WHERE a.matter_id = %s",
        (mid,),
    ).fetchall()
    assert rows
    for r in rows:
        assert " ".join(r["source_quote"].lower().split()) in " ".join(r["page_text"].lower().split()), r[
            "source_quote"
        ]


def test_links_connect_claims_to_evidence(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    m2["replay_next"](2)
    kinds = {
        r["link_type"]
        for r in conn.execute("SELECT link_type FROM fact_links WHERE matter_id = %s", (mid,)).fetchall()
    }
    assert {"SUPPORTS", "CONTRADICTS", "SUPERSEDES"} <= kinds


def test_batch_ledger_is_complete_every_fact_has_a_new_row(m2):
    conn, mid = m2["conn"], str(m2["matter"]["matter_id"])
    m2["replay_next"](1)
    m2["replay_next"](2)
    missing = conn.execute(
        "SELECT count(*) AS n FROM matter_fact_assertions a WHERE a.matter_id = %s AND NOT EXISTS "
        "(SELECT 1 FROM fact_change_log l WHERE l.assertion_id = a.assertion_id AND l.previous_state IS NULL)",
        (mid,),
    ).fetchone()["n"]
    assert missing == 0
    assert (
        conn.execute(
            "SELECT status FROM ingestion_batches WHERE matter_id = %s ORDER BY batch_seq", (mid,)
        ).fetchall()
        == [{"status": "COMMITTED"}] * 2
    )
