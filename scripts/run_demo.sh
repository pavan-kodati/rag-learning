#!/usr/bin/env bash
# One-command local demo: API + UI on http://localhost:8000, recorded model output (no model download, no cost).
set -euo pipefail
cd "$(dirname "$0")/.."
export DATABASE_URL="${DATABASE_URL:-postgresql://lw:lw@localhost:5432/legal_workspace}"
export LLM_PROVIDER="${LLM_PROVIDER:-fixture}" EMBEDDER="${EMBEDDER:-hashing}" EMBEDDED_WORKER=true
[ -d ui/dist ] || (cd ui && npm install --no-audit --no-fund && npm run build)
exec .venv/bin/python -m legal_workspace.api.main
