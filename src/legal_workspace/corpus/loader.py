"""Load the public legal corpus (separate schema, never mixed with matter facts; blueprint §11)."""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from legal_workspace.db.pool import Conn

from ..adapters.embed import Embedder
from ..errors import ValidationFailed

log = logging.getLogger(__name__)
DEFAULT_SEED = Path("data/corpus/seed.yaml")
UNVERIFIED = "UNVERIFIED-SEED (paraphrased summary; replace with the official text)"


def parse_seed(path: Path) -> list[dict[str, Any]]:
    try:
        blob = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ValidationFailed(f"corpus file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ValidationFailed(f"corpus file is not valid YAML: {e}") from e
    sources = (blob or {}).get("sources") if isinstance(blob, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ValidationFailed("corpus file has no 'sources' list")
    seen: set[str] = set()
    for s in sources:
        for field in ("key", "type", "title", "source_url", "passages"):
            if not s.get(field):
                raise ValidationFailed(f"source {s.get('key', '?')!r} is missing {field!r}")
        if s["type"] not in ("STATUTE", "JUDGMENT"):
            raise ValidationFailed(f"source {s['key']!r}: type must be STATUTE or JUDGMENT")
        if s["key"] in seen:
            raise ValidationFailed(f"duplicate source key {s['key']!r}")
        seen.add(s["key"])
        for p in s["passages"]:
            if not str(p.get("content", "")).strip():
                raise ValidationFailed(f"source {s['key']!r} has a passage without content")
    return sources


def load_corpus(conn: Conn, embedder: Embedder, path: Path = DEFAULT_SEED) -> dict[str, int]:
    """Idempotent: each source is replaced wholesale. Returns counts."""
    sources = parse_seed(path)
    n_pass = 0
    for s in sources:
        status = "VERIFIED" if s.get("verified_by") else "UNVERIFIED"
        with conn.transaction():
            conn.execute("DELETE FROM legal_corpus.sources WHERE source_key = %s", (s["key"],))
            row = conn.execute(
                "INSERT INTO legal_corpus.sources (source_key, source_type, title, citation, court, decision_date, source_url, "
                "treatment_note, verified_by, verified_on, verification_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING source_id",
                (
                    s["key"], s["type"], s["title"], s.get("citation"), s.get("court"), s.get("decision_date"), s["source_url"],
                    s.get("treatment_note"), s.get("verified_by") or UNVERIFIED, s.get("verified_on") or date.today(), status,
                ),
            ).fetchone()  # fmt: skip
            assert row is not None
            texts = [
                f"{s['title']} {p.get('section_ref', '')} {p.get('heading', '')}\n{' '.join(str(p['content']).split())}"
                for p in s["passages"]
            ]
            vectors = embedder.embed(texts)
            from pgvector import Vector

            for p, v in zip(s["passages"], vectors, strict=True):
                conn.execute(
                    "INSERT INTO legal_corpus.passages (source_id, section_ref, paragraph_number, heading, content, issue_tags, dense_embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (row["source_id"], p.get("section_ref"), p.get("paragraph_number"), p.get("heading"), " ".join(str(p["content"]).split()),
                     list(p.get("tags") or []), Vector(v)),
                )  # fmt: skip
                n_pass += 1
    return {"sources": len(sources), "passages": n_pass}


def corpus_count(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) AS n FROM legal_corpus.passages").fetchone()
    return int(row["n"]) if row else 0


def main() -> None:
    from ..adapters.factory import get_embedder
    from ..db.migrate import migrate
    from ..db.pool import connection
    from ..logging_setup import setup_logging

    setup_logging("INFO")
    ap = argparse.ArgumentParser(description="Load the legal corpus")
    ap.add_argument("--file", type=Path, default=DEFAULT_SEED)
    args = ap.parse_args()
    migrate()
    with connection() as conn:
        counts = load_corpus(conn, get_embedder(), args.file)
        conn.commit()
    print(f"loaded {counts['passages']} passages from {counts['sources']} sources")


if __name__ == "__main__":
    main()
