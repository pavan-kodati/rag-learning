"""Hybrid search (blueprint §9.3): dense vectors + PostgreSQL full-text, fused with Reciprocal Rank Fusion, then reranked."""

from __future__ import annotations

import logging
import re
from typing import Any

import psycopg
from pgvector import Vector

from legal_workspace.db.pool import Conn

from ..adapters.embed import Embedder
from ..adapters.rerank import Reranker
from .types import Hit

log = logging.getLogger(__name__)

_HYBRID_SQL = """
WITH q AS (
    SELECT (replace(plainto_tsquery('english', %(text)s)::text, '&', '|')::tsquery
         || replace(plainto_tsquery('simple',  %(text)s)::text, '&', '|')::tsquery) AS tsq
),
vector_matches AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY dense_embedding <=> %(vec)s) AS rank_vec
    FROM document_chunks
    WHERE matter_id = %(matter)s AND chunk_level = 'CHILD' AND batch_seq <= %(as_of)s
    ORDER BY dense_embedding <=> %(vec)s
    LIMIT %(limit)s
),
lexical_matches AS (
    SELECT c.chunk_id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC) AS rank_lex
    FROM document_chunks c, q
    WHERE c.matter_id = %(matter)s AND c.chunk_level = 'CHILD' AND c.batch_seq <= %(as_of)s AND c.tsv @@ q.tsq
    ORDER BY rank_lex
    LIMIT %(limit)s
),
fused AS (
    SELECT chunk_id, SUM(score) AS rrf_score FROM (
        SELECT chunk_id, 1.0 / (60 + rank_vec) AS score FROM vector_matches
        UNION ALL
        SELECT chunk_id, 1.0 / (60 + rank_lex) FROM lexical_matches
    ) s GROUP BY chunk_id
)
SELECT c.chunk_id, c.parent_chunk_id, c.document_id, c.page_start, c.page_end, c.structural_ref, c.chunk_text, c.context_header,
       d.title AS document_title, d.document_type, d.document_date,
       COALESCE(p.chunk_text, c.chunk_text) AS parent_text, f.rrf_score
FROM fused f JOIN document_chunks c USING (chunk_id) JOIN documents d ON d.document_id = c.document_id
LEFT JOIN document_chunks p ON p.chunk_id = c.parent_chunk_id
ORDER BY f.rrf_score DESC LIMIT %(limit)s
"""


def _set_iterative_scan(conn: Conn) -> None:
    try:
        with conn.transaction():
            conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
    except psycopg.Error:  # pgvector < 0.8: filtered HNSW scans may return fewer rows, still correct
        pass


def search_chunks(
    conn: Conn, embedder: Embedder, reranker: Reranker, *, matter_id: str, query: str, as_of: int,
    candidates: int = 30, final: int = 8, only_documents: list[str] | None = None,
) -> list[Hit]:  # fmt: skip
    """Top `final` child chunks for `query` within one matter, as known after batch `as_of`."""
    text = " ".join((query or "").split())
    if not text:
        return []
    vec = embedder.embed([text])[0]
    _set_iterative_scan(conn)
    rows = conn.execute(
        _HYBRID_SQL,
        {"text": text, "vec": Vector(vec), "matter": matter_id, "as_of": as_of, "limit": candidates},
    ).fetchall()
    if only_documents:
        allowed = set(only_documents)
        rows = [r for r in rows if str(r["document_id"]) in allowed]
    hits = [
        Hit(
            chunk_id=str(r["chunk_id"]), parent_chunk_id=str(r["parent_chunk_id"]) if r["parent_chunk_id"] else None,
            document_id=str(r["document_id"]), document_title=r["document_title"], document_type=r["document_type"],
            document_date=r["document_date"], page_start=r["page_start"], page_end=r["page_end"], structural_ref=r["structural_ref"],
            text=r["chunk_text"], parent_text=r["parent_text"], rrf=float(r["rrf_score"]),
        )
        for r in rows
    ]  # fmt: skip
    if not hits:
        return []
    scores = reranker.rerank(
        text, [f"{r['context_header']}\n{h.text}" for r, h in zip(rows, hits, strict=True)]
    )
    for h, s in zip(hits, scores, strict=True):
        h.rerank = s
    hits.sort(key=lambda h: (h.rerank if h.rerank is not None else 0.0, h.rrf), reverse=True)
    hits = hits[:final]
    attach_fact_states(conn, matter_id, hits, as_of)
    return hits


def attach_fact_states(conn: Conn, matter_id: str, hits: list[Hit], as_of: int) -> None:
    """Tag each chunk with the facts sourced from it and their state, so superseded facts are never read as current."""
    if not hits:
        return
    rows = conn.execute(
        "SELECT a.source_chunk_id, a.assertion_id, a.assertion_text, a.evidence_only, a.ended_in_batch_seq, "
        "(SELECT l.new_state FROM fact_change_log l WHERE l.assertion_id = a.assertion_id AND l.batch_seq <= %s "
        "  ORDER BY l.batch_seq DESC, l.change_id DESC LIMIT 1) AS state_as_of, "
        "(SELECT d2.title || ', p.' || n.source_page FROM matter_fact_assertions n JOIN documents d2 ON d2.document_id = n.originating_document_id "
        "  WHERE n.assertion_id = a.superseded_by_assertion_id) AS superseded_by "
        "FROM matter_fact_assertions a WHERE a.matter_id = %s AND a.source_chunk_id = ANY(%s::uuid[]) AND a.learned_in_batch_seq <= %s",
        (as_of, matter_id, [h.chunk_id for h in hits], as_of),
    ).fetchall()
    by_chunk: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ended = r["ended_in_batch_seq"]
        state = "SUPERSEDED" if ended is not None and ended <= as_of else (r["state_as_of"] or "ACTIVE")
        by_chunk.setdefault(str(r["source_chunk_id"]), []).append(
            {"assertion_id": str(r["assertion_id"]), "text": r["assertion_text"], "state": state, "evidence_only": r["evidence_only"],
             "superseded_by": r["superseded_by"] if state == "SUPERSEDED" else None}
        )  # fmt: skip
    for h in hits:
        h.facts = by_chunk.get(h.chunk_id, [])


_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "as",
        "from",
        "that",
        "this",
        "it",
        "its",
        "what",
        "when",
        "who",
        "whom",
        "which",
        "how",
        "much",
        "many",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "not",
        "no",
        "any",
        "all",
        "there",
        "their",
        "they",
        "them",
        "his",
        "her",
        "he",
        "she",
        "we",
        "our",
        "you",
        "your",
        "i",
        "me",
        "my",
        "about",
        "under",
        "over",
        "per",
        "than",
        "give",
        "tell",
        "show",
        "me",
        "please",
        "can",
        "could",
        "would",
        "should",
        "will",
        "shall",
        "may",
        "might",
        "now",
        "currently",
        "current",
        "still",
        "latest",
        "today",
        "yet",
        "already",
    ]
)


def keywords(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z0-9][a-z0-9\-/]*", (text or "").lower()) if w not in _STOP and len(w) > 1
    ]
