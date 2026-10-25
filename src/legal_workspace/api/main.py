"""FastAPI application factory (blueprint §16)."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import get_settings
from ..deps import Deps, default_deps
from ..errors import AppError
from ..logging_setup import setup_logging
from . import metrics
from .deps import client_ip
from .routes import auth as auth_routes
from .routes import documents, matters, query, review, system
from .security import RateLimiter

log = logging.getLogger("legal_workspace.api")
PROBLEM = "application/problem+json"


def problem(status: int, code: str, title: str, detail: str, request: Request, **extra: Any) -> JSONResponse:
    body = {"type": f"https://legal-workspace.local/problems/{code}", "title": title, "status": status, "detail": detail, "code": code,
            "request_id": getattr(request.state, "request_id", None), **extra}  # fmt: skip
    headers = {"Retry-After": str(extra["retry_after"])} if "retry_after" in extra else None
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


def create_app(
    deps: Deps | None = None, *, start_worker: bool | None = None, migrate: bool | None = None
) -> FastAPI:
    s = get_settings()
    setup_logging(s.log_level, s.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        from ..db.migrate import migrate as run_migrations

        if s.auto_migrate if migrate is None else migrate:
            run_migrations()
        app.state.deps = deps or default_deps()
        if s.corpus_autoload:
            _autoload_corpus(app.state.deps)
        worker = None
        if s.embedded_worker if start_worker is None else start_worker:
            from ..worker import Worker

            worker = Worker(app.state.deps)
            worker.start()
        app.state.worker = worker
        log.info("Legal Workspace %s started (llm=%s, embedder=%s)", __version__, s.llm_provider, s.embedder)
        yield
        if worker:
            worker.stop()

    app = FastAPI(
        title="Legal Workspace API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
        description="Persistent, evidence-grounded matter memory for Indian commercial and contract litigation. Every answer carries verified source citations.",
    )  # fmt: skip
    if deps is not None:  # tests can use the app without running the lifespan
        app.state.deps = deps
    app.state.limiter = RateLimiter(s.rate_limit_per_min)
    app.state.login_limiter = RateLimiter(s.login_attempts_per_min)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001, ANN202
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        t0 = time.monotonic()
        route = "unmatched"
        status = 500
        try:
            if request.url.path.startswith("/api/v1") and request.method != "OPTIONS":
                request.app.state.limiter.check(client_ip(request))
            response = await call_next(request)
            status = response.status_code
        except AppError as e:
            status = e.status
            response = problem(e.status, e.code, e.title, e.detail, request, **e.extra)
        except Exception:
            log.exception("unhandled error", extra={"trace_id": rid})
            response = problem(
                500,
                "internal_error",
                "Internal error",
                "Something went wrong. Quote the request id when reporting it.",
                request,
            )
        elapsed = time.monotonic() - t0
        r = request.scope.get("route")
        route = getattr(r, "path", "unmatched")
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        path = request.url.path
        if path.startswith("/api/v1") and not path.endswith(("/image", "/pdf")):
            response.headers.setdefault("Cache-Control", "no-store")
        metrics.REQUESTS.labels(request.method, route, str(status)).inc()
        metrics.LATENCY.labels(route).observe(elapsed)
        log.info(
            "%s %s -> %s in %dms",
            request.method,
            request.url.path,
            status,
            int(elapsed * 1000),
            extra={"trace_id": rid, "elapsed_ms": int(elapsed * 1000)},
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):  # noqa: ANN202
        return problem(exc.status, exc.code, exc.title, exc.detail, request, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):  # noqa: ANN202
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return problem(
            422,
            "validation_failed",
            "Validation failed",
            "; ".join(f"{e['field']}: {e['message']}" for e in errors)[:500],
            request,
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):  # noqa: ANN202
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return problem(
            exc.status_code,
            code,
            "Not found" if exc.status_code == 404 else "Request failed",
            str(exc.detail),
            request,
        )

    api = "/api/v1"
    app.include_router(system.router)
    app.include_router(system.api_router, prefix=api)
    app.include_router(auth_routes.router, prefix=api)
    app.include_router(matters.router, prefix=api)
    app.include_router(documents.router, prefix=api)
    app.include_router(query.router, prefix=api)
    app.include_router(review.router, prefix=api)
    _mount_ui(app)
    return app


def _mount_ui(app: FastAPI) -> None:
    """Serve the built single-page app at / when `ui/dist` exists, so one process is enough locally."""
    from fastapi.staticfiles import StaticFiles

    dist = get_settings().ui_dist
    if dist and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")


def _autoload_corpus(deps: Deps) -> None:
    from pathlib import Path

    from ..corpus.loader import DEFAULT_SEED, corpus_count, load_corpus
    from ..db.pool import connection

    try:
        with connection() as conn:
            if corpus_count(conn) == 0 and Path(DEFAULT_SEED).exists():
                counts = load_corpus(conn, deps.embedder, DEFAULT_SEED)
                log.info("legal corpus loaded: %s", counts)
    except Exception:  # noqa: BLE001 - the app must start even if the embedding model is not pulled yet
        log.warning(
            "could not auto-load the legal corpus (is the embedding model available?). Run `make corpus` later.",
            exc_info=True,
        )


def run() -> None:
    s = get_settings()
    uvicorn.run(
        "legal_workspace.api.main:app_factory",
        factory=True,
        host=s.api_host,
        port=s.api_port,
        log_config=None,
    )


def app_factory() -> FastAPI:
    return create_app()


if __name__ == "__main__":
    run()
