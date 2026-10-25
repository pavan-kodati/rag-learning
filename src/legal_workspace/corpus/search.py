"""Search the legal corpus: dense + full-text (RRF) with an issue-tag boost."""

from __future__ import annotations

from typing import Any

from pgvector import Vector

from legal_workspace.db.pool import Conn

from ..adapters.embed import Embedder

_SQL = """
WITH q AS (
    SELECT (replace(plainto_tsquery('english', %(text)s)::text, '&', '|')::tsquery
         || replace(plainto_tsquery('simple',  %(text)s)::text, '&', '|')::tsquery) AS tsq
),
v AS (
    SELECT passage_id, ROW_NUMBER() OVER (ORDER BY dense_embedding <=> %(vec)s) AS r
    FROM legal_corpus.passages ORDER BY dense_embedding <=> %(vec)s LIMIT 30
),
l AS (
    SELECT p.passage_id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(p.tsv, q.tsq) DESC) AS r
    FROM legal_corpus.passages p, q WHERE p.tsv @@ q.tsq ORDER BY r LIMIT 30
),
t AS (
    SELECT passage_id, cardinality(ARRAY(SELECT unnest(issue_tags) INTERSECT SELECT unnest(%(tags)s::text[]))) AS overlap
    FROM legal_corpus.passages WHERE issue_tags && %(tags)s::text[]
),
s AS (
    SELECT passage_id, SUM(sc) AS score FROM (
        SELECT passage_id, 1.0 / (60 + r) AS sc FROM v
        UNION ALL SELECT passage_id, 1.0 / (60 + r) FROM l
        UNION ALL SELECT passage_id, 0.012 * overlap FROM t
    ) x GROUP BY passage_id
)
SELECT p.passage_id, p.section_ref, p.paragraph_number, p.heading, p.content, p.issue_tags, s.score,
       src.source_key, src.source_type, src.title, src.citation, src.court, src.decision_date, src.source_url,
       src.treatment_note, src.verification_status
FROM s JOIN legal_corpus.passages p USING (passage_id) JOIN legal_corpus.sources src USING (source_id)
ORDER BY s.score DESC LIMIT %(k)s
"""


def search_corpus(
    conn: Conn, embedder: Embedder, query: str, *, tags: list[str] | None = None, k: int = 6
) -> list[dict[str, Any]]:
    tags = tags or []
    text = " ".join((query or "").split()) or " ".join(t.replace("_", " ") for t in tags[:6])
    if not text:
        return []
    vec = embedder.embed([text])[0]
    return conn.execute(_SQL, {"text": text, "vec": Vector(vec), "tags": tags, "k": k}).fetchall()


def known_authorities(conn: Conn) -> dict[str, dict[str, Any]]:
    """Every source / passage the corpus holds, keyed by passage id (used to reject citations that are not in the corpus)."""
    rows = conn.execute(
        "SELECT p.passage_id, p.section_ref, p.content, s.title, s.source_key FROM legal_corpus.passages p JOIN legal_corpus.sources s USING (source_id)"
    ).fetchall()
    return {str(r["passage_id"]): r for r in rows}
