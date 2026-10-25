.PHONY: help setup db migrate corpus synth api worker ui test lint typecheck eval demo up down clean
PY := .venv/bin/python
help:            ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ -/'
setup:           ## create venv and install everything
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	cd ui && npm install && npm run build
db:              ## start PostgreSQL + pgvector in Docker
	docker compose up -d db
migrate:         ## apply database migrations
	$(PY) -m legal_workspace.db.migrate
corpus:          ## load the starter legal corpus
	$(PY) -m legal_workspace.corpus.loader
synth:           ## (re)generate synthetic matters (PDFs + gold data)
	$(PY) -m legal_workspace.synthetic.generate
api:             ## run API (+ embedded worker) on :8000
	$(PY) -m legal_workspace.api.main
worker:          ## run a stand-alone ingestion worker
	$(PY) -m legal_workspace.worker
ui:              ## run the UI dev server on :5173
	cd ui && npm run dev
test:            ## unit + integration tests (needs the database)
	$(PY) -m pytest
lint:            ## ruff
	.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
typecheck:       ## mypy
	.venv/bin/mypy src
eval:            ## replay synthetic matters and score against the golden set
	$(PY) -m legal_workspace.eval.runner --matters M1 M2 M3
demo:            ## no model needed: load matter M2 (batches 1+2) into the database, then serve API + UI on :8000
	LLM_PROVIDER=fixture EMBEDDER=hashing $(PY) -m legal_workspace.eval.runner --matters M2 --keep
	scripts/run_demo.sh
up:              ## whole stack in Docker
	docker compose up --build
down:
	docker compose down
clean:
	rm -rf storage .pytest_cache .mypy_cache .ruff_cache
