#!/usr/bin/env bash
# One entry point for running Legal Workspace on a single Linux server (e.g. an AWS EC2 instance).
#   deploy/deploy.sh up            build and start everything (first deploy, or after editing deploy/.env.prod)
#   deploy/deploy.sh update [ref]  git fetch + checkout <ref> (default: current branch, fast-forward) + rebuild + restart
#   deploy/deploy.sh pull-models   download the Ollama models named in deploy/.env.prod (once; ~9 GB)
#   deploy/deploy.sh load-demo     load the built-in synthetic matter M2 so you can click around (demo data only!)
#   deploy/deploy.sh status        containers, health, GPU
#   deploy/deploy.sh logs [svc]    follow logs (api, worker, db, ollama, proxy, ui)
#   deploy/deploy.sh backup [dir]  database dump + stored files (default dir: ~/backups)
#   deploy/deploy.sh down          stop everything (data is kept)
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=deploy/.env.prod
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE. Run: cp deploy/.env.prod.example $ENV_FILE  and edit it." >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a

export IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
FILES=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)
PROFILES=()
if [ "${LLM_PROVIDER:-ollama}" = "ollama" ] || [ "${EMBEDDER:-ollama}" = "ollama" ]; then PROFILES=(--profile with-ollama); fi
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then FILES+=(-f deploy/docker-compose.gpu.yml); fi
dc() { docker compose "${FILES[@]}" --env-file "$ENV_FILE" "${PROFILES[@]}" "$@"; }

cmd="${1:-help}"; shift || true
case "$cmd" in
  up)
    dc up -d --build
    echo "Started. Check: deploy/deploy.sh status   (first time: deploy/deploy.sh pull-models)" ;;
  update)
    git fetch --all --prune
    if [ -n "${1:-}" ]; then
      git checkout "$1"
      if git show-ref --verify --quiet "refs/remotes/origin/$1"; then git merge --ff-only "origin/$1"; fi   # a branch: take its latest commit
    else
      git pull --ff-only
    fi
    IMAGE_TAG="$(git rev-parse --short HEAD)"; export IMAGE_TAG
    dc up -d --build ;;
  pull-models)
    for m in "${LLM_MAIN_MODEL:-qwen3:8b}" "${LLM_FAST_MODEL:-qwen3:4b}" "${EMBEDDING_MODEL:-bge-m3}"; do
      echo "== ollama pull $m"; dc exec -T ollama ollama pull "$m"
    done ;;
  load-demo)
    if [ "${LLM_PROVIDER:-ollama}" != "fixture" ] || [ "${EMBEDDER:-ollama}" != "hashing" ]; then
      echo "load-demo only works in demo mode: set LLM_PROVIDER=fixture and EMBEDDER=hashing in $ENV_FILE, run 'up', then retry." >&2
      echo "(The demo matter is embedded with the offline hashing embedder; searching it with bge-m3 would give poor results.)" >&2
      exit 1
    fi
    dc stop worker                       # the demo loader runs its own worker; do not let two compete
    dc exec -T api lw-eval --matters M2 --keep --no-fail --report-dir /tmp/eval
    dc start worker ;;
  status)
    dc ps
    echo "--- health"; dc exec -T api curl -fsS http://localhost:8000/api/v1/healthz || echo "(API not answering yet)"; echo
    if command -v nvidia-smi >/dev/null 2>&1; then echo "--- gpu"; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv; fi ;;
  logs)    dc logs -f --tail=100 "$@" ;;
  backup)  deploy/backup.sh "${1:-$HOME/backups}" ;;
  down)    dc down ;;
  *)       sed -n '2,10p' "$0" ;;
esac
