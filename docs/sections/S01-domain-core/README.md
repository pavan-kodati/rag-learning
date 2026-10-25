# S01 · Domain core (pure logic, no I/O)

## 1. Spec

**Goal:** implement, as pure and exhaustively tested functions, everything the blueprint says *code* (not a model)
must decide: normalisation (§7.5), slots and fact keys (§8.2), authority classes (§7.3), the R0–R9 authority rules
(§8.3), deadline arithmetic (§8.6) and subject resolution (contract registry, notices, invoices).

**Why first:** these rules decide what the lawyer sees as "current" vs "superseded". They must be deterministic,
explainable and testable without a database or a GPU.

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S01-1 | Amounts: `₹18,40,000`, `Rs. 18.4 lakh`, `INR 1.2 crore`, `18,40,000/-`, amount in words → exact `Decimal` |
| S01-2 | Dates: `12.01.2024`, `12/01/2024`, `12th January, 2024`, `Jan 12, 2024`, ISO → `date`, day-first by default |
| S01-3 | Periods: `within four weeks` → 28 days; `30 days`; `two months` → 2 calendar months; `a fortnight` → 14 days |
| S01-4 | Fact keys are built by code from `(subject_type, normalised subject_ref, slot)`; the model never writes keys |
| S01-5 | One table-driven test per rule R0–R9, plus ordering/precedence cases (first match wins) |
| S01-6 | Deadlines: due date = trigger + period (12 Sep 2025 + 4 weeks = 10 Oct 2025); weekend flag; overdue status; unknown trigger → no date |
| S01-7 | Contract / notice / invoice / payment subject resolution incl. ambiguity → "needs review" |

**Key design decisions**

- Rules are a pure function `decide(new, current_facts) -> Decision`, returning *what to do* (end/mark/link) and the
  `rule_id`; persistence is somebody else's job (S05). This is what makes "one test per rule" possible.
- Authority is a property of the **document class**, not of recency (blueprint "Why not newest wins").
- Conservative defaults: low-confidence classification → CORRESPONDENCE (cannot overwrite anything).

## 2. Plan

1. `domain/types.py`: enums and dataclasses (`DocType`, `Authority`, `FactValue`, `NewFact`, `CurrentFact`, `Decision`).
2. `domain/normalise.py`: amounts, dates, periods, booleans, names, slugs.
3. `domain/slots.py`: subject types → slots → value types, allow-lists per document type.
4. `domain/keys.py` + `domain/subjects.py`: key building, contract registry, notice/invoice/payment refs.
5. `domain/authority.py`: document type → authority class; classification rules.
6. `domain/rules.py`: R0–R9 decision function.
7. `domain/deadlines.py`: due-date calculator.
8. Unit tests: table-driven, written from the blueprint's worked example (Vardhan v Kestrel).

## 3. Execution report

**Built:** `domain/{types,normalise,slots,keys,subjects,authority,rules,deadlines}.py` (pure, no I/O).

**Verified (real test run):** `pytest tests/unit` → 199 passed in 0.19s

| Criterion | Evidence |
| --------- | -------- |
| S01-1 amounts | `test_normalise.py::test_parse_amount_ok` (13 formats) and `..._rejects_garbage` (8 negative inputs) |
| S01-2 dates | 13 positive formats, 7 invalid dates (`31.02.2024`, `13/13/2024`, ...) return `None` |
| S01-3 periods | 11 positive, 6 "no period" negatives; month-end clamping |
| S01-4 keys | blueprint examples + 6 malformed-input rejections |
| S01-5 rules | `test_rules.py`: R0-R9 each covered, plus late-arrival, same-date, same-side, multi-conflict precedence |
| S01-6 deadlines | 12 Sep 2025 + 4 weeks = 10 Oct 2025; receipt-trigger unknown → review; overdue/due-today boundary |
| S01-7 subjects | contract/notice/invoice/payment resolution incl. ambiguity cases |

**Deviations from the blueprint (and why)**

1. **R3 applies only when the existing fact is itself court-sourced.** The blueprint says "earlier direction or order";
   a *pleaded* statement about a hearing is not an order, so it goes to R9 (review) rather than being auto-ended.
2. **Late-arriving older documents** (e.g. an older amendment uploaded after a newer one) are stored as already
   superseded ("born superseded") instead of overwriting the newer term. The blueprint's rules assume
   chronological arrival; real uploads are not chronological.
3. **Link orientation is explicit** (`TargetEffect.reverse`): SUPPORTS/CONTRADICTS point claim → evidence, SUPERSEDES points newer → older.
4. Bare scale words ("lakh") are rejected as amounts rather than read as 1 lakh.
