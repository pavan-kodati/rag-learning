# S04 · Ingestion (upload → searchable, structured candidates)

## 1. Spec

**Goal:** turn an uploaded file into (a) pages with text and character boxes, (b) a document type and authority class,
(c) retrievable chunks with embeddings, and (d) validated *candidate facts* — without ever trusting a model's output
until code has checked it (blueprint §7, §8.4).

**Pipeline** (one job per stage, so a failure is isolated and retryable):

```
upload ─► VALIDATE ─► CONVERT ─► PARSE ─► CLASSIFY ─► CHUNK+EMBED ─► EXTRACT ─► (batch commit) ─► RECONCILE
          magic bytes  docx/email  text +   rules, then   structure-     model → validate     S05
          size, pages  → PDF       OCR      fast model     aware          in code
          encrypted?                                       strategies
```

**Acceptance criteria**

| ID | Criterion |
| -- | --------- |
| S04-1 | Accept PDF, DOCX, EML, TXT/MD, PNG/JPG; reject by **content** (magic bytes), not by extension; size and page limits |
| S04-2 | Digital PDFs: text + per-character boxes (for click-to-highlight). Scanned pages: Tesseract OCR with PIL-only preprocessing |
| S04-3 | Encrypted, corrupt, empty or image-only-without-OCR files fail **that document only**, with a message a lawyer can read |
| S04-4 | Classification is rules-first on *title lines only*; model second; low confidence → CORRESPONDENCE (cannot overwrite anything) |
| S04-5 | Chunk by structure: clauses, numbered paragraphs, order paragraphs, e-mail messages, table rows, windowed fallback; prayer/signature tails kept |
| S04-6 | Extraction output is checked: allowed slot for the document type, quote really on the cited page, value normalises, party/subject resolvable — otherwise dropped **with a reason** (stored in `document_extractions`) |
| S04-7 | Re-upload of the same bytes in a matter creates no duplicate facts |
| S04-8 | Failure in one file never blocks the others in the batch; a failed file can be re-uploaded or retried |

## 2. Plan

1. `ingestion/validate.py`: type sniffing, limits, encryption check. `ingestion/convert.py`: DOCX/EML/text/image → PDF (reportlab, DejaVu for ₹; optional LibreOffice).
2. `ingestion/render.py`, `pdfio.py`: page text, char boxes, quote location (`find_quote_span`, `highlight_rects`), page images.
3. `ingestion/classify.py` (+ `domain/authority.py` title rules).
4. `ingestion/chunk.py`: strategies per document type.
5. `ingestion/extract.py`: prompts, JSON schema, `validate_items`.
6. `ingestion/service.py`: `register_upload`, `run_parse`, `run_extract`, `commit_batch`, `retry_batch`; `worker.py` drives the queue.
7. Tests: unit per module, integration through the real database with a scripted model.

## 3. Execution report

**Built:** `ingestion/{validate,convert,render,pdfio,classify,chunk,extract,service}.py`, `worker.py`.

**Verified (real run):**

| Test file | Tests | Covers |
| --------- | ----- | ------ |
| `tests/unit/test_ingest_validate_convert.py` | 40 | sniffing, limits, encrypted/corrupt, DOCX/EML/text conversion, filename sanitising |
| `tests/unit/test_chunk.py` | 18 | every chunk strategy, tails, window overlap, empty input |
| `tests/unit/test_classify_extract.py` | 50 | title-line rules, low-confidence demotion, `signed_by_all` double-check, every drop reason in `validate_items` |
| `tests/unit/test_authority_slots.py` | 37 | document type → authority; allowed slots per document type |
| `tests/integration/test_ingest_service.py` | 25 | full upload → parse → classify → chunk → extract with a scripted model; worker isolates a corrupt and an encrypted file from a good one; duplicate upload; retry |

**Negative / fallback behaviour exercised:** corrupt PDF, password-protected PDF, empty/blank/whitespace-only documents, executable or
extension/content mismatch, oversize upload, hostile filenames (path traversal), upload to an unknown matter or closed batch,
duplicate upload, parse re-run after a crash (idempotent), scanned page without OCR (flagged, not crashed), model outage
(retried, then the document fails; recovers when the model returns), low-confidence classification (demoted to CORRESPONDENCE and flagged),
extraction items that cite text not on the page or use a slot not allowed for the document type (dropped, reason stored).

**Deviations from the blueprint**

1. **Classification looks at title lines only.** Body text such as "within 30 days of *receipt*" must not turn a contract into a receipt (found during testing).
2. **`signed_by_all` needs the model *and* a text heuristic** (≥2 signature blocks) to agree — a bilateral variation changes the contract only when it is really signed.
3. **Clause/paragraph documents are never merged** into windows (atomic citations).
4. **OCR preprocessing is PIL-only** (grayscale, autocontrast, upscale). Docling/OpenCV were dropped to keep the install light; swap in later behind `render.py`.
5. **Fixture mode keys recorded model output by text SHA or `file:<name>`** because OCR text differs between machines.

**Not verified here:** extraction *quality* of a real LLM (the sandbox has no model). The code paths around the model are verified; accuracy numbers need `lw-eval` on your machine with Ollama.
