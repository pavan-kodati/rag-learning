"""Forward-only SQL migrations with checksums and a start-up advisory lock."""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import psycopg

from ..config import get_settings

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_KEY = 727_001


class MigrationError(RuntimeError):
    pass


def _files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def migrate(database_url: str | None = None) -> list[str]:
    """Apply pending migrations; returns the versions applied. Safe to call concurrently."""
    url = database_url or get_settings().database_url
    applied_now: list[str] = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r[0]: r[1] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
            for path in _files():
                version = path.stem
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                if version in done:
                    if done[version] != checksum:
                        raise MigrationError(f"migration {version} was modified after it was applied")
                    continue
                log.info("applying migration %s", version)
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (version, checksum),
                    )
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied_now


def main() -> None:
    from ..logging_setup import setup_logging

    setup_logging(get_settings().log_level)
    ap = argparse.ArgumentParser(description="Apply database migrations")
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()
    applied = migrate(args.database_url)
    print("applied:", ", ".join(applied) if applied else "nothing to do")


if __name__ == "__main__":
    main()
