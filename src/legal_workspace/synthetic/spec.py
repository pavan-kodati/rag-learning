"""A tiny DSL for synthetic matters: documents, gold extractions (what a perfect model would return), golden
questions and planted changes. Everything here is invented; no real party, court or case is described."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Item:
    """One gold extraction item. `quote` must be a verbatim passage of the document text."""

    subject_type: str
    subject_ref: str
    slot: str
    value: str
    quote: str
    subject_date: str = ""
    subject_party: str = ""
    direction_kind: str = ""


def I(  # noqa: N802, E743 - terse constructor keeps the matter files readable
    st: str, ref: str, slot: str, value: str, quote: str, *, date: str = "", party: str = "", kind: str = ""
) -> Item:
    return Item(st, ref, slot, value, quote, date, party, kind)


@dataclass
class Doc:
    file: str
    batch: int
    doc_type: str
    title: str
    date: str  # as written
    text: str
    author: str = ""  # party key (see Matter.parties) or ""
    signed: bool = False
    amends: str = ""
    items: list[Item] = field(default_factory=list)
    suit_roles: bool = (
        True  # use PLAINTIFF/DEFENDANT roles (False: pre-dispute documents name parties as OTHER)
    )
    terms: list[tuple[str, str]] = field(default_factory=list)  # (defined term, party key)
    scanned: bool = False  # render as an image-only PDF (OCR path)
    confidence: float = 0.95
    is_duplicate_of: str = ""  # upload the identical file again in this batch
    wrong_extension: str = ""
    no_fixture: bool = False  # held-out style document: no recorded model output (needs a real model)


@dataclass
class Party:
    key: str
    name: str
    role: str  # PLAINTIFF | DEFENDANT
    aliases: list[str] = field(default_factory=list)


@dataclass
class Question:
    id: str
    batch: int
    question: str
    expected_facts: list[str] = field(default_factory=list)  # "fact_key = value" (current position)
    expected_text: list[str] = field(default_factory=list)  # strings that must appear in the answer
    expected_citations: list[dict[str, Any]] = field(
        default_factory=list
    )  # {"document": substring, "page": n}
    must_not_say: list[str] = field(default_factory=list)
    intent: str = ""
    not_found: bool = False  # the right answer is "not found"


@dataclass
class Planted:
    """A change the system must detect in a given batch."""

    batch: int
    change_type: str
    rule_id: str
    fact_key: str


@dataclass
class Probe:
    """A labelled retrieval query: the chunk that should be found is on `page` of the document whose title contains `document`."""

    query: str
    document: str
    page: int = 1


@dataclass
class Matter:
    id: str
    number: str
    title: str
    matter_type: str
    forum: str
    parties: list[Party]
    docs: list[Doc]
    questions: list[Question] = field(default_factory=list)
    planted: list[Planted] = field(default_factory=list)
    description: str = ""
    authorities_expected: list[str] = field(default_factory=list)  # corpus source keys Plan 7 should surface
    probes: list[Probe] = field(default_factory=list)

    def batches(self) -> list[int]:
        return sorted({d.batch for d in self.docs})

    def party(self, key: str) -> Party:
        return next(p for p in self.parties if p.key == key)
