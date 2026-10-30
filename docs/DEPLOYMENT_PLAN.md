# Deployment plan (DevOps)

> **Want click-by-click AWS instructions?** See [`AWS_DEPLOYMENT_GUIDE.md`](AWS_DEPLOYMENT_GUIDE.md). This page is the overview; use `deploy/deploy.sh` for everything on a server.

Everything below uses open-source software only. **Status legend:** ✅ run and verified in the build sandbox · 🟡 written but not run (no Docker daemon / cloud there) — review before first use.

## 0. Environments

| Stage | Where | How | Models | Status |
| ----- | ----- | --- | ------ | ------ |
| **Local, no models** (try it in 5 min) | your laptop | `make demo` / `scripts/run_demo.sh` | recorded outputs (`fixture`) + hashing embedder | ✅ |
| **Local, real models** | your laptop | Postgres via compose + `ollama` + `lw-api` | `qwen3:8b`/`4b`, `bge-m3` | 🟡 (code paths mocked/tested; not run against Ollama here) |
| **Local, containers** | your laptop | `docker compose up --build` | Ollama on host (default) or `--profile with-ollama` | 🟡 |
| **Single VM** (pilot, one firm) | any Linux VM | `deploy/docker-compose.prod.yml` + Caddy (auto-TLS) | Ollama/vLLM on the VM or a GPU host | 🟡 |
| **Kubernetes** (multi-team) | any cluster | `deploy/k8s/legal-workspace.yaml` (outline) | vLLM on GPU nodes | 🟡 outline |

## 1. Architecture at runtime

```
 browser ──HTTPS──► Caddy / Ingress ──► ui (nginx, static)
                         │
                         └──/api──► api (FastAPI, N replicas, stateless)
                                      │            │
                                      │            └─► model server (Ollama | vLLM)  ◄─┐
                                      ▼                                               │
                              PostgreSQL 16 + pgvector  ◄── worker (M replicas) ──────┘
                              (facts, chunks, vectors, job queue)      │
                                      shared file storage ◄────────────┘ (originals, PDFs, page images)
```

* The **job queue is PostgreSQL** (`FOR UPDATE SKIP LOCKED`): no Redis/Kafka to run. Scale ingestion by adding worker replicas.
* The API is stateless except for an in-process rate limiter (per replica) and the uploaded-files directory.
* **Shared storage:** the `api` and `worker` must see the same `STORAGE_DIR` (a Docker volume on one VM; ReadWriteMany volume on Kubernetes). An S3-compatible storage adapter (MinIO/Ceph) is the next step for multi-node (listed as a gap below).

## 2. Local run, step by step

**A. No models (demo mode)**
```bash
make setup            # venv + Python deps + ui deps
docker compose up -d db   # or: any PostgreSQL 16 with the pgvector extension
make demo             # migrates, loads the corpus, replays matter M2 and starts nothing else
scripts/run_demo.sh   # API + UI on http://localhost:8000   (builds ui/dist if missing)
```
**B. Real open-source models (Ollama)**
```bash
scripts/pull_models.sh            # ~9 GB; "scripts/pull_models.sh small" for ≤ 8 GB RAM (qwen3:4b main)
cp .env.example .env              # LLM_PROVIDER=ollama, EMBEDDER=ollama (defaults)
docker compose up -d db && make api    # http://localhost:8000
lw-eval --matters M1 M2 M3 M4     # your real accuracy numbers, with your models, on your hardware
```
Hardware guide: 16 GB RAM laptop runs `qwen3:4b` comfortably and `qwen3:8b` slowly on CPU; Apple Silicon or an 8 GB+ NVIDIA GPU makes `qwen3:8b` practical.

## 3. Single-VM production (pilot)

1. VM: 4 vCPU / 16 GB (CPU models) or a GPU VM; Docker + Compose ≥ 2.24 (the overlay uses `!reset`). Open ports 80/443 only.
2. `git clone` to `/opt/legal-workspace`; `cp deploy/.env.prod.example deploy/.env.prod` and fill in secrets (long random `JWT_SECRET`, `POSTGRES_PASSWORD`, real `AUTH_USERS`).
3. `deploy/deploy.sh up` (builds on the server; no registry login needed), then `deploy/deploy.sh pull-models`. GPU hosts are detected automatically (`deploy/docker-compose.gpu.yml`).
4. Point DNS `PUBLIC_HOST` at the VM; Caddy obtains the certificate automatically.
5. Backups: cron `deploy/backup.sh /backups` nightly (DB dump + stored files, 14-day retention). **Practise a restore** before relying on it.

