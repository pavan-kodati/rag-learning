"""Court directions, undertakings and deadlines (blueprint §8.6)."""

from __future__ import annotations

from typing import Any

from legal_workspace.db.pool import Conn

from ..db import facts as fact_repo
from ..domain.authority import STEP_FULFILLED_BY
from ..domain.types import ChangeType


def create_rows(
    conn: Conn, matter_id: str, doc: dict[str, Any], applied: list[Any], resolve_party: Any
) -> int:
    """One `court_directions` row per direction / next-hearing fact of an order. Returns rows created."""
    if doc["document_date"] is None:
        return 0
    created = 0
    siblings: dict[str, dict[str, Any]] = {}
    for a in applied:
        rf = a["rf"]
        if rf.fact.subject_type == "DIRECTION":
            siblings.setdefault(rf.subject_ref, {})[rf.fact.slot] = a
    for step, slots in siblings.items():
        due_fact = slots.get("due_date")
        if due_fact is None:
            continue
        rf = due_fact["rf"]
        info = rf.direction
        due = info.due if info else None
        responsible = slots.get("responsible_party")
        resp_name = (
            responsible["rf"].fact.value.text if responsible else (info.responsible_text if info else "")
        )
        party = resolve_party(resp_name) if resp_name else None
        kind = info.kind if info else "DIRECTION"
        conn.execute(
            "INSERT INTO court_directions (matter_id, assertion_id, order_document_id, order_date, direction_ref, kind, "
            "procedural_step, direction_text, responsible_party_id, period_text, period_days, period_months, trigger_date, "
            "due_date, weekend_flag, source_page) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (assertion_id) DO NOTHING",
            (
                matter_id, due_fact["assertion_id"], doc["document_id"], doc["document_date"], None, kind, step,
                rf.fact.quote, party["party_id"] if party else None, due.period.text if due else None,
                due.period.days if due else None, due.period.months if due else None, due.trigger_date if due else None,
                due.due_date if due else None, bool(due and due.weekend), rf.fact.page,
            ),
        )  # fmt: skip
        created += 1
    for a in applied:  # "listed on <date>" -> a NEXT_HEARING row whose due date is the hearing date
        rf = a["rf"]
        if rf.fact.subject_type == "HEARING" and rf.fact.slot == "next_date" and rf.fact.value.date:
            conn.execute(
                "INSERT INTO court_directions (matter_id, assertion_id, order_document_id, order_date, kind, procedural_step, "
                "direction_text, due_date, weekend_flag, source_page) VALUES (%s,%s,%s,%s,'NEXT_HEARING','next_hearing',%s,%s,%s,%s) "
                "ON CONFLICT (assertion_id) DO NOTHING",
                (matter_id, a["assertion_id"], doc["document_id"], doc["document_date"], rf.fact.quote, rf.fact.value.date,
                 rf.fact.value.date.weekday() >= 5, rf.fact.page),
            )  # fmt: skip
            created += 1
    return created


def update_compliance(conn: Conn, matter_id: str, batch_seq: int) -> int:
    """Mark pending directions COMPLIED when the matching filing by the responsible party is now in the matter."""
    pending = conn.execute(
        "SELECT cd.*, a.state AS fact_state FROM court_directions cd JOIN matter_fact_assertions a USING (assertion_id) "
        "WHERE cd.matter_id = %s AND cd.compliance_status = 'PENDING' AND a.ended_in_batch_seq IS NULL AND NOT a.evidence_only "
        "AND cd.kind <> 'NEXT_HEARING'",
        (matter_id,),
    ).fetchall()
    n = 0
    for cd in pending:
        types = STEP_FULFILLED_BY.get(cd["procedural_step"])
        if not types:
            continue
        cand = conn.execute(
            "SELECT document_id, document_date FROM documents WHERE matter_id = %s AND status = 'PROCESSED' "
            "AND document_type = ANY(%s) AND document_date >= %s AND (%s::uuid IS NULL OR author_party_id = %s::uuid) "
            "ORDER BY document_date, created_at LIMIT 1",
            (
                matter_id,
                [t.value for t in types],
                cd["order_date"],
                cd["responsible_party_id"],
                cd["responsible_party_id"],
            ),
        ).fetchone()
        if not cand:
            continue
        late = bool(cd["due_date"] and cand["document_date"] > cd["due_date"])
        conn.execute(
            "UPDATE court_directions SET compliance_status = 'COMPLIED', complied_by_document_id = %s, complied_late = %s "
            "WHERE direction_id = %s",
            (cand["document_id"], late, cd["direction_id"]),
        )
        fact_repo.insert_ledger(
            conn, matter_id=matter_id, batch_seq=batch_seq, assertion_id=str(cd["assertion_id"]),
            change_type=ChangeType.COMPLIED.value, previous_state=cd["fact_state"], new_state=cd["fact_state"],
            related_assertion_id=None, document_id=str(cand["document_id"]), rule_id="COMPLY",
            reason="filed late" if late else "filed within time",
        )  # fmt: skip
        n += 1
    return n
