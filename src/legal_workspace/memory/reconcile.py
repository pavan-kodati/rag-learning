"""Reconciliation (blueprint §8.4): documents -> facts, links and ledger rows, in one transaction.

No model is called here. Models only *read* documents (classify, extract); this module, using the authority rules
in `domain.rules`, decides what changes. Documents of a batch are reconciled in document-date order under a
per-matter advisory lock, so two amendments in one batch apply in the order of their dates.
"""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from typing import Any

from legal_workspace.db.pool import Conn

from ..db import chunks as chunk_repo
from ..db import documents as doc_repo
from ..db import facts as fact_repo
from ..db import matters as matter_repo
from ..db.pool import advisory_lock
from ..deps import Deps
from ..domain.normalise import format_inr
from ..domain.rules import decide
from ..domain.subjects import NoticeRef, notice_id, party_slug
from ..domain.types import (
    Action,
    Authority,
    ChangeType,
    DocType,
    FactState,
    FactValue,
    LinkType,
    NewFact,
)
from . import directions, events
from .resolve import ResolveContext, ResolvedFact, resolve_items

log = logging.getLogger(__name__)


def _own_notice(doc: dict[str, Any], author: dict[str, Any] | None) -> NoticeRef | None:
    if doc["document_type"] in ("LEGAL_NOTICE", "REPLY_NOTICE") and doc["document_date"] and author:
        slug = party_slug(author["canonical_name"])
        return NoticeRef(notice_id(doc["document_date"], slug), doc["document_date"], slug)
    return None


def apply_fact(
    conn: Conn,
    matter_id: str,
    batch_seq: int,
    doc: dict[str, Any],
    rf: ResolvedFact,
    extra_review: str | None = None,
) -> dict[str, Any]:
    """Decide and persist one fact: the fact row, effects on older facts, links and ledger rows."""
    nf = rf.fact
    current = fact_repo.current_facts(conn, matter_id, nf.fact_key)
    decision = decide(nf, current)
    by_id = {c.assertion_id: c for c in current}
    state = decision.new_state
    born_superseded = state == FactState.SUPERSEDED
    needs_review = nf.needs_review or decision.needs_review or bool(extra_review)
    review_reason = (
        "; ".join(x for x in (nf.review_reason, decision.review_reason, extra_review) if x) or None
    )

    aid = fact_repo.insert_fact(
        conn, matter_id=matter_id, fact_key=nf.fact_key, subject_type=nf.subject_type, slot=nf.slot,
        assertion_category=nf.category, asserting_party_id=nf.party_id, assertion_text=nf.assertion_text,
        value_text=nf.value.text, value_date=nf.value.date, value_amount=nf.value.amount, value_bool=nf.value.boolean,
        value_number=nf.value.number, originating_document_id=nf.document_id, source_chunk_id=rf.chunk_id,
        source_page=nf.page, source_quote=nf.quote, assertion_date=nf.doc_date, effective_from=nf.effective_from,
        learned_in_batch_seq=batch_seq, ended_in_batch_seq=batch_seq if born_superseded else None, state=state.value,
        evidence_only=decision.new_evidence_only, derived=nf.derived,
        superseded_by_assertion_id=decision.effects[0].assertion_id if born_superseded and decision.effects else None,
        needs_review=needs_review, review_reason=review_reason,
    )  # fmt: skip

    for e in decision.effects:
        old = by_id[e.assertion_id]
        if e.action == Action.END:
            fact_repo.end_fact(conn, e.assertion_id, batch_seq, aid)
            fact_repo.insert_ledger(
                conn, matter_id=matter_id, batch_seq=batch_seq, assertion_id=e.assertion_id, change_type=e.change_type.value,
                previous_state=old.state.value, new_state=FactState.SUPERSEDED.value, related_assertion_id=aid,
                document_id=nf.document_id, rule_id=e.rule_id, reason=e.reason,
            )  # fmt: skip
        elif e.action == Action.MARK_DISPUTED:
            if old.state != FactState.DISPUTED:
                fact_repo.set_state(conn, e.assertion_id, FactState.DISPUTED.value)
                fact_repo.insert_ledger(
                    conn, matter_id=matter_id, batch_seq=batch_seq, assertion_id=e.assertion_id, change_type=e.change_type.value,
                    previous_state=old.state.value, new_state=FactState.DISPUTED.value, related_assertion_id=aid,
                    document_id=nf.document_id, rule_id=e.rule_id, reason=e.reason,
                )  # fmt: skip
            if decision.needs_review:
                fact_repo.flag_review(conn, e.assertion_id, e.reason)
        elif e.action == Action.MARK_EVIDENCE_ONLY:
            fact_repo.set_evidence_only(conn, e.assertion_id, True)
            fact_repo.insert_ledger(
                conn, matter_id=matter_id, batch_seq=batch_seq, assertion_id=e.assertion_id, change_type=e.change_type.value,
                previous_state=old.state.value, new_state=old.state.value, related_assertion_id=aid,
                document_id=nf.document_id, rule_id=e.rule_id, reason=e.reason,
            )  # fmt: skip
        if e.link:
            fact_repo.insert_link(
                conn, matter_id=matter_id, assertion_id=e.assertion_id if e.reverse else aid, link_type=e.link.value,
                target_assertion_id=aid if e.reverse else e.assertion_id, target_chunk_id=None, batch_seq=batch_seq,
                rule_id=e.rule_id,
            )  # fmt: skip

    fact_repo.insert_ledger(
        conn, matter_id=matter_id, batch_seq=batch_seq, assertion_id=aid, change_type=decision.change_type.value,
        previous_state=None, new_state=state.value, related_assertion_id=decision.effects[0].assertion_id if decision.effects else None,
        document_id=nf.document_id, rule_id=decision.rule_id, reason=decision.reason or "first statement of this fact",
    )  # fmt: skip
    return {"assertion_id": aid, "rf": rf, "decision": decision}


