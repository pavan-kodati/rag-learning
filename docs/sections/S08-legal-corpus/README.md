# S08 · Legal corpus (separate, labelled, verifiable)

## 1. Spec

**Goal:** let the lawyer ask "what does the law say about X" for the issues in the matter, from a **separate** schema, never mixed with matter facts,
and never presented as verified unless a human verified it.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S08-1 | Own schema/tables; load from versioned YAML; idempotent reload |
| S08-2 | Each source/passage has a verification status; everything shipped is **UNVERIFIED** until a verifier name+date is recorded |
| S08-3 | Search by question and issue tags (dense + tags); works from tags alone; empty corpus returns empty, not an error |
| S08-4 | Malformed corpus files are rejected before anything is written |
| S08-5 | Issue tags follow the disputed slots of the matter (e.g. a disputed termination → termination authorities) |

## 2. Plan

`corpus/loader.py` (validate → write → embed) → `corpus/search.py` → API route → tests.

## 3. Execution report

**Built:** `corpus/{loader,search}.py`, `data/corpus/seed.yaml` (12 sources, 27 passages: Contract Act, Specific Relief Act, CPC, Commercial Courts Act, Arbitration Act, General Clauses Act, and six well-known judgments, e.g. Kailash Nath v DDA, ONGC v Saw Pipes).

**Verified:** `tests/integration/test_corpus.py` → 16 passed (seed loads, embeds and is flagged unverified; reload idempotent; a verifier marks it verified;
malformed files rejected before any write; missing file; ranking by question+tags; tags-only search; empty corpus; list of known authorities; issue tags from disputed slots).

> **Important, honest limitation:** the seed passages are **my paraphrases from memory, not the official text**, and may contain errors.
> They exist so the feature can be tested end to end. They are shown with an UNVERIFIED badge. **Do not rely on them for legal work.**
> Replace them with text you or a lawyer verified (India Code / court websites) and record the verifier in the YAML.
