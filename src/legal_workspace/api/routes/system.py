"""Health, readiness, metrics."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from ... import __version__
from ...corpus.loader import corpus_count
from ...db.pool import connection, db_healthy
from ...deps import Deps
from .. import metrics
from ..deps import get_deps

router = APIRouter()
api_router = APIRouter(tags=["system"])
_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):  # noqa: ANN001, ANN202
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


@router.get("/docs-redirect", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/api/docs")


@router.get("/metrics", include_in_schema=False)
def prometheus() -> Response:
    try:
        with connection() as conn:
            for r in conn.execute(
                "SELECT status, count(*) AS n FROM ingestion_jobs GROUP BY status"
            ).fetchall():
                metrics.JOBS.labels(r["status"]).set(r["n"])
    except Exception:  # noqa: BLE001
        pass
    return Response(metrics.render(), media_type="text/plain; version=0.0.4")


@api_router.get("/healthz/live")
def live() -> dict[str, str]:
    """Liveness: the process is up (no dependencies are touched)."""
    return {"status": "alive"}


@api_router.get("/healthz")
def ready(request: Request, deps: Deps = Depends(get_deps)) -> JSONResponse:  # noqa: B008
    """Readiness: database, language model, embedder, reranker, corpus and worker."""
    db = db_healthy()
    llm = _cached("llm", 20, deps.llm.health)
    emb = _cached("emb", 60, deps.embedder.health)
    rer = _cached("rer", 300, deps.reranker.health)
    corpus = 0
    queue: dict[str, int] = {}
    if db:
        with connection() as conn:
            corpus = corpus_count(conn)
            queue = {
                r["status"]: r["n"]
                for r in conn.execute(
                    "SELECT status, count(*) AS n FROM ingestion_jobs GROUP BY status"
                ).fetchall()
            }
    worker = getattr(request.app.state, "worker", None)
    parts = {
        "database": db,
        "llm": llm.get("ok", False),
        "embedder": emb.get("ok", False),
        "reranker": rer.get("ok", False),
    }
    status = "ok" if all(parts.values()) else ("down" if not db else "degraded")
    body = {
        "status": status, "version": __version__, "checks": {"database": {"ok": db}, "llm": llm, "embedder": emb, "reranker": rer},
        "corpus_passages": corpus, "jobs": queue, "embedded_worker": worker is not None,
        "mode": {"llm_provider": deps.settings.llm_provider, "embedder": deps.settings.embedder, "reranker": deps.settings.reranker, "models": deps.llm.model_names()},
    }  # fmt: skip
    return JSONResponse(body, status_code=503 if not db else 200)


@api_router.get("/version")
def version() -> dict[str, str]:
    return {"version": __version__}
