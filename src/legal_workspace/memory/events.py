"""Chronology: events derived by code from documents and dated facts (blueprint §9.2 plan 2)."""

from __future__ import annotations

from datetime import date
from typing import Any

from legal_workspace.db.pool import Conn

from ..domain.normalise import fmt_date
from ..domain.types import DocType

_DOC_EVENTS: dict[DocType, tuple[str, str]] = {
    DocType.CONTRACT: ("CONTRACT_SIGNED", "{title} executed"),
    DocType.SOW: ("CONTRACT_SIGNED", "{title} executed"),
    DocType.PURCHASE_ORDER: ("PURCHASE_ORDER", "{title} issued"),
    DocType.AMENDMENT: ("CONTRACT_AMENDED", "{title} executed"),
    DocType.CHANGE_REQUEST: ("CHANGE_REQUESTED", "{title}"),
    DocType.SIGNED_MINUTES: ("MEETING", "{title}"),
    DocType.UNSIGNED_MINUTES: ("MEETING", "{title}"),
    DocType.LEGAL_NOTICE: ("NOTICE_SENT", "{title} sent"),
    DocType.REPLY_NOTICE: ("NOTICE_REPLIED", "{title} sent"),
    DocType.PLAINT: ("SUIT_FILED", "Suit filed: {title}"),
    DocType.WRITTEN_STATEMENT: ("WRITTEN_STATEMENT_FILED", "{title} filed"),
    DocType.REPLICATION: ("PLEADING_FILED", "{title} filed"),
    DocType.REJOINDER: ("PLEADING_FILED", "{title} filed"),
    DocType.COUNTERCLAIM: ("PLEADING_FILED", "{title} filed"),
    DocType.AMENDED_PLEADING: ("PLEADING_FILED", "{title} filed"),
    DocType.AFFIDAVIT: ("AFFIDAVIT_FILED", "{title} filed"),
    DocType.APPLICATION: ("APPLICATION_FILED", "{title} filed"),
    DocType.ORDER: ("ORDER_PASSED", "Order passed: {title}"),
    DocType.EMAIL: ("CORRESPONDENCE", "E-mail: {title}"),
    DocType.LETTER: ("CORRESPONDENCE", "Letter: {title}"),
    DocType.HEARING_NOTE: ("HEARING", "Hearing note: {title}"),
    DocType.INVOICE: ("INVOICE_RAISED", "{title} raised"),
}

# (subject type, slot) -> (event type, description prefix)
_FACT_EVENTS: dict[tuple[str, str], tuple[str, str]] = {
    ("CONTRACT", "effective_date"): ("CONTRACT_EFFECTIVE", "Contract effective"),
    ("CONTRACT", "delivery_date"): ("DELIVERY_DUE", "Delivery / completion due"),
    ("MILESTONE", "due_date"): ("MILESTONE_DUE", "Milestone due"),
    ("MILESTONE", "acceptance_date"): ("MILESTONE_ACCEPTED", "Milestone accepted"),
    ("INVOICE", "invoice_date"): ("INVOICE_RAISED", "Invoice raised"),
    ("INVOICE", "due_date"): ("PAYMENT_DUE", "Invoice payment due"),
    ("NOTICE", "sent_date"): ("NOTICE_SENT", "Notice sent"),
    ("NOTICE", "received_date"): ("NOTICE_RECEIVED", "Notice received"),
    ("PAYMENT", "date"): ("PAYMENT", "Payment"),
    ("HEARING", "next_date"): ("HEARING_LISTED", "Next hearing"),
    ("DIRECTION", "due_date"): ("DIRECTION_DUE", "Court-directed deadline"),
}


def derive_events(
    conn: Conn,
    matter_id: str,
    batch_seq: int,
    doc: dict[str, Any],
    applied: list[dict[str, Any]],
) -> int:
    n = 0
    doc_type = DocType(doc["document_type"])
    has_sent_date = any(
        a["rf"].fact.subject_type == "NOTICE" and a["rf"].fact.slot == "sent_date" for a in applied
    )
    has_invoice_date = any(
        a["rf"].fact.subject_type == "INVOICE" and a["rf"].fact.slot == "invoice_date" for a in applied
    )
    ev = _DOC_EVENTS.get(doc_type)
    skip_doc_event = (doc_type in (DocType.LEGAL_NOTICE, DocType.REPLY_NOTICE) and has_sent_date) or (
        doc_type == DocType.INVOICE and has_invoice_date
    )
    if ev and doc["document_date"] and not skip_doc_event:
        _insert(
            conn,
            matter_id,
            batch_seq,
            doc,
            ev[0],
            ev[1].format(title=doc["title"]),
            doc["document_date"],
            None,
            1,
            doc.get("author_party_id"),
        )
        n += 1
    amounts = {
        a["rf"].subject_ref: a["rf"].fact.value
        for a in applied
        if a["rf"].fact.subject_type == "PAYMENT" and a["rf"].fact.slot == "amount"
    }
    for a in applied:
        rf = a["rf"]
        spec = _FACT_EVENTS.get((rf.fact.subject_type, rf.fact.slot))
        d: date | None = rf.fact.value.date
        if not spec or d is None:
            continue
        text = f"{spec[1]}: {fmt_date(d)}" if spec[0] != "PAYMENT" else "Payment received"
        if spec[0] == "PAYMENT" and rf.subject_ref in amounts and amounts[rf.subject_ref].amount is not None:
            from ..domain.normalise import format_inr

            text = f"Payment of ₹{format_inr(amounts[rf.subject_ref].amount)} received"
        elif spec[0] in ("DELIVERY_DUE", "MILESTONE_DUE", "PAYMENT_DUE", "DIRECTION_DUE", "HEARING_LISTED"):
            text = rf.fact.assertion_text
        _insert(
            conn,
            matter_id,
            batch_seq,
            doc,
            spec[0],
            text,
            d,
            a["assertion_id"],
            rf.fact.page,
            rf.fact.party_id,
        )
        n += 1
    return n


def _insert(conn, matter_id, batch_seq, doc, etype, description, when, assertion_id, page, party_id) -> None:  # noqa: ANN001
    conn.execute(
        "INSERT INTO matter_events (matter_id, event_date, event_type, description, party_id, assertion_id, source_document_id, "
        "source_page, learned_in_batch_seq) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (matter_id, when, etype, description, party_id, assertion_id, doc["document_id"], page, batch_seq),
    )
