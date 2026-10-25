# S02 · Data layer

## 1. Spec

**Goal:** one PostgreSQL 16 + pgvector database holding evidence, knowledge and time layers (blueprint ADR-01, §6, §15),
a transactional job queue (ADR-02), an audit trail, and a small repository layer the rest of the code uses.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S02-1 | Migrations are versioned, ordered, idempotent, checksummed and safe under concurrent start-up (advisory lock) |
| S02-2 | Schema implements blueprint §15 (+ the additions listed below); integrity rules enforced **by the database** (CHECKs, FKs) |
| S02-3 | Facts are never deleted; `ended_in_batch_seq`/`state` invariant is enforced by a CHECK |
| S02-4 | A job can be claimed by exactly one worker (`FOR UPDATE SKIP LOCKED`); stuck jobs are re-queued; attempts are capped |
| S02-5 | Duplicate upload (same SHA-256 in a matter) is rejected by a unique constraint and recorded for the batch report |
| S02-6 | Every repository function takes a connection, so transaction boundaries belong to the caller (needed for "fact + link + ledger in one transaction") |
| S02-7 | Negative tests: FK violations, CHECK violations, double claim, stale-lock recovery, cross-matter isolation |

**Additions to the blueprint schema (with reason)**

| Change | Reason |
| ------ | ------ |
| `documents.storage_uri` (was `s3_uri`), `pdf_uri`, `original_filename`, `mime_type` | local-disk storage by default, S3-compatible later; every document has a PDF for citations |
| `documents.contract_id`, `contract_aliases`, `amends_contract_id`, `defined_terms` | the contract registry (§8.2) is derived from documents |
| `document_pages.page_width/height` | bboxes are stored in PDF points; the viewer needs the page size to scale them |
| `document_extractions` | stores normalised extraction candidates + dropped items (with reasons) between EXTRACT and RECONCILE |
| `batch_duplicates` | duplicates are listed in the What-Changed report (§8.5 rule 4) |
| `ingestion_jobs.matter_id/batch_seq`, nullable `document_id` | RECONCILE is a batch-level job (documents must be reconciled in document-date order) |
| `matter_fact_assertions.subject_type`, `derived` | fast filtering; marks facts computed by code (R5) |
| `audit_log` | enterprise requirement: who did what, when |
| `query_traces.answer`, `actor` | replayable answers |

## 2. Plan

1. `db/migrations/001_init.sql` (blueprint DDL + additions), `002_audit.sql`.
2. `db/migrate.py` runner (checksums, advisory lock) and `db/pool.py` (psycopg pool, pgvector adapter).
3. Repositories: `matters`, `documents`, `chunks`, `facts`, `jobs`, `traces`, `audit`.
4. Test fixtures: throw-away schema per test session; table truncation per test.
5. Integration tests incl. negative cases.

## 3. Execution report

**Built:** `db/migrations/{001_init,002_audit}.sql`, `db/{pool,migrate,matters,documents,chunks,facts,jobs,traces,audit}.py`.

**Verified (real PostgreSQL 16 + pgvector 0.8):** `tests/integration/test_db_layer.py` → 50 passed.

| Area | Evidence (test names) |
| ---- | --------------------- |
| Migrations | `test_migrations_idempotent_and_checksummed` |
| Matters / parties | create/get/validation, duplicate matter number → conflict, unknown matter → NotFound, party resolution incl. ambiguous role words |
| Batches | `test_batches_are_sequential_and_exclusive`, status validation, upload to a closed/missing batch fails |
| Duplicates | `test_duplicate_upload_is_rejected_and_recorded`, same file allowed in a different matter, a FAILED document may be uploaded again but a good one cannot |
| Database-enforced invariants | a fact cannot end before it was learned; state/category vocabularies; a link has exactly one target; chunk page range; deleting a matter cascades |
| Job queue | exclusive and ordered claim, two workers never claim the same job, idempotent enqueue, RECONCILE waits for the batch's other jobs, retry then permanent failure, non-retryable failure is final, stale RUNNING job requeued/failed |
| Audit | `test_audit_log_roundtrip` |

Vector search and the as-of fact views are exercised in S05/S06 tests (`test_reconcile_edges.py`, `test_grounding.py`, `test_corpus.py`).

**Deviations:** the additions in the table above (all additive; no blueprint column removed). Every repository function takes the
connection, so the caller owns the transaction (needed for "all or nothing" batch commits).
