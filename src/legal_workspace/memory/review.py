"""Human review queue (blueprint §8.7): unresolved items are shown as 'disputed, needs review', never hidden."""

from __future__ import annotations

from typing import Any

from legal_workspace.db.pool import Conn

from ..db import facts as fact_repo
from ..db import matters as matter_repo
from ..domain.normalise import parse_amount, parse_bool, parse_date
from ..domain.slots import slot_def
from ..domain.types import ChangeType, FactState, VType
from ..errors import BadRequest, Conflict, NotFound, ValidationFailed

ACTIONS = ("CONFIRM", "SUPERSEDE_OTHERS", "DISPUTE", "EVIDENCE_ONLY", "CORRECT_VALUE", "WITHDRAW")


def list_items(conn: Conn, matter_id: str, ocr_threshold: float = 60.0) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT a.assertion_id, a.fact_key, a.assertion_text, a.review_reason, a.state, a.source_page, a.source_quote, "
        "a.learned_in_batch_seq, d.title, d.document_id FROM matter_fact_assertions a "
        "JOIN documents d ON d.document_id = a.originating_document_id WHERE a.matter_id = %s AND a.needs_review "
        "ORDER BY a.learned_in_batch_seq, a.created_at",
        (matter_id,),
    ).fetchall():
        items.append(
            {"kind": "FACT", "id": str(r["assertion_id"]), "title": r["assertion_text"], "reason": r["review_reason"], "state": r["state"],
             "document": r["title"], "document_id": str(r["document_id"]), "page": r["source_page"], "quote": r["source_quote"],
             "batch_seq": r["learned_in_batch_seq"], "fact_key": r["fact_key"]}
        )  # fmt: skip
    for r in conn.execute(
        "SELECT document_id, title, review_reason, batch_seq, original_filename FROM documents WHERE matter_id = %s "
        "AND needs_review AND status <> 'FAILED' ORDER BY batch_seq, created_at",
        (matter_id,),
    ).fetchall():
        items.append(
            {"kind": "DOCUMENT", "id": str(r["document_id"]), "title": r["title"], "reason": r["review_reason"], "state": "REVIEW",
             "document": r["title"], "document_id": str(r["document_id"]), "page": None, "quote": None, "batch_seq": r["batch_seq"]}
        )  # fmt: skip
    for r in conn.execute(
        "SELECT document_id, title, original_filename, error_message, batch_seq FROM documents WHERE matter_id = %s AND status = 'FAILED' "
        "ORDER BY batch_seq, created_at",
        (matter_id,),
    ).fetchall():
        items.append(
            {"kind": "FAILED_DOCUMENT", "id": str(r["document_id"]), "title": r["original_filename"], "reason": r["error_message"],
             "state": "FAILED", "document": r["original_filename"], "document_id": str(r["document_id"]), "page": None, "quote": None,
             "batch_seq": r["batch_seq"]}
        )  # fmt: skip
    for r in conn.execute(
        "SELECT p.document_id, p.page_number, p.ocr_confidence, d.title, d.batch_seq FROM document_pages p "
        "JOIN documents d USING (document_id) WHERE d.matter_id = %s AND p.ocr_confidence IS NOT NULL AND p.ocr_confidence < %s",
        (matter_id, ocr_threshold),
    ).fetchall():
        items.append(
            {"kind": "LOW_OCR_PAGE", "id": f"{r['document_id']}:{r['page_number']}", "title": f"{r['title']} page {r['page_number']}",
             "reason": f"OCR confidence {r['ocr_confidence']:.0f}%: check the page", "state": "REVIEW", "document": r["title"],
             "document_id": str(r["document_id"]), "page": r["page_number"], "quote": None, "batch_seq": r["batch_seq"]}
        )  # fmt: skip
    return items


def _retype(slot_vtype: VType, raw: str) -> dict[str, Any]:
    if slot_vtype == VType.DATE:
        d = parse_date(raw)
        if d is None:
            raise ValidationFailed(f"cannot read a date from {raw!r}")
        return {"value_text": d.isoformat(), "value_date": d}
    if slot_vtype == VType.AMOUNT:
        a = parse_amount(raw)
        if a is None:
            raise ValidationFailed(f"cannot read an amount from {raw!r}")
        return {"value_text": str(a), "value_amount": a}
    if slot_vtype == VType.BOOL:
        b = parse_bool(raw)
        if b is None:
            raise ValidationFailed(f"cannot read true/false from {raw!r}")
        return {"value_text": str(b).lower(), "value_bool": b}
    if not raw.strip():
        raise ValidationFailed("a value is required")
    return {"value_text": raw.strip()}


