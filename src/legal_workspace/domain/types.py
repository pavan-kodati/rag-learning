"""Core domain vocabulary shared by every layer (blueprint §7.3, §8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Authority(StrEnum):
    BILATERAL = "BILATERAL"
    COURT = "COURT"
    PLEADING = "PLEADING"
    SWORN = "SWORN"
    NOTICE = "NOTICE"
    RECORD = "RECORD"
    CORRESPONDENCE = "CORRESPONDENCE"
    INTERNAL = "INTERNAL"


class DocType(StrEnum):
    CONTRACT = "CONTRACT"
    SOW = "SOW"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    AMENDMENT = "AMENDMENT"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    SIGNED_MINUTES = "SIGNED_MINUTES"
    ORDER = "ORDER"
    PLAINT = "PLAINT"
    WRITTEN_STATEMENT = "WRITTEN_STATEMENT"
    REPLICATION = "REPLICATION"
    REJOINDER = "REJOINDER"
    COUNTERCLAIM = "COUNTERCLAIM"
    AMENDED_PLEADING = "AMENDED_PLEADING"
    AFFIDAVIT = "AFFIDAVIT"
    APPLICATION = "APPLICATION"
    LEGAL_NOTICE = "LEGAL_NOTICE"
    REPLY_NOTICE = "REPLY_NOTICE"
    INVOICE = "INVOICE"
    PAYMENT_RECORD = "PAYMENT_RECORD"
    BANK_STATEMENT = "BANK_STATEMENT"
    RECEIPT = "RECEIPT"
    COURIER_PROOF = "COURIER_PROOF"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    EMAIL = "EMAIL"
    LETTER = "LETTER"
    UNSIGNED_MINUTES = "UNSIGNED_MINUTES"
    HEARING_NOTE = "HEARING_NOTE"


class FactState(StrEnum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ChangeType(StrEnum):
    NEW = "NEW"
    SUPERSEDED = "SUPERSEDED"
    NARROWED = "NARROWED"
    DISPUTED = "DISPUTED"
    CONTRADICTED_BY_EVIDENCE = "CONTRADICTED_BY_EVIDENCE"
    CORROBORATED = "CORROBORATED"
    WITHDRAWN = "WITHDRAWN"
    COMPLIED = "COMPLIED"


class LinkType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"


class PartyRole(StrEnum):
    PLAINTIFF = "PLAINTIFF"
    DEFENDANT = "DEFENDANT"
    PETITIONER = "PETITIONER"
    RESPONDENT = "RESPONDENT"
    OTHER = "OTHER"


class VType(StrEnum):
    DATE = "date"
    AMOUNT = "amount"
    BOOL = "bool"
    DAYS = "days"  # number of days (int)
    TEXT = "text"
    PERIOD = "period"  # "within four weeks" -> days / months (directions)
    DATE_OR_PERIOD = "date_or_period"


SIDE_A = {PartyRole.PLAINTIFF, PartyRole.PETITIONER}
SIDE_B = {PartyRole.DEFENDANT, PartyRole.RESPONDENT}


def opposing(a: PartyRole | None, b: PartyRole | None) -> bool:
    """True when two roles are known to be on opposite sides of the dispute."""
    if a is None or b is None:
        return False
    return (a in SIDE_A and b in SIDE_B) or (a in SIDE_B and b in SIDE_A)


@dataclass(frozen=True)
class FactValue:
    """A normalised value. Exactly one typed field is normally set; `text` is always a readable form."""

    text: str
    date: date | None = None
    amount: Decimal | None = None
    boolean: bool | None = None
    number: int | None = None

    def comparable(self) -> tuple[str, object]:
        """Canonical form used for equality: typed value wins over text."""
        if self.amount is not None:
            return ("amount", self.amount)
        if self.date is not None:
            return ("date", self.date)
        if self.boolean is not None:
            return ("bool", self.boolean)
        if self.number is not None:
            return ("number", self.number)
        return ("text", " ".join(self.text.lower().split()))

    def same_as(self, other: FactValue) -> bool:
        return self.comparable() == other.comparable()


@dataclass
class NewFact:
    """A fact extracted from a document, normalised, awaiting reconciliation."""

    fact_key: str
    slot: str
    value: FactValue
    party_id: str | None  # asserting party (None for bilateral documents and orders)
    party_role: PartyRole | None
    authority: Authority
    doc_type: DocType
    doc_date: date | None
    signed_by_all: bool
    document_id: str
    page: int
    quote: str
    assertion_text: str
    category: str
    subject_type: str = ""
    effective_from: date | None = None
    needs_review: bool = False
    review_reason: str | None = None
    derived: bool = False


@dataclass
class CurrentFact:
    """A fact already in case memory with the same key (ended_in_batch_seq IS NULL)."""

    assertion_id: str
    fact_key: str
    slot: str
    value: FactValue
    party_id: str | None
    party_role: PartyRole | None
    authority: Authority
    doc_type: DocType
    doc_date: date | None
    state: FactState = FactState.ACTIVE
    evidence_only: bool = False
    subject_type: str = ""


class Action(StrEnum):
    END = "END"  # end the old fact (SUPERSEDED)
    MARK_DISPUTED = "MARK_DISPUTED"
    MARK_EVIDENCE_ONLY = "MARK_EVIDENCE_ONLY"
    KEEP = "KEEP"


@dataclass
class TargetEffect:
    """What happens to one existing fact when the new fact arrives."""

    assertion_id: str
    action: Action
    link: LinkType | None
    change_type: ChangeType
    rule_id: str
    reason: str
    # Link orientation. SUPPORTS/CONTRACTS: claim -> evidence; SUPERSEDES: newer -> older.
    # Default (False): assertion = new fact, target = existing fact. True: assertion = existing, target = new.
    reverse: bool = False


@dataclass
class Decision:
    """Outcome of reconciling one new fact (blueprint §8.3)."""

    rule_id: str
    change_type: ChangeType
    new_state: FactState
    new_evidence_only: bool
    effects: list[TargetEffect] = field(default_factory=list)
    needs_review: bool = False
    review_reason: str | None = None
    reason: str = ""
