"""Shared types for retrieval plans and answers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Intent(StrEnum):
    GIST = "GIST"
    CHRONOLOGY = "CHRONOLOGY"
    CLAIMS = "CLAIMS"
    EVIDENCE = "EVIDENCE"
    DIRECTIONS = "DIRECTIONS"
    WHAT_CHANGED = "WHAT_CHANGED"
    LEGAL_RESEARCH = "LEGAL_RESEARCH"
    FACTUAL_QA = "FACTUAL_QA"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass
class Citation:
    document_id: str | None
    document_title: str
    page: int | None
    quote: str | None = None
    structural_ref: str | None = None
    chunk_id: str | None = None
    source_kind: str = "matter"  # matter | law
    source_id: str | None = None  # legal_corpus source / passage id for law citations

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Statement:
    id: str
    text: str
    citations: list[Citation] = field(default_factory=list)
    state: str = "CURRENT"  # CURRENT | DISPUTED | SUPERSEDED | EVIDENCE | INFO
    kind: str = "fact"
    fact_id: str | None = None
    superseded_by: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["citations"] = [c.to_dict() for c in self.citations]
        return d


@dataclass
class PlanResult:
    plan: str
    title: str
    statements: list[Statement] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Hit:
    chunk_id: str
    parent_chunk_id: str | None
    document_id: str
    document_title: str
    document_type: str | None
    document_date: Any
    page_start: int
    page_end: int
    structural_ref: str | None
    text: str
    parent_text: str
    rrf: float
    rerank: float | None = None
    facts: list[dict[str, Any]] = field(
        default_factory=list
    )  # facts sourced from this chunk, with their state

    def to_trace(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "document": self.document_title, "page": self.page_start, "ref": self.structural_ref,
                "rrf": round(self.rrf, 5), "rerank": None if self.rerank is None else round(self.rerank, 4)}  # fmt: skip
