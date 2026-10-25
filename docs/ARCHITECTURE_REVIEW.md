# Architecture review: what I kept, what I changed, what worries me

You asked me to review `docs/source/ARCHITECTURE_BLUEPRINT_v3.md` against the hackathon brief and decide. The blueprint is strong. Its best idea is that **code, not a model, decides what is "current"**
(authority rules + canonical fact keys + batch ledger). I kept that spine unchanged and built it as written.

## Kept as designed (ADR numbers refer to the blueprint)

| ADR | Decision | Implemented as |
| --- | -------- | -------------- |
| 01 | One PostgreSQL 16 + pgvector database | yes, HNSW + iterative scan |
| 02 | PostgreSQL job queue (`SKIP LOCKED`) | yes; stale-job reclaim and retries tested |
| 03 | Open-weight, self-hosted models | yes; Ollama locally (zero cost), vLLM through the same OpenAI-compatible adapter |
| 05 | Fact keys + authority rules in code | yes, R0–R9, one test per rule |
| 06 | Batch time + change ledger | yes; as-of views and What-Changed report |
| 07 | Explicit typed retrieval plans, no agent framework | yes, eight plans + router (rules → fast model → default) |
| 08 | Citation verification in code | yes (ids retrieved, quote on page, numbers/dates, not only superseded) |

## Changed or added, and why

| # | Change | Reason |
| - | ------ | ------ |
| 1 | **Ollama for local runs** instead of vLLM/TEI on A10G nodes | you need to test on a laptop at zero cost; same port interface, so vLLM remains a config switch |
| 2 | **`fixture` demo mode** (recorded model output + hashing embedder) | lets anyone see the product work with no model download; used by CI and `lw-eval` |
| 3 | **Born-superseded late arrivals** | real uploads are not chronological; an old amendment arriving late must not override a newer term |
| 4 | **R3 only against court-sourced facts** | a party *pleading* what happened at a hearing is not an order; goes to review, not auto-supersede |
| 5 | **RECONCILE as a batch-level job**, documents applied in document-date order | order of upload must not change the outcome |
| 6 | **Title-line-only classification**; `signed_by_all` needs model **and** text agreement | body-text keywords ("within 30 days of receipt") misclassified documents in testing |
| 7 | **Extractive (model-free) answer fallback** | a model outage degrades the answer instead of breaking the product; flagged in the UI and in metrics |
| 8 | **Enterprise layer you asked for**: JWT roles, rate limits, problem+json, request ids, Prometheus metrics, audit log, structured logs | requirement added mid-build |
| 9 | Extra tables: `document_extractions`, `batch_duplicates`, `audit_log` | explainability of dropped candidates, duplicates in the report, accountability |
| 10 | UI served by the API for single-process runs | one command for demo; nginx image for real deployments |
| 11 | Dropped Docling and OpenCV | PIL-only OCR preprocessing is enough for the synthetic scans and keeps the install small; revisit with real scans |
| 12 | Cost/GPU/AWS sections not built | out of scope for local testing; the deployment plan keeps the spirit (open source, no managed APIs) |

## Concerns about the blueprint itself

1. **The headline claim is only as good as the extraction model.** Rules are deterministic, but a wrong slot, subject or date from the model will produce a confident wrong "current" fact. Mitigations built: quote must be on the page, allowed-slot lists, ambiguity → review queue.
   Missing: calibrated confidence. *Action:* run `lw-eval` on M4 with your chosen model before trusting any number; add real (redacted) matters.
2. **Qwen3-8B / 4B is small for Indian legal drafting.** Long pleadings with nested cross-references are where it will fail first. The `LLM_MAIN_MODEL` setting makes it a one-line change to test a larger model (e.g. a 14B–32B open model) on a GPU host.
3. **Embeddings and Indian-English legal text:** `bge-m3` is multilingual and a sensible default; recall was only measured with the lexical hashing embedder here. Measure before deciding on a reranker.
4. **Legal corpus is the weakest part.** The seed is paraphrased by me, UNVERIFIED, and tiny. A lawyer-verified corpus of the statutes and judgments that matter is a real work item, not an engineering one.
5. **Deadlines:** computing "four weeks from today" is easy; real-world limitation, court holidays, service rules and condonation are not modelled. The product shows the computed date *and* its basis; lawyers must still check.
6. **Evaluation is partly circular.** The synthetic matters were written by the same author as the pipeline. They prove the rules and plumbing; they cannot prove generalisation to messy real files.
7. **Single trust boundary:** matter isolation exists, tenant isolation does not.
8. **Shared file storage** blocks stateless multi-node scale-out until an S3-compatible adapter exists.

## Recommended next steps (in order)

1. Run `scripts/pull_models.sh`, then `lw-eval --matters M1 M2 M3 M4` with Ollama and read the failures: that is your real baseline.
2. Get two or three real, redacted matters from a lawyer and add them as gold sets.
3. Replace the seed corpus with verified text; record verifiers.
4. Decide on model size from the numbers (and GPU budget if you leave "zero cost").
5. S3 adapter, OIDC SSO, tenant isolation — only if this leaves the pilot stage.
