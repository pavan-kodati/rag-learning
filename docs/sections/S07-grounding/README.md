# S07 · Grounding and answers (generation, citation verification, hearing brief)

## 1. Spec

**Goal:** every sentence the user sees is either verified against stored evidence or not shown. A model may *word* an answer; code decides whether it is allowed.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S07-1 | Verification in code: cited ids were retrieved; the quote is on the cited page (whitespace/quote/dash-normalised); numbers and dates in the sentence appear in the evidence; a sentence resting only on SUPERSEDED facts is rejected unless it says so |
| S07-2 | Rejected sentences are dropped and logged in the trace, not shown |
| S07-3 | Model outage or unusable output → **extractive fallback**: the same evidence rendered without a model, with a note saying so |
| S07-4 | The model may decline: "not found", listing what is missing; unanswerable questions invent nothing |
| S07-5 | Prompt injection inside a document cannot alter the answering rules (documents are data, delimited, and the output is verified anyway) |
| S07-6 | Every answer stores a trace (question, plan, evidence, answer, timings, model versions) for replay |
| S07-7 | Hearing brief: eight sections, every line cited, JSON and Markdown |
| S07-8 | Legal citations must exist in the corpus; the UI shows the UNVERIFIED badge |

## 2. Plan

`grounding/verify.py` → `factual.py` (prompt + extractive fallback) → `narrative.py` (chronology/changes prose) → `answer.py` (`ask`) → `brief.py` → tests.

## 3. Execution report

**Built:** `grounding/{verify,factual,narrative,answer,brief}.py`.

**Verified:**

| Test file | Tests | Covers |
| --------- | ----- | ------ |
| `tests/unit/test_verify_router.py` | 41 | numeric tokens, quote normalisation, grounded vs ungrounded sentences, numbers from attached facts, superseded-only rejection, statement and law citations |
| `tests/integration/test_grounding.py` | 17 | grounded answer returned; fabricated/unsupported sentences dropped and logged; superseded value cannot be presented as current; **prompt injection**; **model outage → extractive**; unusable output → extractive; model declines; garbage output shapes; narrative inventing numbers is dropped; question validation; empty-matter answer |
| `tests/e2e/test_m2_answers.py` | 13 | all golden questions for both rounds; every returned sentence verified and cited; superseded never shown as current; as-of answers from the earlier position; computed deadlines/overdue; legal research with UNVERIFIED badge; out-of-scope declined; unanswerable → not found; trace stored; brief has all sections, all lines cited, Markdown; brief before any batch refused |

**Deviations / decisions:** the extractive fallback weights rare words over generic ones and cuts at 0.8× the best score (tuned after the golden set exposed noisy matches);
synonyms are expanded on the question only. Narrative sentences get ids `N-i` so traces are complete.
