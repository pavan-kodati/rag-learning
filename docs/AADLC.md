# AADLC: how this project was built

**AADLC** is read here as the *Agentic / AI-assisted Development Life Cycle*, run spec-first and section by section.
If your organisation defines the acronym differently, the structure below still holds: every section has a
written spec before code, a plan before execution, and an execution report with evidence after.

```
   SPEC  ──►  PLAN  ──►  EXECUTE  ──►  VERIFY  ──►  REPORT  ──►  (next section)
 what & why   tasks,     code +        tests run,    what was built, what was
 acceptance   order,     tests         evidence      verified, what was NOT,
 criteria     risks                    captured      deviations from the blueprint
```

## Rules the build followed

1. **No code before a spec.** Each section's `README.md` opens with its Spec (scope, acceptance criteria
   traced to the brief and the blueprint) and a Plan (ordered tasks).
2. **One section at a time.** A section is only "done" when its acceptance criteria are checked against real
   test output, recorded in its Execution report.
3. **Deterministic code decides; models only read.** (Blueprint §8.4.) Anything a model produces is validated
   in code before it can change case memory.
4. **Honest reports.** Each report lists what was verified in the build sandbox, what could only be verified
   by you locally (real LLM, your hardware), and every deviation from the blueprint.

## Section tracker

| # | Section | Folder | Status |
| - | ------- | ------ | ------ |
| S00 | Foundations: repo, config, tooling, compose, CI | [sections/S00-foundations](sections/S00-foundations/README.md) | ✅ done (report in section) |
| S01 | Domain core: normalisers, slots, keys, authority rules, deadlines | [sections/S01-domain-core](sections/S01-domain-core/README.md) | ✅ done (report in section) |
| S02 | Data layer: schema, migrations, repositories, job queue | [sections/S02-data-layer](sections/S02-data-layer/README.md) | ✅ done (report in section) |
| S03 | Model adapters: LLM, embeddings, reranker (open source, local) | [sections/S03-model-adapters](sections/S03-model-adapters/README.md) | ✅ done (report in section) |
| S04 | Ingestion: parse, OCR, classify, chunk, embed, extract | [sections/S04-ingestion](sections/S04-ingestion/README.md) | ✅ done (report in section) |
| S05 | Matter memory: reconcile, ledger, directions, events, review | [sections/S05-matter-memory](sections/S05-matter-memory/README.md) | ✅ done (report in section) |
| S06 | Retrieval: hybrid search, router, eight plans | [sections/S06-retrieval](sections/S06-retrieval/README.md) | ✅ done (report in section) |
| S07 | Grounding and answers: generation, citation verification, hearing brief | [sections/S07-grounding](sections/S07-grounding/README.md) | ✅ done (report in section) |
| S08 | Legal corpus | [sections/S08-legal-corpus](sections/S08-legal-corpus/README.md) | ✅ done (report in section) |
| S09 | API | [sections/S09-api](sections/S09-api/README.md) | ✅ done (report in section) |
| S10 | UI | [sections/S10-ui](sections/S10-ui/README.md) | ✅ done (report in section) |
| S11 | Synthetic matters and evaluation harness | [sections/S11-synthetic-eval](sections/S11-synthetic-eval/README.md) | ✅ done (report in section) |
| S12 | DevOps and deployment plan | [sections/S12-devops](sections/S12-devops/README.md) | ✅ done (report in section) |

(The final status of each section is recorded in the "Execution report" at the bottom of its README.)
