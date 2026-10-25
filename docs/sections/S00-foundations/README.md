# S00 · Foundations

## 1. Spec

**Goal:** a project skeleton any engineer can clone, install and run in minutes, with quality gates from day one.

**In scope:** package layout (src layout, one package, module per concern), typed configuration, structured logging,
tooling (ruff, mypy, pytest), Docker image, Docker Compose stack, Makefile, GitHub Actions CI.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S00-1 | `pip install -e ".[dev]"` succeeds on Python 3.11+ |
| S00-2 | All configuration comes from environment variables with working local defaults (`.env.example` documents them) |
| S00-3 | `docker compose up` brings up db + api + worker + ui; no cloud service, no paid component |
| S00-4 | CI runs lint, type-check, tests (with a real pgvector service) and builds both images |
| S00-5 | Only permissively licensed runtime dependencies (blueprint constraint C4) |

**Design decisions**

- **src layout + one package**: prevents accidental imports from the working directory; the wheel is what runs in Docker.
- **Ports and adapters** for everything external (LLM, embeddings, reranker, storage): the core never imports a vendor SDK.
- **Sync stack** (FastAPI sync endpoints, psycopg3 pool, httpx sync): fewer failure modes than mixing async with
  CPU-bound parsing; concurrency comes from the worker thread pool and from Ollama/vLLM batching.
- **Config via pydantic-settings**: validated at start-up, typed everywhere.

## 2. Plan

1. `pyproject.toml` with pinned lower bounds and optional extras (`rerank`, `dev`).
2. `config.py`, `logging_setup.py`.
3. `Dockerfile` (tesseract included, LibreOffice and reranker as build args), `docker-compose.yml`, `ui/Dockerfile`.
4. `Makefile`, `.env.example`, `.gitignore`.
5. `.github/workflows/ci.yml`.
