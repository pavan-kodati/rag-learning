"""Replay a synthetic matter through the real pipeline, batch by batch (used by tests, the demo and the evaluation)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from legal_workspace.db.pool import Conn

from ..db import matters as matter_repo
from ..deps import Deps
from ..ingestion import service
from ..memory.reports import build_changes
from ..worker import Worker

log = logging.getLogger(__name__)


@dataclass
class ReplayResult:
    matter_id: str
    reports: dict[int, dict[str, Any]] = field(default_factory=dict)
    uploads: dict[int, list[service.RegisterResult]] = field(default_factory=dict)
    seconds: dict[int, float] = field(default_factory=dict)


def load_manifest(data_dir: Path, matter_key: str) -> dict[str, Any]:
    path = data_dir / "synthetic" / matter_key / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `make synth` to generate the synthetic matters")
    return json.loads(path.read_text())


def create_matter_from_manifest(conn: Conn, manifest: dict[str, Any], suffix: str = "") -> dict[str, Any]:
    """Creates the matter with no pre-declared parties: they are discovered from the documents."""
    return matter_repo.create_matter(
        conn, matter_number=manifest["number"] + suffix, title=manifest["title"], matter_type=manifest["type"], forum=manifest["forum"],
    )  # fmt: skip


def replay_batch(
    conn: Conn, deps: Deps, matter_id: str, data_dir: Path, manifest: dict[str, Any], batch: int, timeout_s: float = 900,
) -> tuple[dict[str, Any], list[service.RegisterResult], float]:  # fmt: skip
    files = [
        (e["file"], (data_dir / "synthetic" / manifest["id"] / e["path"]).read_bytes())
        for e in manifest["batches"][str(batch)]
    ]
    return replay_files(conn, deps, matter_id, batch, files, timeout_s)


def replay_files(
    conn: Conn, deps: Deps, matter_id: str, batch: int, files: list[tuple[str, bytes]], timeout_s: float = 900,
) -> tuple[dict[str, Any], list[service.RegisterResult], float]:  # fmt: skip
    """Upload `files` as the next batch, commit it and run the worker until the batch is reconciled."""
    import time

    t0 = time.monotonic()
    b = matter_repo.open_batch(conn, matter_id, f"Batch {batch}")
    conn.commit()
    results = []
    for name, data in files:
        results.append(
            service.register_upload(
                conn, deps, matter_id=matter_id, batch_seq=b["batch_seq"], filename=name, data=data
            )
        )
        conn.commit()
    service.commit_batch(conn, matter_id, b["batch_seq"])
    conn.commit()
    Worker(deps, concurrency=1).run_until_idle(timeout_s)
    conn.commit()
    report = build_changes(conn, matter_id, b["batch_seq"])
    conn.commit()
    return report, results, time.monotonic() - t0


def replay_matter(
    conn: Conn, deps: Deps, matter: dict[str, Any], data_dir: Path, manifest: dict[str, Any], upto: int | None = None,
) -> ReplayResult:  # fmt: skip
    res = ReplayResult(str(matter["matter_id"]))
    for batch in sorted(int(b) for b in manifest["batches"]):
        if upto is not None and batch > upto:
            break
        report, uploads, secs = replay_batch(conn, deps, res.matter_id, data_dir, manifest, batch)
        res.reports[batch], res.uploads[batch], res.seconds[batch] = report, uploads, secs
    return res
