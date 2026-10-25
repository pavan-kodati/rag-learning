"""Shared fixtures. DB tests need PostgreSQL + pgvector at TEST_DATABASE_URL (CI provides one)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://lw:lw@localhost:5432/legal_workspace_test")


def _db_available() -> bool:
    try:
        with psycopg.connect(TEST_URL, connect_timeout=3) as c:
            c.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


DB_OK = _db_available()


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    if DB_OK:
        return
    skip = pytest.mark.skip(reason=f"PostgreSQL not reachable at {TEST_URL}")
    for item in items:
        if "db" in item.keywords or "e2e" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def _schema(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    if not DB_OK:
        yield
        return
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ["STORAGE_DIR"] = str(tmp_path_factory.mktemp("storage"))
    os.environ["LLM_PROVIDER"] = "fixture"
    os.environ["EMBEDDER"] = "hashing"
    os.environ["EMBEDDED_WORKER"] = "false"
    os.environ["AUTH_ENABLED"] = "false"
    from legal_workspace.config import reset_settings_cache
    from legal_workspace.db.migrate import migrate
    from legal_workspace.db.pool import close_pool

    reset_settings_cache()
    close_pool()
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS legal_corpus CASCADE")
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
    migrate(TEST_URL)
    yield
    close_pool()


@pytest.fixture
def conn(_schema) -> Iterator[psycopg.Connection]:
    """A connection per test; all tables are emptied afterwards."""
    c = psycopg.connect(TEST_URL, row_factory=dict_row)  # type: ignore[arg-type]
    register_vector(c)
    try:
        yield c
        c.commit()
    finally:
        c.rollback()
        tables = [
            r["tablename"]
            for r in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname IN ('public','legal_corpus') AND tablename <> 'schema_migrations'"
            ).fetchall()
        ]
        # schema-qualify corpus tables
        qualified = []
        for r in c.execute(
            "SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('public','legal_corpus') "
            "AND tablename <> 'schema_migrations'"
        ).fetchall():
            qualified.append(f'{r["schemaname"]}."{r["tablename"]}"')
        if tables:
            c.execute("TRUNCATE " + ", ".join(qualified) + " RESTART IDENTITY CASCADE")
            c.commit()
        c.close()


@pytest.fixture
def storage_dir(_schema) -> Path:
    return Path(os.environ["STORAGE_DIR"])


@pytest.fixture
def make_deps(storage_dir: Path):  # noqa: ANN201
    """Factory for Deps with a scripted LLM, the offline embedder and a throw-away storage directory."""
    from legal_workspace.adapters.embed import HashingEmbedder
    from legal_workspace.adapters.rerank import NoopReranker
    from legal_workspace.config import get_settings
    from legal_workspace.deps import Deps
    from legal_workspace.storage import FileStorage

    def _make(llm, **settings_override):  # noqa: ANN001, ANN202
        s = get_settings().model_copy(update=settings_override)
        return Deps(s, llm, HashingEmbedder(), NoopReranker(), FileStorage(storage_dir / "deps"))

    return _make


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def fixture_deps(make_deps):  # noqa: ANN001, ANN201
    """Deps that replay the recorded extractions of the bundled synthetic matters (no model)."""
    from legal_workspace.adapters.llm import FixtureLLM

    return make_deps(FixtureLLM(DATA_DIR / "fixtures"))


@pytest.fixture
def m2(conn, fixture_deps):  # noqa: ANN001, ANN201
    """Matter M2 replayed through batch 1 (call `replay_next` for batch 2)."""
    from legal_workspace.eval import replay

    manifest = replay.load_manifest(DATA_DIR, "M2")
    matter = replay.create_matter_from_manifest(conn, manifest)
    conn.commit()
    state = {
        "conn": conn,
        "deps": fixture_deps,
        "matter": matter,
        "manifest": manifest,
        "reports": {},
        "uploads": {},
    }

    def replay_next(batch: int):  # noqa: ANN202
        report, uploads, _ = replay.replay_batch(
            conn, fixture_deps, str(matter["matter_id"]), DATA_DIR, manifest, batch
        )
        state["reports"][batch], state["uploads"][batch] = report, uploads
        return report

    state["replay_next"] = replay_next
    return state


@pytest.fixture
def scenario(conn, make_deps):  # noqa: ANN001, ANN201
    """Build a matter from an in-memory synthetic spec and replay it batch by batch with recorded model outputs."""
    from legal_workspace.adapters.llm import FixtureLLM
    from legal_workspace.eval import replay
    from legal_workspace.synthetic.generate import render_matter

    class Scenario:
        def __init__(self, spec):  # noqa: ANN001, ANN204
            self.spec = spec
            files, fixtures, _ = render_matter(spec)
            self.files = files
            self.deps = make_deps(FixtureLLM(records=fixtures))
            self.conn = conn
            self.matter = replay.create_matter_from_manifest(
                conn,
                {"number": spec.number, "title": spec.title, "type": spec.matter_type, "forum": spec.forum},
            )
            conn.commit()
            self.mid = str(self.matter["matter_id"])
            self.reports: dict[int, dict] = {}
            self.uploads: dict[int, list] = {}

        def run(self, batch: int):  # noqa: ANN201
            names = [d.file for d in self.spec.docs if d.batch == batch]
            report, uploads, _ = replay.replay_files(
                conn, self.deps, self.mid, batch, [(n, self.files[n]) for n in names]
            )
            self.reports[batch], self.uploads[batch] = report, uploads
            return report

        def facts(self, key: str, evidence: bool | None = None):  # noqa: ANN201
            sql = "SELECT * FROM matter_fact_assertions WHERE matter_id = %s AND fact_key = %s"
            if evidence is not None:
                sql += " AND evidence_only = " + ("TRUE" if evidence else "FALSE")
            return conn.execute(sql + " ORDER BY created_at", (self.mid, key)).fetchall()

    return Scenario


@pytest.fixture
def corpus(conn, fixture_deps):  # noqa: ANN001, ANN201
    from legal_workspace.corpus.loader import load_corpus

    counts = load_corpus(conn, fixture_deps.embedder, DATA_DIR / "corpus" / "seed.yaml")
    conn.commit()
    return counts


class HybridLLM:
    """Replays recorded ingestion output (fixture) and answers generation tasks with a test-supplied function."""

    supports_generation = True

    def __init__(self, fixture, handler):  # noqa: ANN001, ANN204
        self.fixture, self.handler, self.calls = fixture, handler, []

    def chat_json(self, *, role, system, user, schema, task="", meta=None, max_tokens=2048):  # noqa: ANN001, ANN201
        if task in ("classify", "extract"):
            return self.fixture.chat_json(
                role=role,
                system=system,
                user=user,
                schema=schema,
                task=task,
                meta=meta,
                max_tokens=max_tokens,
            )
        self.calls.append({"task": task, "system": system, "user": user, "role": role})
        if task == "route":  # tests control answers and narratives; routing falls through to factual Q&A
            return {"intents": ["FACTUAL_QA"]}
        return self.handler(task, system, user, schema, meta or {})

    def health(self):  # noqa: ANN201
        return {"ok": True}

    def model_names(self):  # noqa: ANN201
        return {"main": "test-main", "fast": "test-fast"}


@pytest.fixture
def gen_m2(conn, make_deps):  # noqa: ANN001, ANN201
    """M2 replayed through both batches with a generation-capable model whose answers a test controls."""
    from legal_workspace.adapters.llm import FixtureLLM
    from legal_workspace.eval import replay

    state: dict = {"handler": lambda *a: {"sentences": [], "not_found": ["nothing"]}}
    llm = HybridLLM(FixtureLLM(DATA_DIR / "fixtures"), lambda *a: state["handler"](*a))
    deps = make_deps(llm)
    manifest = replay.load_manifest(DATA_DIR, "M2")
    matter = replay.create_matter_from_manifest(conn, manifest)
    conn.commit()
    for b in (1, 2):
        replay.replay_batch(conn, deps, str(matter["matter_id"]), DATA_DIR, manifest, b)
    from legal_workspace.corpus.loader import load_corpus

    load_corpus(conn, deps.embedder, DATA_DIR / "corpus" / "seed.yaml")
    conn.commit()
    state.update(conn=conn, deps=deps, mid=str(matter["matter_id"]), llm=llm)
    return state


@pytest.fixture
def api(conn, fixture_deps, monkeypatch):  # noqa: ANN001, ANN201
    """The real FastAPI app on the test database with recorded model output (no embedded worker; tests run the worker explicitly)."""
    from fastapi.testclient import TestClient

    from legal_workspace.api.main import create_app
    from legal_workspace.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "corpus_autoload", False)
    monkeypatch.setattr(s, "rate_limit_per_min", 0)
    app = create_app(fixture_deps, start_worker=False, migrate=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.deps = fixture_deps  # type: ignore[attr-defined]
        client.app_ref = app  # type: ignore[attr-defined]
        yield client