def reconcile_document(
    conn: Conn, deps: Deps, matter_id: str, batch_seq: int, doc: dict[str, Any]
) -> list[dict[str, Any]]:
    extraction = doc_repo.get_extraction(conn, str(doc["document_id"]))
    items = extraction["items"] if extraction else []
    author = None
    if doc["author_party_id"]:
        row = conn.execute("SELECT * FROM parties WHERE party_id = %s", (doc["author_party_id"],)).fetchone()
        author = row
    ctx = ResolveContext(
        doc=doc, registry=doc_repo.contract_registry(conn, matter_id), notices=doc_repo.notice_registry(conn, matter_id),
        resolve_party=lambda text: matter_repo.resolve_party(conn, matter_id, text), author=author,
        children=chunk_repo.list_children(conn, str(doc["document_id"])), own_notice=_own_notice(doc, author),
    )  # fmt: skip
    resolved = resolve_items(items, ctx)
    uncertain = (
        doc["classification_confidence"] is not None
        and doc["classification_confidence"] < deps.settings.classification_min_confidence
    )
    applied = [
        apply_fact(conn, matter_id, batch_seq, doc, rf, "document type uncertain: facts need review" if uncertain else None)
        for rf in resolved
    ]  # fmt: skip
    directions.create_rows(conn, matter_id, doc, applied, ctx.resolve_party)
    events.derive_events(conn, matter_id, batch_seq, doc, applied)
    return applied


