"""Turn validated extraction items into NewFacts: resolve subjects, build keys, compute deadlines, write readable text.

Runs at reconcile time (not extraction time) so the contract / notice registries are complete for the whole batch.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from ..domain.authority import AUTHORITY_OF
from ..domain.deadlines import DueResult, compute_due
from ..domain.keys import build_key
from ..domain.normalise import fmt_date, format_inr, normalise_name, parse_date, slugify
from ..domain.slots import (
    ALLEGATION_TOPICS,
    CLAIM_HEADS,
    PROCEDURAL_STEPS,
    RELIEF_TYPES,
    SUBJECT_SLOTS,
    category_for,
)
from ..domain.subjects import (
    ContractRef,
    NoticeRef,
    party_slug,
    resolve_contract,
    resolve_invoice,
    resolve_milestone,
    resolve_notice,
    resolve_payment,
)
from ..domain.types import Authority, DocType, FactValue, NewFact, PartyRole

_PARTY_ATTRIBUTED = {
    Authority.PLEADING,
    Authority.SWORN,
    Authority.NOTICE,
    Authority.CORRESPONDENCE,
    Authority.INTERNAL,
}

_SYNONYMS: dict[str, dict[str, str]] = {
    "ALLEGATION": {
        "late": "delay",
        "delayed": "delay",
        "delivery": "delay",
        "nonpayment": "non_payment",
        "non-payment": "non_payment",
        "unpaid": "non_payment",
        "payment": "non_payment",
        "defect": "defective_work",
        "defective": "defective_work",
        "quality": "defective_work",
        "termination": "wrongful_termination",
        "exclusivity": "breach_of_exclusivity",
    },
    "CLAIM": {
        "outstanding": "principal",
        "price": "principal",
        "compensation": "damages",
        "cost": "costs",
        "pendente": "interest",
    },
    "RELIEF": {
        "decree": "recovery",
        "money": "recovery",
        "payment": "recovery",
        "restrain": "injunction",
        "injunctive": "injunction",
        "performance": "specific_performance",
        "cost": "costs",
    },
    "DIRECTION": {
        "wsf": "written_statement",
        "statement": "written_statement",
        "evidence": "affidavit_of_evidence",
        "witnesses": "list_of_witnesses",
        "witness": "list_of_witnesses",
        "admission": "admission_denial_of_documents",
        "denial": "admission_denial_of_documents",
        "documents": "admission_denial_of_documents",
        "listing": "next_hearing",
        "hearing": "next_hearing",
        "interim": "interim_relief",
        "compliance": "compliance_report",
        "report": "compliance_report",
        "inspect": "inspection",
    },
}
_ENUMS = {
    "CLAIM": CLAIM_HEADS,
    "RELIEF": RELIEF_TYPES,
    "ALLEGATION": ALLEGATION_TOPICS,
    "DIRECTION": PROCEDURAL_STEPS,
}


def match_enum(subject_type: str, ref: str) -> str:
    """Map free text to one of the fixed subject references; 'other' when nothing fits."""
    options = _ENUMS[subject_type]
    slug = slugify(ref).replace("-", "_")
    if slug in options:
        return slug
    for opt in options:
        if opt != "other" and (opt in slug or slug in opt and len(slug) > 3):
            return opt
    for word in re.split(r"[^a-z]+", ref.lower()):
        syn = _SYNONYMS.get(subject_type, {}).get(word)
        if syn:
            return syn
    return "other"


@dataclass
class DirectionInfo:
    step: str
    kind: str
    due: DueResult | None = None
    responsible_text: str = ""


@dataclass
class ResolvedFact:
    fact: NewFact
    subject_ref: str
    raw: dict[str, Any]
    chunk_id: str | None = None
    direction: DirectionInfo | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class ResolveContext:
    """Everything resolution needs; assembled from the database by the reconciler (and by tests directly)."""

    doc: dict[str, Any]
    registry: list[ContractRef]
    notices: list[NoticeRef]
    resolve_party: Any  # Callable[[str], dict | None]
    author: dict[str, Any] | None
    children: list[dict[str, Any]]  # chunk rows of the document
    own_notice: NoticeRef | None = None


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def find_chunk(children: list[dict[str, Any]], quote: str, page: int) -> str | None:
    q = _norm_ws(quote)
    for c in children:
        if c["page_start"] <= page <= c["page_end"] and q and q in _norm_ws(c["chunk_text"]):
            return str(c["chunk_id"])
    for c in children:
        if q and q in _norm_ws(c["chunk_text"]):
            return str(c["chunk_id"])
    return None


def _title(s: str) -> str:
    return s.replace("_", " ").replace("-", " ").strip().capitalize()


def subject_label(st: str, ref: str, notices: list[NoticeRef] | None = None) -> str:
    if st in ("CONTRACT", "MILESTONE", "INVOICE"):
        return ref.upper()
    if st == "PAYMENT":
        return f"payment {ref}"
    if st == "NOTICE":
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", ref)
        if m:
            d = date.fromisoformat(m.group(1))
            return f"notice of {fmt_date(d)} from {m.group(2).capitalize()}"
        return f"notice {ref}"
    if st == "HEARING":
        try:
            return f"hearing of {fmt_date(date.fromisoformat(ref))}"
        except ValueError:
            return f"hearing {ref}"
    return _title(ref)


def display_value(st: str, slot: str, v: FactValue) -> str:
    if v.amount is not None:
        return "₹" + format_inr(v.amount)
    if v.date is not None:
        return fmt_date(v.date)
    if v.boolean is not None:
        if st == "ALLEGATION":
            return (
                {"asserted": "alleged", "denied": "denied", "admitted": "admitted"}.get(slot, "yes")
                if v.boolean
                else f"not {slot}"
            )
        if slot == "received":
            return "received / served" if v.boolean else "not received"
        return "yes" if v.boolean else "no"
    return v.text


def assertion_text(st: str, ref: str, slot: str, v: FactValue, direction: DirectionInfo | None = None) -> str:
    label = subject_label(st, ref)
    if st == "ALLEGATION":
        return (
            f"{_title(ref)}: {display_value(st, slot, v)}" if slot != "other" else f"{_title(ref)}: {v.text}"
        )
    if st == "DIRECTION" and slot == "due_date":
        step = _title(ref)
        if v.date is not None:
            how = (
                f" ({direction.due.period.text})"
                if direction and direction.due and direction.due.period.text
                else ""
            )
            return f"{step} due {fmt_date(v.date)}{how}"
        return f"{step}: {v.text or 'no period specified'}"
    if st == "DIRECTION":
        return f"{_title(ref)}: {slot.replace('_', ' ')} {v.text}"
    if st == "HEARING" and slot == "next_date":
        return f"Next hearing listed on {display_value(st, slot, v)}"
    if st == "CLAIM":
        return f"Claim for {_title(ref)}: {slot.replace('_', ' ')} {display_value(st, slot, v)}"
    if st == "RELIEF":
        return f"Relief sought: {_title(ref)} ({slot.replace('_', ' ')} {display_value(st, slot, v)})"
    sd = SUBJECT_SLOTS[st].get(slot)
    return f"{sd.label if sd else slot} ({label}): {display_value(st, slot, v)}"


def _fact_value(item: dict[str, Any]) -> FactValue:
    amount = Decimal(item["value_amount"]) if item.get("value_amount") else None
    d = date.fromisoformat(item["value_date"]) if item.get("value_date") else None
    return FactValue(
        text=item.get("value_text", ""),
        date=d,
        amount=amount,
        boolean=item.get("value_bool"),
        number=item.get("value_number"),
    )


def resolve_items(items: list[dict[str, Any]], ctx: ResolveContext) -> list[ResolvedFact]:
    doc = ctx.doc
    doc_type = DocType(doc["document_type"])
    authority = Authority(doc["authority_class"] or AUTHORITY_OF[doc_type])
    doc_date: date | None = doc["document_date"]
    default_contract = doc.get("contract_id")
    if doc_type in (
        DocType.AMENDMENT,
        DocType.CHANGE_REQUEST,
        DocType.SIGNED_MINUTES,
        DocType.UNSIGNED_MINUTES,
    ):
        r = resolve_contract(doc["amends_ref"], ctx.registry, None) if doc.get("amends_ref") else None
        default_contract = r.ref if (r and r.ok) else None
    author_id = str(ctx.author["party_id"]) if ctx.author and authority in _PARTY_ATTRIBUTED else None
    author_role = PartyRole(ctx.author["role"]) if author_id and ctx.author else None

    out: list[ResolvedFact] = []
    for it in items:
        st = it["subject_type"]
        slot = it["slot"]
        raw_ref = it.get("subject_ref", "")
        flags = list(it.get("flags", []))
        review: str | None = None
        ref: str | None = None
        direction: DirectionInfo | None = None

        if st == "CONTRACT":
            res = resolve_contract(raw_ref, ctx.registry, default_contract)
            ref, review = res.ref, (None if res.ok else res.reason)
        elif st == "MILESTONE":
            res = resolve_milestone(raw_ref, ctx.registry, default_contract)
            ref, review = res.ref, (None if res.ok else res.reason)
        elif st == "INVOICE":
            res = resolve_invoice(raw_ref)
            ref, review = res.ref, (None if res.ok else res.reason)
        elif st == "PAYMENT":
            hint = date.fromisoformat(it["value_date"]) if slot == "date" and it.get("value_date") else None
            hint = parse_date(it.get("subject_date")) or hint
            res = resolve_payment(raw_ref, hint)
            ref, review = res.ref, (None if res.ok else res.reason)
        elif st == "NOTICE":
            sender = ctx.resolve_party(it.get("subject_party", "")) if it.get("subject_party") else None
            pslug = party_slug(sender["canonical_name"]) if sender else None
            res = resolve_notice(
                raw_ref, parse_date(it.get("subject_date")), pslug, ctx.notices, ctx.own_notice
            )
            ref, review = res.ref, (None if res.ok else res.reason)
        elif st in _ENUMS:
            ref = match_enum(st, raw_ref or slot)
            if st == "DIRECTION":
                kind = it.get("direction_kind") or ("NEXT_HEARING" if ref == "next_hearing" else "DIRECTION")
                direction = DirectionInfo(ref, kind)
        elif st == "HEARING":
            ref = doc_date.isoformat() if doc_date else None
            if not ref:
                review = "hearing without a document date"
        if ref is None:
            ref = "unresolved-" + (slugify(raw_ref)[:30] or "x")

        value = _fact_value(it)
        if st == "PAYMENT" and slot == "against_invoice":
            inv = resolve_invoice(value.text)
            value = FactValue(text=inv.ref or value.text)
        if st == "DIRECTION" and slot == "due_date":
            due = compute_due(value.text, doc_date)
            assert direction is not None
            direction.due = due
            value = FactValue(
                text=due.due_date.isoformat() if due.due_date else (value.text or "unspecified"),
                date=due.due_date,
            )
            if due.needs_review:
                review = (review + "; " if review else "") + due.reason
        if st == "DIRECTION" and slot == "responsible_party":
            p = ctx.resolve_party(value.text)
            if direction is not None:
                direction.responsible_text = p["canonical_name"] if p else value.text
            value = FactValue(text=p["canonical_name"] if p else value.text)
        if st == "DIRECTION" and slot not in ("due_date", "responsible_party") and direction is None:
            direction = DirectionInfo(ref, "DIRECTION")

        if slot == "other":
            digest = hashlib.sha1(normalise_name(value.text).encode()).hexdigest()[:6]  # noqa: S324 - not security relevant
            key = build_key(st, ref, "other") + "-" + digest
        else:
            key = build_key(st, ref, slot)

        nf = NewFact(
            fact_key=key, slot=slot, value=value, party_id=author_id, party_role=author_role, authority=authority,
            doc_type=doc_type, doc_date=doc_date, signed_by_all=bool(doc["signed_by_all_parties"]), document_id=str(doc["document_id"]),
            page=int(it["page"]), quote=it["quote"], assertion_text=assertion_text(st, ref, slot, value, direction),
            category=("UNDERTAKING" if direction and direction.kind == "UNDERTAKING" else category_for(authority, doc_type, st, slot, author_role)),
            subject_type=st, effective_from=doc_date if authority == Authority.BILATERAL else None,
            needs_review=bool(review or flags), review_reason="; ".join(x for x in [review, *flags] if x) or None,
        )  # fmt: skip
        out.append(
            ResolvedFact(
                nf, ref, it, find_chunk(ctx.children, it["quote"], int(it["page"])), direction, flags
            )
        )
    return out
