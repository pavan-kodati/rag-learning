"""Document types -> authority classes (blueprint §7.3) and rule-based classification."""

from __future__ import annotations

import re

from .types import Authority, DocType

AUTHORITY_OF: dict[DocType, Authority] = {
    DocType.CONTRACT: Authority.BILATERAL,
    DocType.SOW: Authority.BILATERAL,
    DocType.PURCHASE_ORDER: Authority.BILATERAL,
    DocType.AMENDMENT: Authority.BILATERAL,
    DocType.CHANGE_REQUEST: Authority.BILATERAL,
    DocType.SIGNED_MINUTES: Authority.BILATERAL,
    DocType.ORDER: Authority.COURT,
    DocType.PLAINT: Authority.PLEADING,
    DocType.WRITTEN_STATEMENT: Authority.PLEADING,
    DocType.REPLICATION: Authority.PLEADING,
    DocType.REJOINDER: Authority.PLEADING,
    DocType.COUNTERCLAIM: Authority.PLEADING,
    DocType.AMENDED_PLEADING: Authority.PLEADING,
    DocType.AFFIDAVIT: Authority.SWORN,
    DocType.APPLICATION: Authority.SWORN,
    DocType.LEGAL_NOTICE: Authority.NOTICE,
    DocType.REPLY_NOTICE: Authority.NOTICE,
    DocType.INVOICE: Authority.RECORD,
    DocType.PAYMENT_RECORD: Authority.RECORD,
    DocType.BANK_STATEMENT: Authority.RECORD,
    DocType.RECEIPT: Authority.RECORD,
    DocType.COURIER_PROOF: Authority.RECORD,
    DocType.DELIVERY_NOTE: Authority.RECORD,
    DocType.EMAIL: Authority.CORRESPONDENCE,
    DocType.LETTER: Authority.CORRESPONDENCE,
    DocType.UNSIGNED_MINUTES: Authority.CORRESPONDENCE,
    DocType.HEARING_NOTE: Authority.INTERNAL,
}

CONTRACT_LIKE = {DocType.CONTRACT, DocType.SOW, DocType.PURCHASE_ORDER}
# document types that chunk paragraph-by-paragraph
PARAGRAPH_DOCS = {
    DocType.PLAINT, DocType.WRITTEN_STATEMENT, DocType.REPLICATION, DocType.REJOINDER, DocType.COUNTERCLAIM,
    DocType.AMENDED_PLEADING, DocType.AFFIDAVIT, DocType.APPLICATION, DocType.LEGAL_NOTICE, DocType.REPLY_NOTICE,
}  # fmt: skip
CLAUSE_DOCS = {
    DocType.CONTRACT, DocType.SOW, DocType.PURCHASE_ORDER, DocType.AMENDMENT, DocType.CHANGE_REQUEST,
    DocType.SIGNED_MINUTES,
}  # fmt: skip

# Pleading doc type that discharges a procedural step (used for compliance, blueprint §8.6)
STEP_FULFILLED_BY: dict[str, set[DocType]] = {
    "written_statement": {DocType.WRITTEN_STATEMENT},
    "replication": {DocType.REPLICATION},
    "rejoinder": {DocType.REJOINDER},
    "affidavit_of_evidence": {DocType.AFFIDAVIT},
}

