"""Replay the synthetic matters batch by batch and score the system against the golden set (blueprint §18).

Works with any configured model: with LLM_PROVIDER=fixture it tests the pipeline logic (recorded extractions); with a real
model (ollama / openai_compat) it measures how well that model actually reads the documents.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings
from ..corpus.loader import corpus_count, load_corpus
from ..db.migrate import migrate
from ..db.pool import connection
from ..deps import default_deps
from ..grounding.answer import ask
from ..grounding.brief import generate_brief
from ..logging_setup import setup_logging
from ..retrieval.hybrid import search_chunks
from . import replay
from .checker import check_planted, check_question

log = logging.getLogger(__name__)
EVAL_TODAY = date(2025, 10, 20)
TARGETS = {
    "answer_correctness": 0.90,
    "citation_precision": 0.95,
    "planted_detected": 0.90,
    "recall_at_8": 0.85,
    "unanswerable_not_found": 1.0,
}


@dataclass
class MatterScore:
    matter: str
    batches: int = 0
    questions: int = 0
    passed: int = 0
    failures: dict[str, list[str]] = field(default_factory=dict)
    planted_total: int = 0
    planted_found: int = 0
    planted_missing: list[str] = field(default_factory=list)
    unanswerable_total: int = 0
    unanswerable_ok: int = 0
    cites_total: int = 0
    cites_ok: int = 0
    retrieval_total: int = 0
    retrieval_hits: int = 0
    seconds_per_batch: dict[int, float] = field(default_factory=dict)
    pages_per_batch: dict[int, int] = field(default_factory=dict)
    duplicate_facts: int = 0
    failed_documents: int = 0
    brief_ok: bool = False


def _rate(a: int, b: int) -> float:
    return a / b if b else 1.0


def score_matter(conn: Any, deps: Any, data_dir: Path, matter_key: str, keep: bool) -> MatterScore:
    manifest = replay.load_manifest(data_dir, matter_key)
    golden = yaml.safe_load((data_dir / "synthetic" / matter_key / "golden.yaml").read_text()) or []
    planted = yaml.safe_load((data_dir / "synthetic" / matter_key / "planted.yaml").read_text()) or []
    if keep:
        conn.execute("DELETE FROM matters WHERE matter_number = %s", (manifest["number"],))
        suffix = ""
    else:
        suffix = f" [eval {datetime.now():%H%M%S%f}]"
    matter = replay.create_matter_from_manifest(conn, manifest, suffix)
    conn.commit()
    mid = str(matter["matter_id"])
    sc = MatterScore(matter_key)
    for batch in sorted(int(b) for b in manifest["batches"]):
        report, uploads, secs = replay.replay_batch(conn, deps, mid, data_dir, manifest, batch)
        sc.batches += 1
        sc.seconds_per_batch[batch] = round(secs, 2)
        pages = conn.execute(
            "SELECT COALESCE(sum(total_pages), 0) AS n FROM documents WHERE matter_id = %s AND batch_seq = %s",
            (mid, batch),
        ).fetchone()
        sc.pages_per_batch[batch] = int(pages["n"]) if pages else 0
        sc.failed_documents += len(report["documents_failed"])
        missing = check_planted(report, planted, batch)
        sc.planted_total += sum(1 for p in planted if p["batch"] == batch)
        sc.planted_found += sum(1 for p in planted if p["batch"] == batch) - len(missing)
        sc.planted_missing += [f"batch {batch}: {m}" for m in missing]
        for q in (g for g in golden if g["batch"] == batch):
            ans = ask(conn, deps, mid, q["question"], as_of=batch, today=EVAL_TODAY, actor="eval")
            conn.commit()
            res = check_question(conn, mid, q, ans)
            sc.questions += 1
            sc.passed += int(res.passed)
            if not res.passed:
                sc.failures[q["id"]] = res.failures
            if q.get("not_found"):
                sc.unanswerable_total += 1
                sc.unanswerable_ok += int(res.passed)
            for s in ans["answer_sentences"]:
                if s["status"] == "VERIFIED":
                    sc.cites_total += 1
                    sc.cites_ok += int(bool(s["citations"]))
    last = max(int(b) for b in manifest["batches"])
    probes = yaml.safe_load((data_dir / "synthetic" / matter_key / "probes.yaml").read_text()) or []
    for pr in probes:  # retrieval quality: is the labelled chunk in the top 8?
        hits = search_chunks(
            conn, deps.embedder, deps.reranker, matter_id=mid, query=pr["query"], as_of=last, final=8
        )
        conn.commit()
        sc.retrieval_total += 1
        sc.retrieval_hits += int(
            any(
                pr["document"].lower() in h.document_title.lower() and h.page_start == pr["page"]
                for h in hits
            )
        )
    dup = conn.execute(
        "SELECT count(*) AS n FROM (SELECT fact_key, value_text, originating_document_id, count(*) FROM matter_fact_assertions WHERE matter_id = %s "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1) d",
        (mid,),
    ).fetchone()
    sc.duplicate_facts = int(dup["n"]) if dup else 0
    try:
        brief = generate_brief(conn, deps, mid, today=EVAL_TODAY, actor="eval")
        conn.commit()
        sc.brief_ok = len(brief["sections"]) == 8 and not brief["unverified"]
    except Exception as e:  # noqa: BLE001
        log.warning("brief failed: %s", e)
    if not keep:
        conn.execute("DELETE FROM matters WHERE matter_id = %s", (mid,))
        conn.commit()
    return sc


def summarise(scores: list[MatterScore]) -> dict[str, Any]:
    t = lambda f: sum(getattr(s, f) for s in scores)  # noqa: E731
    sec = sum(sum(s.seconds_per_batch.values()) for s in scores)
    pages = sum(sum(s.pages_per_batch.values()) for s in scores)
    return {
        "answer_correctness": _rate(t("passed"), t("questions")), "citation_precision": _rate(t("cites_ok"), t("cites_total")),
        "planted_detected": _rate(t("planted_found"), t("planted_total")), "recall_at_8": _rate(t("retrieval_hits"), t("retrieval_total")),
        "unanswerable_not_found": _rate(t("unanswerable_ok"), t("unanswerable_total")), "duplicate_facts": t("duplicate_facts"),
        "failed_documents": t("failed_documents"), "seconds_per_20_pages": round(sec / pages * 20, 2) if pages else 0.0,
        "questions": t("questions"), "planted": t("planted_total"), "briefs_ok": sum(int(s.brief_ok) for s in scores), "matters": len(scores),
    }  # fmt: skip


def render_markdown(scores: list[MatterScore], summary: dict[str, Any], mode: str) -> str:
    lines = [
        f"# Evaluation report ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        f"Model mode: **{mode}**",
        "",
        "| Metric | Result | Target | |",
        "| --- | --- | --- | --- |",
    ]
    for k, target in TARGETS.items():
        v = summary[k]
        lines.append(
            f"| {k.replace('_', ' ')} | {v:.1%} | ≥ {target:.0%} | {'PASS' if v >= target else 'FAIL'} |"
        )
    lines.append(
        f"| duplicate facts after re-upload | {summary['duplicate_facts']} | 0 | {'PASS' if summary['duplicate_facts'] == 0 else 'FAIL'} |"
    )
    lines.append(
        f"| ingestion seconds per 20 pages | {summary['seconds_per_20_pages']} | ≤ 120 | {'PASS' if summary['seconds_per_20_pages'] <= 120 else 'FAIL'} |"
    )
    lines += [
        "",
        "## By matter",
        "",
        "| Matter | Questions passed | Planted changes found | Failed documents | Brief |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        lines.append(
            f"| {s.matter} | {s.passed}/{s.questions} | {s.planted_found}/{s.planted_total} | {s.failed_documents} | {'ok' if s.brief_ok else 'issue'} |"
        )
    for s in scores:
        if s.failures or s.planted_missing:
            lines += ["", f"### {s.matter}: details"]
            lines += [f"- **{qid}**: {'; '.join(f)}" for qid, f in s.failures.items()]
            lines += [f"- planted change not found: {m}" for m in s.planted_missing]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay synthetic matters and score the system")
    ap.add_argument("--matters", nargs="+", default=["M1", "M2", "M3"])
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--report-dir", type=Path, default=Path("eval_reports"))
    ap.add_argument(
        "--keep", action="store_true", help="keep the matters in the database (so the UI can show them)"
    )
    ap.add_argument("--no-fail", action="store_true", help="always exit 0")
    args = ap.parse_args()
    s = get_settings()
    setup_logging("WARNING")
    migrate()
    deps = default_deps()
    mode = f"llm={s.llm_provider} ({deps.llm.model_names()['main']}), embedder={s.embedder}, reranker={s.reranker}"
    scores: list[MatterScore] = []
    with connection() as conn:
        if corpus_count(conn) == 0:
            load_corpus(conn, deps.embedder, Path(s.fixtures_dir).parent / "corpus" / "seed.yaml")
            conn.commit()
        for key in args.matters:
            if s.llm_provider == "fixture" and key == "M4":
                print("M4 has no recorded model output; run it with a real model (LLM_PROVIDER=ollama).")
                continue
            t0 = time.monotonic()
            print(f"== {key} ...", flush=True)
            sc = score_matter(conn, deps, args.data, key, args.keep)
            scores.append(sc)
            print(
                f"   {sc.passed}/{sc.questions} questions, {sc.planted_found}/{sc.planted_total} planted changes, {time.monotonic() - t0:.1f}s",
                flush=True,
            )
    from ..db.pool import close_pool

    close_pool()
    summary = summarise(scores)
    md = render_markdown(scores, summary, mode)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    (args.report_dir / f"eval-{stamp}.md").write_text(md)
    (args.report_dir / f"eval-{stamp}.json").write_text(
        json.dumps(
            {"mode": mode, "summary": summary, "matters": [s.__dict__ for s in scores]}, indent=2, default=str
        )
    )
    print("\n" + md)
    failed = (
        any(summary[k] < v for k, v in TARGETS.items())
        or summary["duplicate_facts"]
        or summary["failed_documents"]
    )
    if failed and not args.no_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
