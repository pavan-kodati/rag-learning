"""PostgreSQL job queue (blueprint ADR-02): FOR UPDATE SKIP LOCKED, stale-lock recovery, capped attempts."""

from __future__ import annotations

from typing import Any

from legal_workspace.db.pool import Conn

Row = dict[str, Any]


def enqueue(
    conn: Conn, matter_id: str, batch_seq: int, stage: str, document_id: str | None = None
) -> int | None:
    """Queue a job; returns its id, or None if an identical job already exists (idempotent)."""
    if stage == "RECONCILE":
        row = conn.execute(
            "INSERT INTO ingestion_jobs (matter_id, batch_seq, stage) VALUES (%s,%s,'RECONCILE') "
            "ON CONFLICT DO NOTHING RETURNING job_id",
            (matter_id, batch_seq),
        ).fetchone()
    else:
        row = conn.execute(
            "INSERT INTO ingestion_jobs (matter_id, batch_seq, document_id, stage) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING job_id",
            (matter_id, batch_seq, document_id, stage),
        ).fetchone()
    return int(row["job_id"]) if row else None


_CLAIM = """
UPDATE ingestion_jobs SET status = 'RUNNING', locked_at = now(), attempts = attempts + 1
WHERE job_id = (
    SELECT j.job_id FROM ingestion_jobs j
    WHERE j.status = 'QUEUED'
      AND (j.stage <> 'RECONCILE' OR NOT EXISTS (
            SELECT 1 FROM ingestion_jobs o
            WHERE o.matter_id = j.matter_id AND o.batch_seq = j.batch_seq AND o.stage <> 'RECONCILE'
              AND o.status IN ('QUEUED', 'RUNNING')))
    ORDER BY j.job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING job_id, matter_id, batch_seq, document_id, stage, attempts
"""


def claim(conn: Conn) -> Row | None:
    """Take one job; a job locked by another worker is skipped. RECONCILE waits for its batch's other jobs."""
    return conn.execute(_CLAIM).fetchone()


def complete(conn: Conn, job_id: int, timings_ms: dict | None = None) -> None:
    from psycopg.types.json import Jsonb

    conn.execute(
        "UPDATE ingestion_jobs SET status = 'DONE', finished_at = now(), locked_at = NULL, timings_ms = %s WHERE job_id = %s",
        (Jsonb(timings_ms or {}), job_id),
    )


def fail(conn: Conn, job_id: int, error: str, max_attempts: int, retryable: bool = True) -> str:
    """Re-queue until attempts are exhausted, then mark FAILED. Returns the new status."""
    row = conn.execute("SELECT attempts FROM ingestion_jobs WHERE job_id = %s", (job_id,)).fetchone()
    attempts = row["attempts"] if row else max_attempts
    status = "QUEUED" if (retryable and attempts < max_attempts) else "FAILED"
    conn.execute(
        "UPDATE ingestion_jobs SET status = %s, last_error = %s, locked_at = NULL, "
        "finished_at = CASE WHEN %s = 'FAILED' THEN now() END WHERE job_id = %s",
        (status, error[:4000], status, job_id),
    )
    return status


def requeue_stale(conn: Conn, older_than_s: int, max_attempts: int) -> int:
    """A job RUNNING for too long (worker died) goes back to the queue, or fails if out of attempts."""
    rows = conn.execute(
        "UPDATE ingestion_jobs SET status = CASE WHEN attempts >= %s THEN 'FAILED' ELSE 'QUEUED' END, locked_at = NULL, "
        "last_error = 'worker lost (stale lock)', finished_at = CASE WHEN attempts >= %s THEN now() END "
        "WHERE status = 'RUNNING' AND locked_at < now() - make_interval(secs => %s) RETURNING job_id",
        (max_attempts, max_attempts, older_than_s),
    ).fetchall()
    return len(rows)


def batch_progress(conn: Conn, matter_id: str, batch_seq: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, count(*) AS n FROM ingestion_jobs WHERE matter_id = %s AND batch_seq = %s AND stage <> 'RECONCILE' "
        "GROUP BY status",
        (matter_id, batch_seq),
    ).fetchall()
    out = {"QUEUED": 0, "RUNNING": 0, "DONE": 0, "FAILED": 0}
    for r in rows:
        out[r["status"]] = int(r["n"])
    return out


def get_job(conn: Conn, job_id: int) -> Row | None:
    return conn.execute("SELECT * FROM ingestion_jobs WHERE job_id = %s", (job_id,)).fetchone()
