# S09 · API (FastAPI, enterprise hardening)

## 1. Spec

**Goal:** a versioned REST API (`/api/v1`) that exposes every capability the UI and any integration needs, with the hardening an enterprise reviewer expects.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S09-1 | Resources: matters, parties, batches, documents (PDF, page text/image, highlights), facts + history, views (gist, chronology, claims, directions, evidence), ask, brief, legal search, review queue, traces, audit |
| S09-2 | Errors are RFC 7807 `application/problem+json` with the request id; unhandled errors never leak internals |
| S09-3 | Request id generated/echoed; security headers; `Cache-Control: no-store` on API data |
| S09-4 | Optional JWT auth, roles viewer < analyst < admin, login rate limit, per-client API rate limit (429 + `Retry-After`) |
| S09-5 | Upload reports per-file outcomes (accepted / duplicate / rejected with reason) with correct status codes |
| S09-6 | Health (`/healthz/live`, `/healthz`), Prometheus `/metrics`, OpenAPI docs |
| S09-7 | Matter/party/batch/upload/commit/retry, questions, briefs and review actions are written to `audit_log` (admin-only `GET /audit`) |

## 2. Plan

`api/main.py` (app factory, middleware, UI mount) → `security.py`, `metrics.py`, `deps.py` → routes `system, auth, matters, documents, query, review` → tests via TestClient on the real DB.

## 3. Execution report

**Built:** `api/{main,security,deps,metrics}.py`, `api/routes/*.py`.

**Verified:** `tests/integration/test_api.py` → 33 passed, including: problem+json with request id; unhandled errors do not leak; field-specific validation messages;
matter CRUD and conflicts; one open batch at a time; per-file upload outcomes and status codes; closed/unknown batch; failed-document retry; views, claims filter, ask validation,
brief JSON/Markdown and empty-matter error; document endpoints (PDF, text, image, highlight rectangles); review flow over HTTP; auth off by default, login/logout, bad credentials,
tampered/expired/foreign tokens, role enforcement, login and API rate limits; image tokens via query for `<img>`; matter deletion removes stored files.

**Decisions:** sync endpoints (see S00); auth is **off by default** so local testing needs no login — set `AUTH_ENABLED=true`, `JWT_SECRET`, `AUTH_USERS="user:password:role,..."` for anything shared.
The in-process rate limiter is per replica; use a gateway limiter when running several replicas (see `docs/DEPLOYMENT_PLAN.md`).
