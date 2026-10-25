# S05 · Matter memory (reconcile, ledger, directions, events, review)

## 1. Spec

**Goal:** after a batch is committed, update the matter's *memory* — the set of current facts, what they replaced, and why —
using only the S01 rules. The memory must answer "what is true now", "what was true at batch N" and "what changed in this batch".

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S05-1 | Every candidate fact gets a key, a decision (R0–R9) and a ledger row in `fact_change_log`; nothing is overwritten in place |
| S05-2 | Documents in a batch reconcile in **document-date order**, not upload order; reconcile is idempotent |
| S05-3 | Late-arriving older documents never override newer terms ("born superseded") |
| S05-4 | Unsigned/one-sided documents, internal notes and low-confidence documents are evidence only |
| S05-5 | Outstanding amount is **derived by code** = invoice − recorded payments; overpayment clamps to 0 and is flagged (R5) |
| S05-6 | Court directions carry computed due dates; a later filing by the right party discharges the direction (late is still COMPLIED, marked late) |
| S05-7 | Anything ambiguous goes to the **review queue**; a human action writes a MANUAL ledger row; confirm/dispute/evidence-only/supersede/withdraw/correct |
| S05-8 | As-of views reproduce each committed batch exactly; What-Changed report lists new, superseded, narrowed, disputed, duplicates, failures |
| S05-9 | Matters are isolated: identical keys in two matters never mix |

## 2. Plan

1. `memory/resolve.py`: candidate → `NewFact` (subject resolution, party mapping, authority).
2. `memory/reconcile.py`: `apply_fact` (decide → persist state/links/ledger), `recompute_outstanding`, `reconcile_batch` (advisory lock, date order).
3. `memory/directions.py`: due dates, compliance matching. `memory/events.py`: chronology.
4. `memory/queries.py`, `memory/reports.py`: current/as-of facts, claims board, What-Changed.
5. `memory/review.py`: review queue and resolution actions.
6. Tests: edge-case integration suite + the M2 worked example end to end.

## 3. Execution report

**Built:** `memory/{resolve,reconcile,directions,events,queries,reports,review}.py`.

**Verified (real database):**

| Test file | Tests | Covers |
| --------- | ----- | ------ |
| `tests/integration/test_reconcile_edges.py` | 27 | date-order application; older amendment born superseded; unsigned amendment evidence-only; ambiguous contract reference flagged not guessed; uncertain type demoted; equal-authority conflict disputed; failed doc does not block batch; reconcile twice = same result; empty document; duplicate in later batch; cross-matter isolation; R5 outstanding (payments, overpayment clamp, none); compliance (in time, late, wrong party/too early, period from receipt unknown, later order supersedes deadline, undated order); amended pleading vs unamended change; every review action and its rejections |
| `tests/e2e/test_m2_worked_example.py` | 8 | the blueprint's worked example (matter M2) F1–F7: batch 1 position; batch 2 supersedes/narrows/disputes and adds directions; as-of views per batch; computed deadlines and statuses; struck-through chronology; every fact has a verbatim quote on its page; claim↔evidence links; complete ledger |

**Deviations from the blueprint**

1. RECONCILE is a **batch-level job** (so documents can be ordered by date), not per-document.
2. R3 applies only against court-sourced facts; late-arriving older documents are stored already-superseded (see S01).
3. Review actions write `MANUAL` ledger rows so human decisions are as auditable as rule decisions.
4. Directions listing excludes evidence-only rows (found by the eval harness: a one-sided email proposing a date leaked into the direction list).
