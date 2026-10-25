# S11 · Synthetic matters and evaluation harness

## 1. Spec

**Goal:** you have no confidential case files, so generate realistic synthetic matters with planted traps and a gold answer key, and make "does it work?" a number (blueprint §18).

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S11-1 | Deterministic generator → realistic PDFs (digital and scanned), e-mails, orders, pleadings, invoices, in batches |
| S11-2 | Gold data per matter: golden questions, planted changes (supersession, narrowing, dispute, late-arrival, unsigned, ambiguous…), retrieval probes |
| S11-3 | Four matters: M1, M2 (blueprint worked example), M3, and **M4 — held-out style, with no recorded model output** to expose over-fitting |
| S11-4 | `lw-eval` replays batch by batch and scores: answer correctness, citation precision, planted-change detection, recall@8, unanswerable-not-found, duplicate facts, ingestion speed — with pass/fail targets |
| S11-5 | Works with any model: fixture mode tests the pipeline; Ollama/vLLM mode measures the model |

## 2. Plan

`synthetic/spec.py` (DSL) → `generate.py` (reportlab rendering, manifest, golden/planted/probes YAML, fixtures) → `matters/m1..m4.py` → `eval/{replay,checker,runner}.py` → report (Markdown + JSON in `eval_reports/`).

## 3. Execution report

**Built:** `synthetic/*`, `eval/*`, `data/synthetic/M1..M4`, `data/fixtures/M1..M4.json`.

**Verified (real run, fixture mode, `lw-eval --matters M1 M2 M3`):**

| Metric | Result | Target |
| ------ | ------ | ------ |
| answer correctness | 37/37 questions (100%) | ≥ 90% |
| citation precision | 100% | ≥ 95% |
| planted changes detected | 23/23 (M1 9, M2 7, M3 7) | ≥ 90% |
| recall@8 (labelled probes) | 100% | ≥ 85% |
| unanswerable → "not found" | 100% | 100% |
| duplicate facts after re-upload | 0 | 0 |
| ingestion time per 20 pages | ~1.3 s (no real model) | ≤ 120 s |

The first eval run scored 34/37 and found three real defects, all fixed and covered by tests: the checker ignored numeric values, evidence-only directions leaked into the direction list, and
the first recall metric was measured on questions rather than labelled probes.

**Read these numbers honestly**

1. In fixture mode the "model" replays the output the generator recorded, so this proves the **pipeline, rules, grounding and UI**, not the **extraction accuracy of a real LLM**. That is why M4 exists with no recording: run it with Ollama to get a model-quality number (`LLM_PROVIDER=ollama lw-eval --matters M4`). Expect it to fail some items on a small local model; that is the signal the harness is meant to give.
2. M4 was written by the same author as the pipeline, so it is not truly independent. Have a lawyer write one matter from a real (redacted) file.
3. Scanned-document OCR output differs between machines; fixtures key those by file name as well as text hash.
4. Do not run a live server with an embedded worker on the same database while evaluating (its worker steals eval jobs).
