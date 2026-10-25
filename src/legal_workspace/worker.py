"""Ingestion worker: claims jobs from PostgreSQL and runs them (blueprint ADR-02, §7.6).

Jobs retry up to `job_max_attempts`; a job stuck RUNNING past `job_stale_after_s` is re-queued.
Parse errors are final (retrying a corrupt file cannot help); model outages are retried.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Any

from .config import get_settings
from .db import documents as doc_repo
from .db import jobs as job_repo
from .db import matters as matter_repo
from .db.pool import connection
from .deps import Deps, default_deps
from .errors import AppError, ModelUnavailable, ParseError
from .ingestion import service

log = logging.getLogger(__name__)


def _is_final(e: Exception) -> bool:
    if isinstance(e, ParseError):
        return True
    return isinstance(e, ModelUnavailable) and e.extra.get("retryable") is False


def process_job(deps: Deps, job: dict[str, Any]) -> bool:
    """Run one claimed job on its own connection. Returns True on success."""
    s = deps.settings
    job_id, stage = job["job_id"], job["stage"]
    started = time.monotonic()
    with connection() as conn:
        try:
            if stage == "PARSE":
                timings = service.run_parse(conn, deps, str(job["document_id"]))
            elif stage == "EXTRACT":
                timings = service.run_extract(conn, deps, str(job["document_id"]))
            else:
                from .memory.reconcile import reconcile_batch

                timings = reconcile_batch(conn, deps, str(job["matter_id"]), job["batch_seq"])
            timings["total_ms"] = int((time.monotonic() - started) * 1000)
            job_repo.complete(conn, job_id, timings)
            conn.commit()
            log.info(
                "job %s %s done",
                job_id,
                stage,
                extra={"job_id": job_id, "stage": stage, "elapsed_ms": timings["total_ms"]},
            )
            return True
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            msg = e.detail if isinstance(e, AppError) else f"{e.__class__.__name__}: {e}"
            log.warning("job %s %s failed: %s", job_id, stage, msg, exc_info=not isinstance(e, AppError))
            status = job_repo.fail(conn, job_id, msg, s.job_max_attempts, retryable=not _is_final(e))
            if status == "FAILED":
                if job["document_id"]:
                    doc_repo.update_document(
                        conn, str(job["document_id"]), status="FAILED", error_message=msg[:1000]
                    )
                else:
                    matter_repo.set_batch_status(conn, str(job["matter_id"]), job["batch_seq"], "FAILED")
            conn.commit()
            return False


class Worker:
    def __init__(self, deps: Deps | None = None, concurrency: int | None = None) -> None:
        self.deps = deps or default_deps()
        self.concurrency = concurrency or self.deps.settings.worker_concurrency
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_sweep = 0.0

    def _claim(self) -> dict[str, Any] | None:
        with connection() as conn:
            now = time.monotonic()
            if now - self._last_sweep > 30:
                self._last_sweep = now
                n = job_repo.requeue_stale(
                    conn, self.deps.settings.job_stale_after_s, self.deps.settings.job_max_attempts
                )
                if n:
                    log.warning("re-queued %d stale job(s)", n)
            job = job_repo.claim(conn)
            conn.commit()
            return job

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._claim()
            except Exception:  # noqa: BLE001
                log.exception("claim failed; backing off")
                self._stop.wait(2.0)
                continue
            if job is None:
                self._stop.wait(0.5)
                continue
            process_job(self.deps, job)

    def start(self) -> None:
        self._stop.clear()
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"lw-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        log.info("worker started with %d thread(s)", self.concurrency)

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()

    def run_until_idle(self, timeout_s: float = 600.0) -> int:
        """Process jobs in the calling thread until nothing is queued or running. Returns jobs processed."""
        deadline = time.monotonic() + timeout_s
        done = 0
        while time.monotonic() < deadline:
            job = self._claim()
            if job is not None:
                process_job(self.deps, job)
                done += 1
                continue
            with connection() as conn:
                row = conn.execute(
                    "SELECT count(*) AS n FROM ingestion_jobs WHERE status IN ('QUEUED','RUNNING')"
                ).fetchone()
                conn.commit()
            if not row or row["n"] == 0:
                return done
            time.sleep(0.2)
        raise TimeoutError(f"worker did not become idle within {timeout_s}s")


def main() -> None:
    from .db.migrate import migrate
    from .logging_setup import setup_logging

    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    migrate()
    w = Worker()
    w.start()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    w.stop()


if __name__ == "__main__":
    main()