def resolve_fact(
    conn: Conn, matter_id: str, assertion_id: str, *, action: str, reviewer: str, reason: str, value: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Apply a reviewer's decision. Every action writes a MANUAL ledger row with the reviewer's name and reason."""
    if action not in ACTIONS:
        raise BadRequest(f"action must be one of {ACTIONS}")
    if not reviewer.strip() or not reason.strip():
        raise ValidationFailed("a reviewer name and a reason are required")
    fact = fact_repo.get_fact(conn, assertion_id)
    if fact is None or str(fact["matter_id"]) != matter_id:
        raise NotFound(f"fact {assertion_id} not found in this matter")
    batch = matter_repo.latest_committed_seq(conn, matter_id)
    if batch == 0:
        raise Conflict("no committed batch yet")
    if fact["ended_in_batch_seq"] is not None and action != "CONFIRM":
        raise Conflict("this fact has already ended; it can no longer be changed")
    prev = fact["state"]
    new_state, change = prev, ChangeType.NEW

    if action == "CONFIRM":
        change = ChangeType.NEW
    elif action == "SUPERSEDE_OTHERS":
        for c in fact_repo.current_facts(conn, matter_id, fact["fact_key"]):
            if c.assertion_id != assertion_id and not c.evidence_only:
                fact_repo.end_fact(conn, c.assertion_id, batch, assertion_id)
                fact_repo.insert_ledger(conn, matter_id=matter_id, batch_seq=batch, assertion_id=c.assertion_id, change_type="SUPERSEDED",
                                        previous_state=c.state.value, new_state="SUPERSEDED", related_assertion_id=assertion_id,
                                        document_id=None, rule_id="MANUAL", reason=reason, reviewer=reviewer)  # fmt: skip
        fact_repo.set_state(conn, assertion_id, "ACTIVE")
        fact_repo.set_evidence_only(conn, assertion_id, False)
        new_state, change = "ACTIVE", ChangeType.NEW
    elif action == "DISPUTE":
        for c in fact_repo.current_facts(conn, matter_id, fact["fact_key"]):
            if not c.evidence_only and c.state != FactState.DISPUTED:
                fact_repo.set_state(conn, c.assertion_id, "DISPUTED")
                if c.assertion_id != assertion_id:
                    fact_repo.insert_ledger(conn, matter_id=matter_id, batch_seq=batch, assertion_id=c.assertion_id, change_type="DISPUTED",
                                            previous_state=c.state.value, new_state="DISPUTED", related_assertion_id=assertion_id,
                                            document_id=None, rule_id="MANUAL", reason=reason, reviewer=reviewer)  # fmt: skip
        new_state, change = "DISPUTED", ChangeType.DISPUTED
    elif action == "EVIDENCE_ONLY":
        fact_repo.set_evidence_only(conn, assertion_id, True)
        change = ChangeType.CONTRADICTED_BY_EVIDENCE
    elif action == "WITHDRAW":
        fact_repo.end_fact(conn, assertion_id, batch, None)
        conn.execute(
            "UPDATE matter_fact_assertions SET state = 'WITHDRAWN' WHERE assertion_id = %s", (assertion_id,)
        )
        new_state, change = "WITHDRAWN", ChangeType.WITHDRAWN
    elif action == "CORRECT_VALUE":
        sd = slot_def(fact["subject_type"], fact["slot"])
        if value is None or sd is None:
            raise ValidationFailed("a corrected value is required")
        typed = _retype(sd.vtype, value)
        cols = {"value_text": None, "value_date": None, "value_amount": None, "value_bool": None, **typed}
        conn.execute(
            "UPDATE matter_fact_assertions SET value_text = %(value_text)s, value_date = %(value_date)s, value_amount = %(value_amount)s, "
            "value_bool = %(value_bool)s WHERE assertion_id = %(id)s",
            {**cols, "id": assertion_id},
        )
        change = ChangeType.NEW

    conn.execute(
        "UPDATE matter_fact_assertions SET needs_review = FALSE WHERE assertion_id = %s", (assertion_id,)
    )
    fact_repo.insert_ledger(conn, matter_id=matter_id, batch_seq=batch, assertion_id=assertion_id, change_type=change.value,
                            previous_state=prev, new_state=new_state, related_assertion_id=None, document_id=None, rule_id="MANUAL",
                            reason=f"{action}: {reason}", reviewer=reviewer)  # fmt: skip
    return {"assertion_id": assertion_id, "action": action, "state": new_state, "batch_seq": batch}


def confirm_document(conn: Conn, matter_id: str, document_id: str) -> None:
    row = conn.execute("SELECT matter_id FROM documents WHERE document_id = %s", (document_id,)).fetchone()
    if row is None or str(row["matter_id"]) != matter_id:
        raise NotFound("document not found in this matter")
    conn.execute("UPDATE documents SET needs_review = FALSE WHERE document_id = %s", (document_id,))