## 4. CI/CD

| Stage | What | Where |
| ----- | ---- | ----- |
| Pull request | ruff, ruff-format, mypy, pytest (+ coverage) against a pgvector service; UI lint, typecheck, vitest, build | `.github/workflows/ci.yml` ✅ commands run locally; workflow itself 🟡 until it runs on GitHub |
| main | build and push `api` and `ui` images to GHCR tagged with the commit SHA | `ci.yml` job `images` 🟡 |
| Release | manual `workflow_dispatch`: SSH to the VM and run `deploy/deploy.sh update <ref>` (builds on the server), then `status`; protect with a GitHub *environment* approval | `.github/workflows/cd.yml` 🟡 |
| Rollback | re-run CD with the previous SHA. Migrations are forward-only and additive, so the old image keeps working against the new schema for one release | — |

Recommended additions once the pilot is live: Dependabot, `pip-audit`/`npm audit` and Trivy image scan in CI, a nightly `lw-eval` against a staging model server with the result posted to the PR.

## 5. Observability

* **Logs:** JSON (`LOG_JSON=true`) with the request id on every line; ship with Promtail/Vector → Loki.
* **Metrics:** `GET /metrics` (Prometheus; deliberately outside `/api` so the public proxy does not route it — scrape it on the internal network): `lw_http_requests_total`, `lw_unverified_sentences_total` (sentences dropped by citation verification), `lw_http_request_seconds`, `lw_answers_total{mode}` (`mode=extractive` = the model was unavailable or unusable and the model-free fallback answered), `lw_uploads_total{result}`, `lw_jobs{status}`.
* **Suggested alerts:** `lw_jobs{status="FAILED"}` rising; `lw_answers_total{mode="extractive"}` rate > 0 for 10 min (model server down); 5xx ratio > 1%; `/healthz` failing (database or model unreachable); disk > 80% on the storage volume.
* **Audit trail:** `GET /api/v1/audit` (admin) and the `audit_log` table; keep a copy in your SIEM if required.
* **Answer replay:** every answer has a stored trace (`/api/v1/traces/{id}`) — the first thing to open when a lawyer disputes an answer.

## 6. Security checklist

| Item | State |
| ---- | ----- |
| TLS | via Caddy/Ingress 🟡 |
| AuthN/AuthZ | JWT, roles viewer < analyst < admin ✅ tested; **default is off for local use** — turn on for any shared deployment |
| Secrets | env / Secret objects; never in the image; `.env.prod` git-ignored |
| Brute force / abuse | login limiter + per-IP API limiter ✅ (per replica; add gateway limits for multi-replica) |
| Uploads | content sniffing (not extension), size/page limits, filename sanitising, stored outside web root ✅ tested |
| Data residency | all processing local; **no document text leaves your network** (no external LLM API) |
| Prompt injection | documents are data; every output sentence is verified in code ✅ tested |
| Containers | non-root user in the API image; add read-only root FS and network policies in Kubernetes |
| Multi-tenancy | **not implemented**: one deployment = one trust boundary (matter isolation exists, tenant isolation/row-level security does not) |
| Data protection | encrypt disks/backups at rest at the infrastructure layer; retention/erasure beyond "delete matter" is not implemented |

## 7. GPU / scale-out option (still open source)

Switch `LLM_PROVIDER=openai_compat` and point `OPENAI_BASE_URL` at **vLLM** (`vllm serve Qwen/Qwen3-8B` on a 24 GB GPU; Qwen3-4B for the fast role). Run **TEI** (text-embeddings-inference) for `bge-m3` if you want to move embeddings off Ollama
(requires a small embedder adapter; today embeddings use Ollama or the hashing fallback). No application code changes for the chat models.

## 8. Known gaps for a regulated enterprise

1. S3-compatible storage adapter (needed for stateless multi-node without RWX volumes).
2. Tenant isolation / row-level security, SSO (OIDC) — current auth is a built-in user list with JWT.
3. Legal corpus is a paraphrased **seed**; load verified official texts before using the Legal tab.
4. Real-model accuracy has not been measured by me — run `lw-eval` (M1–M4) on your hardware and decide with the numbers.
5. Distributed rate limiting and Redis-free HA for Postgres (use a managed Postgres or Patroni/CloudNativePG).
