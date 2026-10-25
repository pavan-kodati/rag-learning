#!/usr/bin/env bash
# Download the open-source models used by the default (non-demo) configuration into a local Ollama.
# Usage: scripts/pull_models.sh [small]     ("small" = 4B main model for laptops with <= 8 GB RAM)
set -euo pipefail
command -v ollama >/dev/null || { echo "Ollama is not installed: https://ollama.com/download" >&2; exit 1; }
MAIN="qwen3:8b"; [ "${1:-}" = "small" ] && MAIN="qwen3:4b"
for m in "$MAIN" qwen3:4b bge-m3; do
  echo "== ollama pull $m"; ollama pull "$m"
done
echo "Done. Put these in .env:  LLM_MAIN_MODEL=$MAIN  LLM_FAST_MODEL=qwen3:4b  EMBEDDING_MODEL=bge-m3"