def recompute_outstanding(conn: Conn, matter_id: str, batch_seq: int) -> int:
    """R5: outstanding = invoice amount - recorded payments against that invoice, computed by code."""
    invoices = conn.execute(
        "SELECT DISTINCT split_part(fact_key, '/', 2) AS inv FROM matter_fact_assertions WHERE matter_id = %s "
        "AND subject_type = 'INVOICE' AND slot = 'invoice_amount' AND ended_in_batch_seq IS NULL AND NOT evidence_only",
        (matter_id,),
    ).fetchall()
    n = 0
    for r in invoices:
        inv = r["inv"]
        amounts = conn.execute(
            "SELECT DISTINCT value_amount FROM matter_fact_assertions WHERE matter_id = %s AND fact_key = %s "
            "AND ended_in_batch_seq IS NULL AND NOT evidence_only",
            (matter_id, f"invoice/{inv}/invoice_amount"),
        ).fetchall()
        if len(amounts) != 1 or amounts[0]["value_amount"] is None:
            continue  # unknown or disputed invoice amount: do not compute
        invoice_amount: Decimal = amounts[0]["value_amount"]
        pays = conn.execute(
            "SELECT p.* FROM matter_fact_assertions p JOIN matter_fact_assertions ag "
            "ON ag.matter_id = p.matter_id AND ag.fact_key = replace(p.fact_key, '/amount', '/against_invoice') "
            "WHERE p.matter_id = %s AND p.subject_type = 'PAYMENT' AND p.slot = 'amount' AND p.ended_in_batch_seq IS NULL "
            "AND NOT p.evidence_only AND ag.ended_in_batch_seq IS NULL AND NOT ag.evidence_only AND ag.value_text = %s "
            "ORDER BY p.assertion_date NULLS LAST, p.created_at",
            (matter_id, inv),
        ).fetchall()
        if not pays:
            continue
        unique: dict[str, dict[str, Any]] = {}
        for p in pays:
            unique.setdefault(p["fact_key"], p)
        paid = sum((p["value_amount"] or Decimal(0)) for p in unique.values())
        computed = max(invoice_amount - paid, Decimal(0))
        existing = [
            c
            for c in fact_repo.current_facts(conn, matter_id, f"invoice/{inv}/amount_outstanding")
            if not c.evidence_only
        ]
        if existing and all(c.value.amount == computed for c in existing):
            continue
        last = list(unique.values())[-1]
        doc = doc_repo.get_document(conn, str(last["originating_document_id"]))
        text = (
            f"Outstanding on {inv.upper()}: ₹{format_inr(computed)} "
            f"(invoice ₹{format_inr(invoice_amount)} less payments ₹{format_inr(paid)}, computed)"
        )
        nf = NewFact(
            fact_key=f"invoice/{inv}/amount_outstanding", slot="amount_outstanding",
            value=FactValue(text=str(computed), amount=computed), party_id=None, party_role=None, authority=Authority.RECORD,
            doc_type=DocType(doc["document_type"]), doc_date=doc["document_date"], signed_by_all=False,
            document_id=str(doc["document_id"]), page=last["source_page"], quote=last["source_quote"], assertion_text=text,
            category="EVENT_FACT", subject_type="INVOICE", derived=True,
            needs_review=paid > invoice_amount, review_reason="payments exceed the invoice amount" if paid > invoice_amount else None,
        )  # fmt: skip
        apply_fact(
            conn,
            matter_id,
            batch_seq,
            doc,
            ResolvedFact(nf, inv, {}, str(last["source_chunk_id"]) if last["source_chunk_id"] else None),
        )
        n += 1
    return n


def reconcile_batch(conn: Conn, deps: Deps, matter_id: str, batch_seq: int) -> dict[str, Any]:
    """Reconcile every extracted document of the batch, recompute derived values, then commit the batch."""
    with advisory_lock(conn, matter_id):
        batch = matter_repo.get_batch(conn, matter_id, batch_seq)
        if batch["status"] == "COMMITTED":
            return {"already_committed": True}
        docs = conn.execute(
            "SELECT * FROM documents WHERE matter_id = %s AND batch_seq = %s ORDER BY document_date NULLS LAST, created_at",
            (matter_id, batch_seq),
        ).fetchall()
        stats: Counter[str] = Counter()
        failed = 0
        for doc in docs:
            if doc["status"] == "FAILED":
                failed += 1
                continue
            if doc["status"] != "EXTRACTED":
                doc_repo.update_document(
                    conn,
                    str(doc["document_id"]),
                    status="FAILED",
                    error_message=f"not processed (status {doc['status']})",
                )
                failed += 1
                continue
            for a in reconcile_document(conn, deps, matter_id, batch_seq, doc):
                stats[a["decision"].rule_id] += 1
            doc_repo.update_document(conn, str(doc["document_id"]), status="PROCESSED")
        stats["R5"] += recompute_outstanding(conn, matter_id, batch_seq)
        complied = directions.update_compliance(conn, matter_id, batch_seq)
        matter_repo.set_batch_status(conn, matter_id, batch_seq, "COMMITTED")
        conn.execute("UPDATE matters SET updated_at = now() WHERE matter_id = %s", (matter_id,))
        log.info(
            "batch %s committed: %s",
            batch_seq,
            dict(stats),
            extra={"matter_id": matter_id, "batch_seq": batch_seq},
        )
        return {
            "documents": len(docs),
            "failed": failed,
            "complied": complied,
            "rules": dict(stats),
            "chunks": 0,
        }


__all__ = [
    "apply_fact",
    "reconcile_batch",
    "reconcile_document",
    "recompute_outstanding",
    "ChangeType",
    "LinkType",
]