# Title patterns, tested against the document's *title lines* only (the first few short lines that are not
# numbered clauses and do not end like a sentence). Body text such as "within 30 days of receipt" must never decide
# the type. Order = priority.
_TITLE_RULES: list[tuple[re.Pattern[str], DocType]] = [
    (re.compile(r"(?i)\b(amendment|addendum|variation)\b"), DocType.AMENDMENT),
    (re.compile(r"(?i)\bchange\s+request\b"), DocType.CHANGE_REQUEST),
    (re.compile(r"(?i)\bamended\s+(plaint|written\s+statement)\b"), DocType.AMENDED_PLEADING),
    (re.compile(r"(?i)\bwritten\s+statement\b"), DocType.WRITTEN_STATEMENT),
    (re.compile(r"(?i)\breplication\b"), DocType.REPLICATION),
    (re.compile(r"(?i)\brejoinder\b"), DocType.REJOINDER),
    (re.compile(r"(?i)\bcounter[\s-]?claim\b"), DocType.COUNTERCLAIM),
    (re.compile(r"(?i)\b(plaint|suit\s+for)\b"), DocType.PLAINT),
    (re.compile(r"(?i)\baffidavit\b"), DocType.AFFIDAVIT),
    (re.compile(r"(?i)\b(application\s+(?:under|for)|i\.?a\.?\s*no)\b"), DocType.APPLICATION),
    (
        re.compile(r"(?i)\b(reply\s+to\s+(?:the\s+)?(?:legal\s+)?notice|reply\s+notice)\b"),
        DocType.REPLY_NOTICE,
    ),
    (
        re.compile(
            r"(?i)\b(legal\s+notice|notice\s+of\s+(?:termination|breach|default|demand)|cure\s+notice|demand\s+notice)\b"
        ),
        DocType.LEGAL_NOTICE,
    ),
    (
        re.compile(
            r"(?i)^(?:interim\s+|ex[\s-]?parte\s+|final\s+)?order(?:\s+sheet)?(?:\s+(?:dated|passed).*)?$|\b(record\s+of\s+proceedings|proceedings\s+of\s+the\s+day)\b"
        ),
        DocType.ORDER,
    ),
    (re.compile(r"(?i)\b(tax\s+invoice|invoice\s+no\.?|invoice\s+number)\b|^invoice\b"), DocType.INVOICE),
    (
        re.compile(r"(?i)\b(bank\s+statement|statement\s+of\s+account|account\s+statement)\b"),
        DocType.BANK_STATEMENT,
    ),
    (
        re.compile(r"(?i)\b(payment\s+(?:advice|receipt|record|voucher)|remittance\s+advice)\b"),
        DocType.PAYMENT_RECORD,
    ),
    (re.compile(r"(?i)^(?:official\s+)?receipt\b"), DocType.RECEIPT),
    (
        re.compile(r"(?i)\b(courier|postal|speed\s+post)\b.{0,40}\b(receipt|proof|tracking|delivery)\b"),
        DocType.COURIER_PROOF,
    ),
    (re.compile(r"(?i)\bdelivery\s+(?:note|challan)\b"), DocType.DELIVERY_NOTE),
    (re.compile(r"(?i)\bpurchase\s+order\b"), DocType.PURCHASE_ORDER),
    (re.compile(r"(?i)\bstatement\s+of\s+work\b"), DocType.SOW),
    (re.compile(r"(?i)\b(minutes\s+of\s+(?:the\s+)?meeting|meeting\s+minutes)\b"), DocType.UNSIGNED_MINUTES),
    (
        re.compile(r"(?i)\b(hearing\s+note|note\s+of\s+hearing|notes?\s+for\s+hearing)\b"),
        DocType.HEARING_NOTE,
    ),
    (re.compile(r"(?i)\b(master\s+services?\s+agreement|agreement|contract|deed)\b"), DocType.CONTRACT),
]
_EMAIL_HEADER = re.compile(r"(?im)^\s*(from|subject)\s*:")


_SENTENCE_START = re.compile(
    r"(?i)^(this|these|the said|i |we |under instructions|whereas|it is|please|dear|with reference)\b"
)
_SENTENCE_BODY = re.compile(
    r"(?i)\b(is|are|was|were|has|have|shall|will)\s+(made|entered|between|hereby|agreed|executed)\b"
)


def _is_title_like(s: str) -> bool:
    return (
        len(s) <= 110
        and len(s.split()) <= 14
        and not re.match(r"^\d+[.)]\s", s)
        and not s.endswith(".")
        and not _SENTENCE_START.match(s)
        and not _SENTENCE_BODY.search(s)
    )


def _title_lines(text: str, n: int = 6) -> list[str]:
    first: list[str] = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if s:
            first.append(s)
        if len(first) >= n:
            break
    return [s for s in first if _is_title_like(s)]


def rule_classify(text: str) -> set[DocType]:
    """Doc types whose title rules fire on the document's title lines (plus e-mail headers)."""
    hits: set[DocType] = set()
    for line in _title_lines(text):
        for pat, dt in _TITLE_RULES:
            if pat.search(line):
                hits.add(dt)
    if _EMAIL_HEADER.search((text or "")[:300]):
        hits.add(DocType.EMAIL)
    if DocType.AMENDED_PLEADING in hits:  # "AMENDED WRITTEN STATEMENT" also contains the plain pleading words
        hits -= {DocType.PLAINT, DocType.WRITTEN_STATEMENT}
    if len(hits) > 1:
        hits.discard(DocType.CONTRACT)  # a specific title beats the generic "agreement" rule
        if DocType.EMAIL in hits and len(hits) > 1:
            hits.discard(DocType.EMAIL)
    return hits


_SIGN_RE = re.compile(
    r"(?i)(signed\s+by|executed\s+by|for\s+and\s+on\s+behalf\s+of|authori[sz]ed\s+signatory|/s/|\(sd\.?\)|witness)"
)


def looks_signed_by_all(text: str) -> bool:
    """Heuristic: two or more signature blocks on the document."""
    return len(_SIGN_RE.findall(text or "")) >= 2


def authority_for(doc_type: DocType, confidence: float, min_confidence: float) -> tuple[Authority, bool]:
    """Authority class and whether the document needs review. Low confidence -> CORRESPONDENCE (blueprint §7.3)."""
    if confidence < min_confidence:
        return Authority.CORRESPONDENCE, True
    return AUTHORITY_OF[doc_type], False
