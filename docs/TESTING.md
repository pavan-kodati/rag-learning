# Testing guide

## Layers

| Layer | Where | Needs | What it proves |
| ----- | ----- | ----- | -------------- |
| Unit (402 tests) | `tests/unit` | nothing | normalisers, slots/keys, R0–R9 rules, deadlines, subjects, validation/sniffing/conversion, chunking, classification, extraction validation, citation verification, router, model adapters (HTTP mocked), resilience |
| Integration (168) | `tests/integration` | PostgreSQL + pgvector | DB constraints and queue, ingestion service and worker, reconcile edge cases, review actions, grounding with scripted models, corpus, full HTTP API incl. auth/rate limits |
| End-to-end (21) | `tests/e2e` | PostgreSQL | matter M2 (the blueprint's worked example) from PDFs to answers, as-of views, deadlines, brief |
| UI (44) | `ui/src/__tests__` | Node | API client, formatting, citations, viewer, forms, views (loading/empty/error) |
| Browser E2E | `ui/e2e/flow.cjs` | API + DB + Chromium | the whole lawyer workflow through the real UI; produces screenshots |
| Evaluation | `lw-eval` | PostgreSQL (+ model) | accuracy numbers against the gold answer key (see S11) |

Total backend: **591 passing, 88 % line coverage**; ruff and mypy clean.

## Running

```bash
docker compose up -d db                 # or any local PostgreSQL 16 with pgvector
docker compose exec db createdb -U lw legal_workspace_test        # a separate, throw-away database
export TEST_DATABASE_URL=postgresql://lw:lw@localhost:5432/legal_workspace_test
# WARNING: the suite DROPs and recreates the `public` schema of TEST_DATABASE_URL. Never point it at data you care about.
# Without a reachable database the database-backed tests are skipped (not failed): check the summary line.
make test                               # == pytest  (add:  --cov=legal_workspace --cov-report=term-missing)
make lint typecheck
cd ui && npm test && npm run lint && npm run typecheck
node ui/e2e/flow.cjs                    # needs the demo server on :8000 (scripts/run_demo.sh) and Playwright
LLM_PROVIDER=fixture EMBEDDER=hashing lw-eval --matters M1 M2 M3        # pipeline score
LLM_PROVIDER=ollama lw-eval --matters M1 M2 M3 M4                        # real-model score (your hardware)
```

Select subsets with markers/paths: `pytest tests/unit`, `pytest -k reconcile`, `pytest tests/e2e`.

## Negative-path map: upload → retrieval

| Step | Failure injected | Expected, and tested |
| ---- | ---------------- | -------------------- |
| Upload | executable / wrong extension / empty / oversize / hostile filename / unknown or closed batch / duplicate | rejected per file with a reason, nothing stored, other files unaffected |
| Convert / parse | corrupt PDF, encrypted PDF, blank page, scan without OCR, empty DOCX, HTML-only e-mail | that document FAILED with a readable message (or flagged), rest of batch continues |
| Classify | ambiguous title, low confidence | demoted to CORRESPONDENCE, flagged for review |
| Extract | model down, invalid JSON, hallucinated quote, disallowed slot | retries with backoff → document fails cleanly; items dropped with stored reason |
| Reconcile | late/older document, unsigned amendment, equal-authority conflict, ambiguous contract reference, overpayment, undated order | rule R0–R9 outcome or review queue; idempotent; ledger row written |
| Retrieve | no committed batch, as-of out of range, unknown matter, empty question, empty corpus | helpful "not found"/validation error, never a crash |
| Answer | model down / unusable output / fabricated sentence / superseded-only / injected instructions / unanswerable | extractive fallback, sentence dropped and logged, "not found", never an invented answer |
| API | bad token, expired token, wrong role, login flood, request flood, unhandled exception | 401/403/429 or problem+json with request id; no internals leaked |

## Known gaps in the tests

* Real LLM/embedding servers are never contacted (HTTP is mocked); `lw-eval` with Ollama is the check.
* No load/soak tests; no formal security scan; no cross-browser or accessibility audit.
* Docker/Kubernetes artefacts are not exercised by CI until you run it on GitHub.
