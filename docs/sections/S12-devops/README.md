# S12 · DevOps and deployment plan

## 1. Spec

**Goal:** a path from "runs on my laptop for free" to a production-shaped deployment, all open source, with CI quality gates, health/metrics/logging, backups and a rollback story.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S12-1 | One-command local demo with no model and no cost |
| S12-2 | Containerised stack (db, api, worker, ui, optional Ollama) |
| S12-3 | CI gates: lint, format, types, backend tests with coverage, UI lint/types/tests/build |
| S12-4 | Production overlay: TLS proxy, no public DB, secrets from env, restart policies, worker scale-out |
| S12-5 | Kubernetes outline, backup/restore script, health probes, Prometheus metrics, JSON logs |
| S12-6 | Written deployment plan incl. security checklist, rollback, GPU/vLLM option and known gaps |

## 2. Plan

`Dockerfile`, `docker-compose.yml`, `ui/Dockerfile` + `nginx.conf` → `.github/workflows/{ci,cd}.yml` → `deploy/{docker-compose.prod.yml,Caddyfile,.env.prod.example,backup.sh,k8s/}` → `scripts/{run_demo,pull_models}.sh` → `docs/DEPLOYMENT_PLAN.md`.

## 3. Execution report

**Verified in the sandbox (real runs):**

- `make lint` → ruff check + format clean; `mypy src` → *no issues in 88 files*.
- Every CI command passes locally: `pytest` (591 passed, 88% line coverage), `npm run lint/typecheck/test/build` (44 UI tests).
- The demo path (`scripts/run_demo.sh` → API serving `ui/dist`) and the browser E2E were run against a real PostgreSQL.
- YAML of the k8s outline and CD workflow parses; the compose overlay uses Compose-specific `!reset` tags (needs Compose ≥ 2.24).

**NOT verified (be aware):** the build sandbox has **no Docker daemon and no cloud account**, so `Dockerfile`, `docker-compose*.yml`, Caddy, the Kubernetes manifests, the GitHub workflows (until they run on GitHub) and `backup.sh` were written carefully but **never executed**. Expect to fix small things on first run; the first-run checklist is in `docs/DEPLOYMENT_PLAN.md`.
Also unverified: a real Ollama/vLLM server, GPU performance.
