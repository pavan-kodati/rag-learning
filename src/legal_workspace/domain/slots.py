"""Subject types, slots and their value types (blueprint §8.2).

The model fills *slots*; code builds the fact key. The slot list is generic: it is derived from the three
matter archetypes, not from any sample document (constraint C2).
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Authority, DocType, PartyRole, VType


@dataclass(frozen=True)
class SlotDef:
    name: str
    vtype: VType
    label: str
    hint: str = ""


def _s(name: str, vtype: VType, label: str, hint: str = "") -> SlotDef:
    return SlotDef(name, vtype, label, hint)


SUBJECT_SLOTS: dict[str, dict[str, SlotDef]] = {
    "CONTRACT": {
        s.name: s
        for s in [
            _s("effective_date", VType.DATE, "Effective date"),
            _s("contract_value", VType.AMOUNT, "Contract value"),
            _s("scope", VType.TEXT, "Scope"),
            _s(
                "delivery_date",
                VType.DATE,
                "Delivery / completion date",
                "the date deliverables or go-live are due",
            ),
            _s("payment_terms_days", VType.DAYS, "Payment terms (days)", "days allowed to pay an invoice"),
            _s("ld_rate", VType.TEXT, "Liquidated damages rate", "e.g. 0.5% per week of delay"),
            _s("ld_cap", VType.TEXT, "Liquidated damages cap"),
            _s("termination_notice_days", VType.DAYS, "Termination notice (days)"),
            _s("cure_period_days", VType.DAYS, "Cure period (days)"),
            _s("termination_for_convenience", VType.BOOL, "Termination for convenience allowed"),
            _s("arbitration_clause", VType.BOOL, "Arbitration clause present"),
            _s("governing_law", VType.TEXT, "Governing law"),
            _s("jurisdiction", VType.TEXT, "Jurisdiction / seat"),
            _s("liability_cap", VType.TEXT, "Liability cap"),
            _s("other", VType.TEXT, "Other term"),
        ]
    },
    "MILESTONE": {
        s.name: s
        for s in [
            _s("due_date", VType.DATE, "Milestone due date"),
            _s("amount", VType.AMOUNT, "Milestone amount"),
            _s("completion_status", VType.TEXT, "Completion status"),
            _s("acceptance_date", VType.DATE, "Acceptance date"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "INVOICE": {
        s.name: s
        for s in [
            _s("invoice_amount", VType.AMOUNT, "Invoice amount"),
            _s("invoice_date", VType.DATE, "Invoice date"),
            _s("due_date", VType.DATE, "Invoice due date"),
            _s("amount_paid", VType.AMOUNT, "Amount paid"),
            _s("amount_outstanding", VType.AMOUNT, "Amount outstanding"),
            _s("deduction", VType.AMOUNT, "Deduction"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "PAYMENT": {
        s.name: s
        for s in [
            _s("amount", VType.AMOUNT, "Payment amount"),
            _s("date", VType.DATE, "Payment date"),
            _s(
                "against_invoice",
                VType.TEXT,
                "Paid against invoice",
                "the invoice number the payment relates to",
            ),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "NOTICE": {
        s.name: s
        for s in [
            _s("sent_date", VType.DATE, "Date sent"),
            _s("mode_of_service", VType.TEXT, "Mode of service"),
            _s(
                "received",
                VType.BOOL,
                "Notice received / served",
                "true if received or served, false if denied",
            ),
            _s("received_date", VType.DATE, "Date received"),
            _s("demand_amount", VType.AMOUNT, "Amount demanded"),
            _s("cure_demanded", VType.TEXT, "Cure demanded"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "CLAIM": {
        s.name: s
        for s in [
            _s("amount", VType.AMOUNT, "Claim amount"),
            _s("interest_rate", VType.TEXT, "Interest rate"),
            _s("basis", VType.TEXT, "Basis of claim"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "RELIEF": {
        s.name: s
        for s in [
            _s("sought", VType.BOOL, "Relief sought"),
            _s("amount", VType.AMOUNT, "Relief amount"),
            _s("status", VType.TEXT, "Relief status"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "ALLEGATION": {
        s.name: s
        for s in [
            _s("asserted", VType.BOOL, "Alleged / asserted"),
            _s("admitted", VType.BOOL, "Admitted"),
            _s("denied", VType.BOOL, "Denied"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "DIRECTION": {
        s.name: s
        for s in [
            _s(
                "due_date",
                VType.DATE_OR_PERIOD,
                "Due",
                "copy the period or date exactly as written, e.g. 'within four weeks'",
            ),
            _s("responsible_party", VType.TEXT, "Responsible party"),
            _s("compliance", VType.TEXT, "Compliance"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
    "HEARING": {
        s.name: s
        for s in [
            _s("next_date", VType.DATE, "Next hearing date"),
            _s("purpose", VType.TEXT, "Purpose of hearing"),
            _s("outcome", VType.TEXT, "Outcome"),
            _s("other", VType.TEXT, "Other"),
        ]
    },
}

SUBJECT_TYPES = tuple(SUBJECT_SLOTS)
ALL_SLOTS = tuple(sorted({s for slots in SUBJECT_SLOTS.values() for s in slots}))

CLAIM_HEADS = ("principal", "interest", "damages", "costs", "other")
RELIEF_TYPES = ("recovery", "damages", "injunction", "specific_performance", "declaration", "costs", "other")
ALLEGATION_TOPICS = (
    "delay", "defective_work", "non_payment", "wrongful_termination", "breach_of_exclusivity", "other",
)  # fmt: skip
PROCEDURAL_STEPS = (
    "written_statement", "replication", "rejoinder", "admission_denial_of_documents", "affidavit_of_evidence",
    "list_of_witnesses", "deposit", "mediation", "interim_relief", "compliance_report", "inspection",
    "next_hearing", "other",
)  # fmt: skip
DIRECTION_KINDS = ("DIRECTION", "UNDERTAKING", "INTERIM_RELIEF", "NEXT_HEARING")

_CONTRACTUAL = (
    DocType.CONTRACT, DocType.SOW, DocType.PURCHASE_ORDER, DocType.AMENDMENT, DocType.CHANGE_REQUEST,
    DocType.SIGNED_MINUTES,
)  # fmt: skip
_PLEADINGS = (
    DocType.PLAINT, DocType.WRITTEN_STATEMENT, DocType.REPLICATION, DocType.REJOINDER, DocType.COUNTERCLAIM,
    DocType.AMENDED_PLEADING, DocType.AFFIDAVIT, DocType.APPLICATION,
)  # fmt: skip

_PLEADING_SUBJECTS = (
    "CONTRACT",
    "MILESTONE",
    "INVOICE",
    "PAYMENT",
    "NOTICE",
    "CLAIM",
    "RELIEF",
    "ALLEGATION",
    "HEARING",
)

ALLOWED_SUBJECTS: dict[DocType, tuple[str, ...]] = {
    **dict.fromkeys(_CONTRACTUAL, ("CONTRACT", "MILESTONE")),
    **dict.fromkeys(_PLEADINGS, _PLEADING_SUBJECTS),
    DocType.ORDER: ("DIRECTION", "HEARING"),
    DocType.LEGAL_NOTICE: (
        "NOTICE",
        "CONTRACT",
        "MILESTONE",
        "INVOICE",
        "PAYMENT",
        "CLAIM",
        "RELIEF",
        "ALLEGATION",
    ),
    DocType.REPLY_NOTICE: ("NOTICE", "CONTRACT", "MILESTONE", "INVOICE", "PAYMENT", "CLAIM", "ALLEGATION"),
    DocType.INVOICE: ("INVOICE", "PAYMENT", "MILESTONE"),
    DocType.DELIVERY_NOTE: ("MILESTONE", "INVOICE"),
    DocType.RECEIPT: ("PAYMENT", "INVOICE"),
    DocType.PAYMENT_RECORD: ("PAYMENT", "INVOICE"),
    DocType.BANK_STATEMENT: ("PAYMENT", "INVOICE"),
    DocType.COURIER_PROOF: ("NOTICE",),
    DocType.EMAIL: ("CONTRACT", "MILESTONE", "INVOICE", "PAYMENT", "NOTICE", "ALLEGATION"),
    DocType.LETTER: ("CONTRACT", "MILESTONE", "INVOICE", "PAYMENT", "NOTICE", "ALLEGATION", "CLAIM"),
    DocType.UNSIGNED_MINUTES: ("CONTRACT", "MILESTONE", "INVOICE", "PAYMENT", "NOTICE", "ALLEGATION"),
    DocType.HEARING_NOTE: ("HEARING", "DIRECTION", "ALLEGATION"),
}


def allowed_subjects(doc_type: DocType) -> tuple[str, ...]:
    return ALLOWED_SUBJECTS.get(doc_type, ("CONTRACT", "INVOICE", "PAYMENT", "NOTICE", "ALLEGATION"))


def slot_def(subject_type: str, slot: str) -> SlotDef | None:
    return SUBJECT_SLOTS.get(subject_type.upper(), {}).get(slot.lower())


def category_for(
    authority: Authority, doc_type: DocType, subject_type: str, slot: str, role: PartyRole | None
) -> str:
    """Assertion category (blueprint §15 CHECK list), decided by code."""
    st = subject_type.upper()
    if st == "DIRECTION" or (st == "HEARING" and authority == Authority.COURT):
        return "DIRECTION"
    if st in ("CONTRACT", "MILESTONE") and authority == Authority.BILATERAL:
        return "TERM"
    if st == "PAYMENT":
        return "PAYMENT"
    if st == "CLAIM":
        return "COUNTERCLAIM" if doc_type == DocType.COUNTERCLAIM else "CLAIM"
    if st == "RELIEF":
        return "RELIEF_SOUGHT"
    if st == "ALLEGATION":
        if slot == "denied":
            return "DENIAL"
        if slot == "admitted":
            return "ADMISSION"
        if doc_type == DocType.COUNTERCLAIM:
            return "COUNTERCLAIM"
        if role in (PartyRole.DEFENDANT, PartyRole.RESPONDENT) and authority in (
            Authority.PLEADING,
            Authority.SWORN,
        ):
            return "DEFENCE"
        return "CLAIM"
    return "EVENT_FACT"
