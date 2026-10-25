# S06 · Retrieval (hybrid search, router, eight plans)

## 1. Spec

**Goal:** given a question, decide *which kind of question it is*, then fetch exactly the evidence that kind needs —
structured facts first, passages second — as of a chosen batch.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S06-1 | Router: deterministic rules first, fast model second (only when no rule fires), default plan last; a broken model never breaks routing |
| S06-2 | Eight plans: FACTUAL, CURRENT_POSITION, CHRONOLOGY, DIRECTIONS, CLAIMS/EVIDENCE, CHANGES, LEGAL_RESEARCH, OUT_OF_SCOPE; multi-intent questions run at most three |
| S06-3 | Hybrid passage search = dense (pgvector HNSW) + full-text, fused with Reciprocal Rank Fusion; optional cross-encoder rerank; small-to-big context |
| S06-4 | Every plan honours `as_of_batch_seq` and the matter boundary |
| S06-5 | Every retrieved item carries what grounding needs: ids, page, quote, state (CURRENT / SUPERSEDED / DISPUTED), source document |

## 2. Plan

`retrieval/types.py` (Intent, Evidence, Plan result) → `hybrid.py` (search + RRF) → `router.py` → `plans.py` (one function per intent) → tests.

## 3. Execution report

**Built:** `retrieval/{types,hybrid,router,plans}.py`.

**Verified:** `tests/unit/test_verify_router.py` (router tests: rules route to the expected plan; out-of-scope wins over everything; ≤3 intents;
unmatched → fast model → default; router survives a broken model; hint overrides rules and a bad hint is ignored) and `tests/integration/test_grounding.py`
(`search_finds_the_right_chunk_for_natural_language_questions`, `search_respects_the_as_of_batch_and_the_matter`, `intent_hint_forces_a_plan`).
Retrieval quality is measured by labelled probes in S11 (**recall@8 = 100%** on M1–M3 in fixture mode).

**Caveat:** probes use the offline hashing embedder, which is lexical. With `bge-m3` recall should be the same or better, but that is unmeasured here.
Reranking is off by default (`RERANKER=none`), on purpose: it costs ~2 GB and is only worth turning on if recall@8 on your matters is below target.
