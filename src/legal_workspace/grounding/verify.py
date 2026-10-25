"""Citation verification in code (blueprint §10): deterministic, fast, logged for every answer.

A sentence survives only if: (a) every cited id was in the retrieved set; (b) its quote is found on the cited page;
(c) every number and date in the sentence appears in the cited evidence; (d) it is not built only from superseded facts
(except in change and chronology views). Legal authorities must exist in the loaded corpus.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from ..domain.normalise import amounts_in, find_dates

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").translate(_QUOTES).lower().split())


def quote_on_page(quote: str, page_text: str, threshold: int = 90) -> bool:
    q, t = norm(quote), norm(page_text)
    if len(q) < 4 or not t:
        return False
    return q in t or fuzz.partial_ratio(q, t) >= threshold


def numeric_tokens(text: str) -> set[str]:
    """Canonical numbers and dates in `text`: amounts as plain decimals ('1840000'), dates as ISO ('2024-07-31')."""
    toks: set[str] = set()
    for a in amounts_in(text or ""):
        s = format(a.normalize(), "f")
        toks.add(s.rstrip("0").rstrip(".") if "." in s else s)
    for d, _ in find_dates(text or ""):
        toks.add(d.isoformat())
    return toks


@dataclass
class Evidence:
    """One citable item shown to the model (a chunk or a fact)."""

    id: str
    kind: str  # chunk | fact
    text: str  # the span the model saw
    page_text: str  # full text of the cited page (for the quote check)
    document_id: str | None = None
    document_title: str = ""
    page: int | None = None
    structural_ref: str | None = None
    chunk_id: str | None = None
    state: str = "CURRENT"  # CURRENT | DISPUTED | SUPERSEDED | EVIDENCE
    extra_text: str = ""  # additional text whose numbers may be used (fact value, sourced facts)

    def pool(self) -> str:
        return f"{self.text}\n{self.extra_text}\n{self.document_title} {self.structural_ref or ''} {self.page or ''}"


@dataclass
class SentenceCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def verify_sentence(
    text: str, cited_ids: list[str], quote: str, evidence: dict[str, Evidence], *, allow_superseded: bool = False, threshold: int = 90,
) -> SentenceCheck:  # fmt: skip
    reasons: list[str] = []
    if not cited_ids:
        return SentenceCheck(False, ["no evidence cited"])
    unknown = [i for i in cited_ids if i not in evidence]
    if unknown:
        return SentenceCheck(False, [f"cites evidence that was not retrieved: {unknown}"])
    cited = [evidence[i] for i in cited_ids]
    if not any(
        quote_on_page(quote, e.page_text, threshold) or quote_on_page(quote, e.text, threshold) for e in cited
    ):
        reasons.append("quote not found on the cited page")
    pool = " ".join(e.pool() for e in cited)
    missing = numeric_tokens(text) - numeric_tokens(pool) - {"0"}
    # plain small integers (list numbering, clause numbers) are tolerated only if they appear in the pool as text
    missing = {m for m in missing if not re.search(rf"(?<!\d){re.escape(m)}(?!\d)", pool)}
    if missing:
        reasons.append(f"numbers or dates not found in the cited evidence: {sorted(missing)}")
    if not allow_superseded and all(e.state == "SUPERSEDED" for e in cited):
        reasons.append("relies only on superseded facts")
    return SentenceCheck(not reasons, reasons)


def verify_statement_citation(
    page_texts: dict[tuple[str, int], str],
    doc_id: str | None,
    page: int | None,
    quote: str | None,
    threshold: int = 90,
) -> SentenceCheck:
    """Structured plans: the stored quote must still be on the stored page (belt and braces over the extraction-time check)."""
    if doc_id is None or page is None:
        return SentenceCheck(False, ["citation has no document or page"])
    text = page_texts.get((doc_id, page))
    if text is None:
        return SentenceCheck(False, ["cited page does not exist"])
    if quote is None:  # document-level events: the page must exist
        return SentenceCheck(True)
    return (
        SentenceCheck(True)
        if quote_on_page(quote, text, threshold)
        else SentenceCheck(False, ["quote not found on the cited page"])
    )


def verify_law_citation(passage_id: str | None, known: dict[str, Any]) -> SentenceCheck:
    """Legal authorities are never quoted from model memory: they must match a row in the corpus."""
    if passage_id and passage_id in known:
        return SentenceCheck(True)
    return SentenceCheck(False, ["authority is not in the legal corpus"])
