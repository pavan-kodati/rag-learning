# Legal Workspace: Architecture & Engineering Blueprint
## Persistent, evidence-grounded matter memory for Indian commercial and contract litigation

> **Team:** Team 3 · AI Fusion, RAG Hackathon (Track: Retrieval-Augmented Generation)  
> **Status:** Revised architecture v3, for team review (25 Oct 2026)  
> **Environment:** AWS us-east-1 on two GPU nodes: AI node `g5.4xlarge` + App node `g5.2xlarge` (1× NVIDIA A10G, 24 GB each)  
> **Budget:** $3,000 for the 30-day build. Planned spend ≈ $1,520 including 25% contingency; billing alarms at $1,000, $1,600 and $2,200; GPU nodes stop automatically when idle  
> **Core constraints:** Open-weight models only, self-hosted (vLLM, Text Embeddings Inference); no managed or closed LLM APIs; permissive licences only  
> **Scope:** Indian commercial and contract litigation: Breach / Non-Performance, Payment / Recovery, Termination / Injunction

---

## 0. Document Control

### 0.1 Version history

| Version | Change |
| :--- | :--- |
| v1 | Initial architecture deck (19 slides): two GPU nodes, Qwen3-8B, canonical fact keys, authority rules, batch ledger |
| v2 | Production blueprint: single `g4dn.xlarge`, $500/month, Mumbai region, legal fine-tuned 4B model |
| v3 (this document) | Returns to the deck's limits and keeps v2's detail (schema, hybrid SQL, API, OCR, coordinates). Fixes the gaps listed in 0.2 |

### 0.2 What changed from v2, and why

| Area | v2 | v3 | Why |
| :--- | :--- | :--- | :--- |
| Hardware and budget | 1× T4 16 GB, $500/month, ap-south-1 | 2× A10G 24 GB, $3,000 / 30 days, us-east-1 | Agreed team limits; A10G supports BF16 and fits Qwen3-8B |
| Main LLM | `goasty/Qwen3-4B-Indian-Law` (unverified single-author fine-tune, trained mainly on criminal statutes) | `Qwen3-8B`, with `Qwen3-4B` as router and standby | Grounding is scored: reliable JSON and instruction following matter more than built-in legal knowledge. The law comes from the corpus |
| "What changed" | Real-world dates only | Batch time + `fact_change_log` ledger (§8.1, §8.5) | A document dated 2024 can arrive in Batch 2; dates alone cannot say what is new |
| Supersession | Similarity search + NLI classifier | Fact keys + authority rules in code (§8.2, §8.3) | NLI has no "superseded" answer and cannot tell replace, dispute and narrow apart |
| Missing structures | One fact table | Parties, evidence links, events, court directions, page text | Required by brief §4 |
| Retrieval plans | 4 | 8 plans + hearing brief template (§9) | Required by brief §7 and round 3 |
| Citation checks | NLI stage with no model named | Code checks: source retrieved, quote on page, numbers match (§10) | Deterministic, cheap, explainable |
| Parsing licences | PyMuPDF (AGPL-3.0), Surya (GPL-3.0) | pypdfium2, pdfplumber, Docling, Tesseract | Licence constraint C4 |
| Job queue | Amazon SQS | PostgreSQL `FOR UPDATE SKIP LOCKED` | One less service; job state commits with batch state |
| Network | Private subnet with an Elastic IP (contradictory); NAT not costed | Public App node, private AI node, S3 gateway endpoint, NAT only during setup | Correct topology; about $40 saved |
| Instances | Spot | On-demand with auto-stop | A Spot interruption during judging would end the demo |
| LLM context | 4,096 tokens | 16,384 tokens on the AI node | Evidence + instructions + JSON output exceed 4K |
| Evaluation | Public legal IR benchmark | Golden set on synthetic matters + held-out matter (§18) | Judges use an unseen matter |
| Claims | "Guarantees zero hallucination" | Measurable targets | Judges test claims |

### 0.3 Owners

| Role | Owns |
| :--- | :--- |
| Lead / Architect | §1–6, authority rules sign-off, ADRs |
| Ingestion | §7, §8.2–8.4, §8.6 |
| Retrieval & Answers | §9–11 |
| UI & API | §16–17 |
| Platform & Eval | §12–15, §18 |

---

## 1. Problem, Goals and Scope

### 1.1 The problem
Legal matters are not static document archives. A commercial dispute begins with an agreement and purchase orders, grows through notices and replies, becomes pleadings (plaint, written statement, replication), and accumulates evidence, applications, hearing notes and court orders. As new documents arrive:

1. **Facts change.** An amendment moves the delivery date; a bank statement shows a part-payment.
2. **Positions are contested.** The written statement denies that a legal notice was ever received.
3. **Courts set deadlines.** An order directs replication "within four weeks".
4. **Law governs consequences.** For example, Indian Contract Act ss.73–74 (compensation and stipulated damages), Specific Relief Act, CPC Order XXXIX (temporary injunctions), Commercial Courts Act s.12A (pre-institution mediation).

### 1.2 Mission
The system is **not a document chatbot**. It is a persistent case memory that tells a lawyer, with a page reference for every material statement:
- the current position of the matter;
- what changed with the latest documents, and which earlier understanding is no longer valid;
- which facts are disputed, and the evidence for and against each side;
- what the court has directed, and what is due when;
- which statutes and judgments are relevant;
- what needs to be prepared for the next hearing.

### 1.3 How judges test it (brief §8)

| Round | Judges do | Workspace shows |
| :--- | :--- | :--- |
| 1. Index initial documents | Ask about gist, chronology, claims, evidence, court directions | Gist with citations; dated timeline; per-party claims board with evidence for and against; directions with computed due dates |
| 2. Add documents to the same matter | Ask what changed, what is no longer valid, what new evidence or action appeared, the current position | What-Changed Report for the batch; superseded items struck through with the document that replaced them; gist rebuilt from current facts only |
| 3. Hearing preparation | Ask for a brief using the complete matter | Hearing brief in a fixed template; every line cited to a document and page |

### 1.4 Brief requirements traceability

| Brief requirement | Design element | Section |
| :--- | :--- | :--- |
| Create or open a matter and ingest its documents (§3) | Matters, batches, upload API and UI | §16, §17 |
| Different retrieval for different questions (§3, §7) | Router + 8 typed retrieval plans | §9 |
| Incremental memory without retraining (§3) | Batches, batch time, ledger | §8.1, §8.5 |
| Document/page references (§3, §7) | Coordinates on every chunk; citation verification | §7.4, §10 |
| Chronology (§4) | Events table + Plan 2 | §8, §9.2 |
| Claims, counterclaims, defences, relief per party (§4) | Parties + fact categories | §8.2, §15 |
| Assertions mapped to supporting or contradicting evidence (§4) | `fact_links` | §8.3, §15 |
| Directions, deadlines, undertakings, pending actions (§4) | `court_directions`, deadline rules | §8.6 |
| What changed; no repetition of superseded facts (§4, §7) | Ledger, authority rules, current-fact filters | §8.3, §8.5, §10 |
| Hearing brief (§4) | Fixed template fed by six plans | §9.4 |
| Statutes and judgments when needed (§4, §6) | Separate legal corpus schema + Plan 7 | §11 |
| Synthetic development documents (§5) | Three synthetic matters + held-out matter | §18.1 |

### 1.5 Quality goals (scoring areas)

| Scoring area | Weight | What earns it | How we test it | Target |
| :--- | :--- | :--- | :--- | :--- |
| Answer correctness | 25% | Right plan per question; Qwen3-8B; slot-based extraction; normalisation in code | Golden Q&A with a scripted checker | ≥ 90% on the held-out matter |
| Grounding / traceability | 20% | Citations verified in code before display | Automated span check + manual sample of 50 | ≥ 95% citation precision |
| Incremental update | 20% | Batches, ledger, idempotent ingestion; old documents never re-indexed | Timed batch replay | All new documents in; ≤ 2 min per 20 pages |
| Contradiction / supersession | 15% | Fact keys + authority rules | Planted changes in every matter | ≥ 90% correct; 0 superseded facts shown as current |
| Matter understanding / chronology | 10% | Event store; claims and relief per party | Compare with a gold timeline | ≥ 90% events correct |
| Retrieval quality | 5% | Structure-aware chunks; dense + full-text; reranker | Recall@10 on labelled chunks | ≥ 0.85 |
| Usability / demo | 5% | Click-to-source PDF, struck-through history, retrieval trace | Dry runs with a teammate as judge | 3 full rehearsals |

### 1.6 Out of scope
Criminal, family, land/revenue, tax and IP matters; legal outcome prediction; an all-India case-law search engine (brief §2).

---

## 2. Constraints

| ID | Constraint | Source | Consequence for the design |
| :--- | :--- | :--- | :--- |
| C1 | Indian commercial and contract litigation only | Brief §2 | Small, curated legal corpus; no criminal-law models |
| C2 | Unseen matter, delivered in batches | Brief §8 | No matter-specific rules or prompts; a held-out test matter |
| C3 | 24 GB GPU per node; model size P (billions) must satisfy P × 2.2 + 5 ≤ 24 GB | Team deck (track formula) | Largest main model: about 8.6B, so Qwen3-8B |
| C4 | Permissive model and tool licences; Llama-licensed models excluded | Team deck (organiser rule 10) | Apache / MIT / BSD stack; no AGPL or GPL code inside our process |
| C5 | $3,000 for 30 days | Team deck | On-demand nodes with auto-stop; planned ≈ $1,520 |
| C6 | 30-day build; code freeze on Day 28 | Team deck | Weekly exit tests (§19) |
| C7 | Synthetic matter data is for building and validation, not training | Brief §5 | No fine-tuning; retrieval + extraction only |

---

## 3. System Context

```text
  Lawyer / judge (browser)
          |
          |  HTTPS, team login
          v
  +--------------------------------------------------+
  |                 LEGAL WORKSPACE                  |
  |  matters - batches - case memory - answers       |
  +--------------------------------------------------+
          |                               ^
          | originals, model weights,     | statutes and judgments,
          | nightly backups               | loaded once before judging
          v                               |
  +----------------+            +----------------------------------+
  |   Amazon S3    |            |  India Code / SCR / eCourts      |
  +----------------+            +----------------------------------+
```

*Text alternative:* users reach the workspace over HTTPS. The workspace stores originals, model weights and backups in S3. Public statutes and judgments are downloaded, verified and loaded once, before judging; the system makes no live calls to public legal sites.

---

## 4. Architecture Decisions

| ID | Decision | Rejected alternatives | Reason |
| :--- | :--- | :--- | :--- |
| ADR-01 | One PostgreSQL 16 + pgvector database for chunks, vectors, facts, links, ledger and corpus | OpenSearch; Qdrant + separate fact DB; Neo4j | A supersession updates a fact, adds a link and writes a ledger row in one transaction. The claims graph is small; plain SQL is enough |
| ADR-02 | PostgreSQL job queue (`FOR UPDATE SKIP LOCKED`) | Amazon SQS; Redis + Celery | Survives restarts; job and batch state commit together; no extra service or cost |
| ADR-03 | Self-hosted open-weight models on vLLM and TEI | Managed LLM APIs | Constraint C4; fixed cost; data stays in the VPC |
| ADR-04 | General instruction model (Qwen3-8B) + legal corpus | Legal fine-tuned small models | Grounding is scored; law must come from cited sources, not model memory |
| ADR-05 | Canonical fact keys + authority rules in code | Similarity search + NLI classifier | Exact matching; legal effect decides the outcome; predictable and testable |
| ADR-06 | Batch time + change ledger | Real-world validity dates only | Answers "what changed" and "what is no longer valid" directly |
| ADR-07 | Explicit, typed retrieval plans (Pydantic) | Agent framework | Each plan is logged and shown in the UI trace; easy to debug and explain |
| ADR-08 | Citation verification in code | Trusting the model; separate NLI model | Deterministic and fast; no extra GPU memory |
| ADR-09 | pypdfium2, pdfplumber, Docling, Tesseract | PyMuPDF (AGPL-3.0), Surya OCR (GPL-3.0) | Constraint C4 |
| ADR-10 | On-demand instances with auto-stop | Spot instances | No interruption risk during judging; idle cost controlled by auto-stop |
| ADR-11 | React + TypeScript single-page app served by Nginx | Next.js server rendering | No server rendering needed; one less runtime |
| ADR-12 | Model weights and images staged through S3 (free gateway endpoint); NAT gateway only during setup | Permanent NAT gateway | Same result for about $40 less; fewer open egress paths |

---

## 5. Building Blocks and Deployment View

```text
PUBLIC SUBNET (us-east-1)
+------------------------------------------------------------------------+
| App node: g5.2xlarge (8 vCPU, 32 GiB RAM, 1x A10G 24 GB)               |
|------------------------------------------------------------------------|
| Nginx (TLS)  ->  React + TypeScript UI (static files)                  |
| FastAPI: matters, batches, ask, hearing brief, review queue            |
| Ingestion worker (PostgreSQL job queue, FOR UPDATE SKIP LOCKED)        |
| Query orchestrator: route -> plan -> retrieve -> generate -> verify    |
| PostgreSQL 16 + pgvector (own 100 GB EBS volume, kept on termination)  |
| GPU: vLLM Qwen3-4B  |  TEI BGE-M3  |  TEI bge-reranker-v2-m3           |
| SG: 443 from allow-listed IPs, 22 from team IPs                        |
+------------------------------------------------------------------------+
                  |
                  |  HTTP :8000, OpenAI-compatible API + API key
                  v
PRIVATE SUBNET (no public IP)
+------------------------------------------------------------------------+
| AI node: g5.4xlarge (16 vCPU, 64 GiB RAM, 1x A10G 24 GB)               |
|------------------------------------------------------------------------|
| vLLM: Qwen3-8B BF16  (extraction, answers, hearing brief)              |
| SG: 8000 from the App node's security group only                       |
+------------------------------------------------------------------------+

Both nodes reach S3 through the free S3 gateway endpoint:
originals, model weights, container images, nightly pg_dump.
```

*Text alternative:* the App node (public subnet) runs the web UI, API, ingestion worker, query orchestrator, PostgreSQL and three small GPU models. It calls the AI node (private subnet, no public IP) on port 8000 for Qwen3-8B. Both nodes use S3 through a gateway endpoint.

| Component | Responsibility | Technology |
| :--- | :--- | :--- |
| Web UI | Matters, batch upload, all views in §17, PDF viewer with highlights | React + TypeScript, pdf.js |
| API | REST endpoints in §16; team login (JWT); every query scoped to one matter | FastAPI (Python 3.11) |
| Ingestion worker | The eight steps in §7.1 | Python worker pool reading `ingestion_jobs` |
| Query orchestrator | Route, run plans, rerank, generate, verify citations, write trace | Python; plans as Pydantic models |
| Case memory | Evidence, knowledge and time layers (§6) | PostgreSQL 16 + pgvector ≥ 0.8 |
| Fast model server | Routing, classification, standby answers | vLLM serving Qwen3-4B |
| Embedding + reranker | Dense vectors; reranking | Text Embeddings Inference (TEI) |
| Main model server | Extraction, answers, hearing brief | vLLM serving Qwen3-8B |
| Object store | Originals, weights, images, backups | Amazon S3 (encrypted, versioned) |

---

## 6. Case Memory: Three Layers in One Database

| Layer | Question it answers | Main tables |
| :--- | :--- | :--- |
| **Evidence** | What do the documents say, and where? | `documents`, `document_pages`, `document_chunks` |
| **Knowledge** | What do we believe now, and what supports or contradicts it? | `parties`, `matter_fact_assertions`, `fact_links`, `matter_events`, `court_directions` |
| **Time** | When did we learn it, and what changed? | `ingestion_batches`, `fact_change_log`, batch columns on every fact |

The public legal corpus lives in its own schema (`legal_corpus`) and is never mixed with matter facts. Full DDL is in §15.

---

## 7. Ingestion Pipeline

### 7.1 Eight steps from file to case memory

| # | Step | What happens | Done by |
| :--- | :--- | :--- | :--- |
| 1 | Register | SHA-256 hash; skip duplicates in the matter; store original in S3; stamp with batch number; queue a job | Code |
| 2 | Parse | Text layer via pypdfium2; Docling or pdfplumber for tables and complex layouts; Tesseract OCR for scanned pages; save page text and boxes | Code |
| 3 | Classify | Document type, date, parties, whether signed by all parties; this sets the authority class (§7.3) | Rules first, then Qwen3-4B |
| 4 | Chunk | By clause, numbered paragraph, direction or email message (§7.4) | Code |
| 5 | Embed | BGE-M3 dense vectors for child chunks; full-text index is generated by PostgreSQL | Model |
| 6 | Extract | Qwen3-8B fills fixed slots per section; JSON schema; temperature 0 (§7.5) | Model |
| 7 | Normalise | Dates, rupee amounts, periods and party names normalised; each quote checked against its page | Code |
| 8 | Reconcile and commit | Fact-key lookup + authority rules; fact, link and ledger row in one transaction (§8.4) | Code |

Steps 1–7 run per document in parallel. Step 8 runs one document at a time per matter (§7.6). When every document in the batch is processed or failed, the batch is committed and its What-Changed Report is built (§8.5).

### 7.2 Parsing and OCR tools

| Tool | Licence | Used for |
| :--- | :--- | :--- |
| pypdfium2 | Apache-2.0 / BSD-3 | Default: text layer with character boxes; renders pages for OCR (no Poppler needed) |
| pdfplumber | MIT | Table detection and simple tables (milestones, invoices, payment schedules) as Markdown rows |
| Docling | MIT | Complex layouts and multi-column pages |
| Tesseract 5 + OpenCV | Apache-2.0 | Scanned pages: deskew and denoise, then OCR; per-page confidence saved. `eng`, plus `hin` if organisers confirm Hindi |
| LibreOffice (headless, separate process) | MPL-2.0 | DOCX to PDF, so every document has pages for citation |
| Python `email` (standard library) | PSF | EML: one message per chunk; quoted replies and signatures removed by rules; attachments become documents in the same batch |

A page is sent to OCR when its text layer is missing or unreadable (configurable threshold on extractable characters). Pages with low OCR confidence are flagged in the UI.

**Not used:** PyMuPDF (AGPL-3.0) and Surya OCR (GPL-3.0, restricted weights), because of constraint C4. OpenNyAI NER and rhetorical-role models are also not used: they are trained on judgments, not on contracts, emails or invoices, and would add CPU time to live ingestion.

### 7.3 Document types and authority classes
The authority class decides what a document is allowed to change (§8.3).

| Authority class | Document types | Can change |
| :--- | :--- | :--- |
| BILATERAL | CONTRACT, SOW, PURCHASE_ORDER, AMENDMENT, CHANGE_REQUEST (accepted), SIGNED_MINUTES | Contract terms (R2) |
| COURT | ORDER | Earlier directions and orders (R3) |
| PLEADING | PLAINT, WRITTEN_STATEMENT, REPLICATION, REJOINDER, COUNTERCLAIM, AMENDED_PLEADING | Its own party's position (R4); disputes the other side (R6) |
| SWORN | AFFIDAVIT, APPLICATION | Disputes the other side (R6); never changes contract terms |
| NOTICE | LEGAL_NOTICE, REPLY_NOTICE | Disputes the other side (R6); replaced by the same party's later pleading (R4) |
| RECORD | INVOICE, PAYMENT_RECORD, BANK_STATEMENT, RECEIPT, COURIER_PROOF, DELIVERY_NOTE | Narrows amounts (R5); evidence (R7) |
| CORRESPONDENCE | EMAIL, LETTER, UNSIGNED_MINUTES | Evidence only (R7, R8) |
| INTERNAL | HEARING_NOTE | Evidence only; never overrides a court order (R8) |

Classification uses rules first (titles such as "AMENDMENT" or "WRITTEN STATEMENT", cause titles, signature blocks), then Qwen3-4B with a JSON schema when no rule fires or rules disagree. **If confidence is below 0.7, the document is treated as CORRESPONDENCE and its facts go to the review queue.** A wrongly low authority creates a review item; a wrongly high one would silently overwrite facts.

### 7.4 Structure-aware chunking

| Document type | One child chunk = |
| :--- | :--- |
| Contract, SOW, amendment | One clause or sub-clause; provisos stay with their clause |
| Plaint, written statement, affidavit | One numbered paragraph (cited as ¶12) |
| Court order | One numbered direction, plus one header chunk (court, case number, date, coram) |
| Email thread | One message, with quoted replies removed |
| Invoice, bank statement | Whole document, or one table row per chunk |
| Statute / judgment (corpus) | One section / one numbered paragraph |

Rules:
1. **Size guard:** target 150–500 tokens; split above 800 at sentence boundaries; merge below 50.
2. **Coordinates:** every chunk stores `page_start`, `page_end`, character offsets and bounding boxes, for click-to-source highlighting.
3. **Context header:** for example `[MSA | 12 Jan 2023 | Vardhan v Kestrel | cl. 4.2]`, added before embedding.
4. **Small-to-big:** search child chunks (clauses, paragraphs); send the parent section to the LLM; cite the child's page.
5. **Fallback:** if no structure is found, 400-token windows with 50-token overlap.

### 7.5 Extraction and normalisation
- **Per document type:** one prompt with a JSON schema listing only the allowed slots (§8.2), plus two generic examples. Temperature 0. Qwen3 thinking mode is turned off. vLLM structured output enforces the schema.
- **Each extracted item:** `subject_type`, `subject_ref` (as written), `slot`, `value` (as written), `quote` (verbatim) and `page`.
- **Code then:** normalises the value, resolves the subject, builds the fact key, and checks the quote on the stated page (fuzzy match ≥ 90 with rapidfuzz, MIT). Items that fail the check are dropped and logged.

| Input | Normalised by code |
| :--- | :--- |
| ₹18,40,000 / Rs. 18.4 lakh / INR 1.2 crore / amount in words | Rupees as NUMERIC (lakh = 100,000; crore = 10,000,000) |
| 12.01.2024 / 12/01/2024 / 12th January, 2024 | ISO date; day-first by default (Indian convention) |
| "within four weeks" / "30 days" / "two months" | 28 days / 30 days / two calendar months |
| "Defendant No. 1", "Kestrel Limited", "the Customer" | One `party_id` via `party_aliases` |

**Documents are untrusted input.** Text inside a document (for example "ignore previous instructions") is treated as data. Outputs are constrained by the schema, and outcomes are decided by code.

### 7.6 Performance and concurrency
- **Target:** ≤ 2 minutes per 20-page digital document; scanned pages measured separately. Both are verified in the Week 1 benchmark.
- **Parallelism:** documents in a batch are parsed, chunked, embedded and extracted in parallel. vLLM batches concurrent requests. Classification runs on the App node while the AI node extracts.
- **Reconcile is serialised per matter** with a transaction-level advisory lock, in document-date order. Two documents in one batch therefore cannot race on the same fact key, and two amendments in one batch apply in date order.
- **Resilience:** jobs retry up to 3 times; a job stuck in RUNNING for more than 10 minutes is re-queued.

---

## 8. Matter Memory: Time, Supersession and Change

The core requirement of the brief is handling **incremental ingestion** and detecting when later documents **contradict, modify or supersede** earlier positions.

### 8.1 Two kinds of time
Every fact carries two kinds of time, stored separately:

| Time | Meaning | Example (synthetic matter) | Used for |
| :--- | :--- | :--- | :--- |
| **Real-world time** (`effective_from`, `effective_to`) | When the fact is true in the dispute | Amendment-1 moved delivery to 31 Jul 2024 from the day it was signed, 10 May 2024 | Chronology |
| **Batch time** (`learned_in_batch_seq`, `ended_in_batch_seq`) | In which upload batch the system learned the fact, and in which batch it stopped being current | Amendment-1 arrived in Batch 2, so the earlier "30 Jun 2024" fact ended in Batch 2 | What changed; what is no longer valid |

Real-world dates alone cannot answer "what changed". Amendment-1 is dated May 2024, which is *earlier* than the plaint uploaded in Batch 1, yet it is new information in Batch 2.

### 8.2 Slots and fact keys
To decide whether a new statement is about the same thing as an old one, the model fills **fixed slots** and **code builds a key**. Two facts about the same thing get the same key, so matching is an exact lookup.

**Key format:** `<subject_type>/<subject_ref>/<slot>`, lowercase, built by code from the normalised subject. The model never writes keys.

| Subject type | Subject reference (normalised by code) | Slots |
| :--- | :--- | :--- |
| CONTRACT | Contract ID from the matter's contract registry, e.g. `msa-2023` | effective_date, contract_value, scope, delivery_date, payment_terms_days, ld_rate, ld_cap, termination_notice_days, cure_period_days, termination_for_convenience, arbitration_clause, governing_law, jurisdiction, liability_cap |
| MILESTONE | Contract ID + milestone number | due_date, amount, completion_status, acceptance_date |
| INVOICE | Invoice number | invoice_amount, invoice_date, due_date, amount_paid, amount_outstanding (computed by code), deduction |
| PAYMENT | Payment reference or date | amount, date, against_invoice |
| NOTICE | Notice date + sender | sent_date, mode_of_service, received, received_date, demand_amount, cure_demanded |
| CLAIM | Claim head: principal, interest, damages, costs, other | amount, interest_rate, basis |
| RELIEF | Relief type: recovery, damages, injunction, specific_performance, declaration, costs | sought, amount, status |
| ALLEGATION | Topic: delay, defective_work, non_payment, wrongful_termination, breach_of_exclusivity, other | asserted, admitted, denied |
| DIRECTION | Procedural step (fixed list in §8.6) | due_date, responsible_party, compliance |
| HEARING | Hearing date | next_date, purpose, outcome |

**Examples**

| Document says | Slot filled by the model | Key built by code |
| :--- | :--- | :--- |
| MSA cl. 4.2: "Completion of the Deliverables… on or before 30 June 2024" | `delivery_date = 2024-06-30` | `contract/msa-2023/delivery_date` |
| Amendment-1: "Clause 4.2 stands substituted. The Go-Live Date shall be 31 July 2024" | `delivery_date = 2024-07-31` | `contract/msa-2023/delivery_date` |
| Plaint: "₹18,40,000 remains due under INV-014" | `amount_outstanding = 1840000` | `invoice/inv-014/amount_outstanding` |
| Written statement ¶7: "No notice was ever received" | `received = false` | `notice/2025-02-05-vardhan/received` |
| Order dated 12 Sep 2025: "Replication within four weeks" | `due_date` (computed) | `direction/replication/due_date` |

The key is built from **what the fact is about** (the MSA), not from the document that said it. That is why Amendment-1's date lands on the MSA's key. Contract references ("the Agreement dated 12.01.2023", "MSA") are resolved through a registry of the matter's contracts; an ambiguous reference goes to the review queue.

**Statements that fit no slot** are stored with slot `other`. Code may suggest a similar existing fact (BGE-M3 cosine similarity), but only as a review-queue candidate, never applied automatically.

The slot list is generic: it is built from all three archetypes, not from our own sample documents (constraint C2).

### 8.3 Authority rules
When a new fact has the same key as a current fact, **the authority of the new document decides the outcome**. Neither recency nor a model's opinion decides it. Rules are evaluated in order; the first match wins.

| Rule | New document | Current fact with the same key | Outcome | Change type |
| :--- | :--- | :--- | :--- | :--- |
| R0 | Any | None | New fact, ACTIVE | NEW |
| R1 | Any | Same value | New fact kept as supporting evidence; SUPPORTS link | CORROBORATED |
| R2 | BILATERAL, signed by all parties, dated after the term's source | Contract or milestone term | Old fact ended; SUPERSEDES link | SUPERSEDED |
| R3 | COURT order on the same point, later order date | Earlier direction or order | Old fact ended; if the new order stays or sets aside the earlier one, the reason says so | SUPERSEDED |
| R4 | Same party's later formal position: amended pleading allowed under Order VI Rule 17 CPC, or its pleading after its own notice | That party's earlier position | Old fact ended (shown in change views) | SUPERSEDED |
| R5 | RECORD of payment against the invoice | Outstanding amount | Code recomputes outstanding = invoice amount − sum of payments; old figure ended | NARROWED |
| R6 | Opposing party's PLEADING, SWORN or NOTICE document | The allegation | Both kept; both DISPUTED | DISPUTED |
| R7 | RECORD or CORRESPONDENCE conflicting with a party's pleaded or sworn position (in either order of arrival) | Pleaded fact | Both kept; CONTRADICTS link to the evidence | CONTRADICTED_BY_EVIDENCE |
| R8 | One-sided proposal (e.g. an email offering a new date), amendment application not yet allowed, or a hearing note that conflicts with an order | Any | Current fact unchanged; new fact stored as evidence only | NEW (evidence only) |
| R9 | Nothing above matches | Any | New fact DISPUTED and flagged for review; current fact marked DISPUTED; never overwritten silently | DISPUTED |

**Why not "the newest document wins":** Kestrel's written statement is newer than Vardhan's plaint. Under "newest wins", the system would state "the notice was not received" as fact, when it is only Kestrel's claim. Under R6, both versions stay visible as a dispute, each with its source.

**Why not NLI:** an NLI model only answers agree, contradict or neutral. In the example, an amendment, a denial, a part-payment and a contradicting email are all "contradict". The legal outcomes, however, are supersede, dispute, narrow and contradicted-by-evidence.

**Evidence-only facts** (`evidence_only = TRUE`, from R1, R7 and R8) appear on the claims board as evidence, but never in "current position" answers. A key whose current, non-evidence facts have different values is shown as disputed.

*This table is the team's reading of how commercial suits run. It must be reviewed and signed off by the team in Week 1, ideally with a lawyer.*

### 8.4 Reconciliation procedure
1. Take a transaction-level advisory lock for the matter.
2. For each new fact, in document-date order, load the current facts with the same key (`ended_in_batch_seq IS NULL`).
3. Evaluate R0–R9 using: the new fact (value, party, slot), the new document (authority class, signed by all parties, date) and the existing facts (value, party, authority, date).
4. In one transaction, apply the result: insert the new fact, end or re-state old facts, insert links and write the ledger rows (each with its `rule_id`).
5. On batch commit, recompute derived values (outstanding amounts, overdue directions) and build the What-Changed Report.

**No model call happens in steps 1–5.** Models only read documents (classify, extract); code decides.

### 8.5 Batch ledger and What-Changed Report
Each upload is a numbered **batch** (Batch 1 = initial documents, Batch 2 = first additional set, and so on). Every change to the system's understanding is written to `fact_change_log` with that batch number.

**Rules**
1. **Every upload opens a batch.** Each document is stamped with `batch_seq` on arrival; each fact it produces gets `learned_in_batch_seq = N`.
2. **Same transaction.** A fact update and its ledger row commit together, so the ledger can never disagree with the facts.
3. **Commit, then report.** A batch is committed once every document is `PROCESSED` or `FAILED`. Failed documents are listed in the report so nobody assumes they were read.
4. **Idempotent.** A file already in the matter (same SHA-256) is skipped and listed as a duplicate. Documents from earlier batches are never re-processed or re-indexed.
5. **Never delete.** A replaced fact is ended (`ended_in_batch_seq = N`) and linked to its replacement, so the earlier understanding can always be shown.

**Which time answers which question**

| Judge's question | Read from |
| :--- | :--- |
| What changed? What new evidence or action appeared? | `fact_change_log` rows for Batch N |
| Which earlier understanding is no longer valid? | Facts with `ended_in_batch_seq = N` |
| What is the current position? | Facts with `ended_in_batch_seq IS NULL` and `evidence_only = FALSE` |
| Chronology | Events sorted by real-world date |

**Worked example (synthetic matter: Vardhan Infotech v Kestrel Ltd, payment recovery)**

- **Batch 1:** MSA dated 12 Jan 2023, Invoice INV-014, legal notice dated 5 Feb 2025, plaint filed 3 Mar 2025.
- **Batch 2:** Amendment-1 dated 10 May 2024, bank statement, written statement, court order dated 12 Sep 2025.

Facts after Batch 2:

| # | Fact | Key | Source | Learned in | Ended in | State | Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| F1 | Delivery due 30 Jun 2024 | `contract/msa-2023/delivery_date` | MSA cl. 4.2, p.3 | 1 | 2 | SUPERSEDED | R2 |
| F2 | Delivery due 31 Jul 2024 | `contract/msa-2023/delivery_date` | Amendment-1, p.2 | 2 | — | ACTIVE | R2 |
| F3 | INV-014: ₹18,40,000 unpaid | `invoice/inv-014/amount_outstanding` | Plaint ¶9, p.4 | 1 | 2 | SUPERSEDED | R5 |
| F4 | INV-014: ₹12,40,000 unpaid after ₹6,00,000 paid on 14 Mar 2025 | `invoice/inv-014/amount_outstanding` | Bank statement, p.2 | 2 | — | ACTIVE | R5 |
| F5 | Legal notice of 5 Feb 2025 was served | `notice/2025-02-05-vardhan/received` | Plaint ¶12, p.5 | 1 | — | DISPUTED | R6 |
| F6 | Legal notice was never received | `notice/2025-02-05-vardhan/received` | Written statement ¶7, p.3 | 2 | — | DISPUTED | R6 |
| F7 | Plaintiff to file replication within four weeks (due 10 Oct 2025) | `direction/replication/due_date` | Order dated 12 Sep 2025, p.2 | 2 | — | ACTIVE | R0 |

The ledger rows for Batch 2, rendered as the report (each NEW row is grouped with the change it caused):

```text
WHAT CHANGED IN BATCH 2   (4 documents processed, 0 failed, 0 duplicates)

1. SUPERSEDED  Delivery date: 30 Jun 2024 -> 31 Jul 2024     [Amendment-1, p.2]
2. NARROWED    Amount unpaid: 18,40,000 -> 12,40,000 (INR)   [Bank statement, p.2]
3. DISPUTED    Notice served (Plaint p.5) vs denied           [Written statement para 7]
4. NEW         Replication due 10 Oct 2025                    [Order dated 12 Sep 2025, p.2]
```

**Queries**

```sql
-- (a) What changed in Batch N
SELECT l.change_type,
       l.rule_id,
       a.assertion_text AS fact,
       r.assertion_text AS related_fact,
       d.title AS caused_by,
       l.reason
FROM fact_change_log l
JOIN matter_fact_assertions a ON a.assertion_id = l.assertion_id
LEFT JOIN matter_fact_assertions r ON r.assertion_id = l.related_assertion_id
JOIN documents d ON d.document_id = l.caused_by_document_id
WHERE l.matter_id = $1
  AND l.batch_seq = $2
ORDER BY l.change_id;

-- (b) What the system believed as of Batch N, with each fact's state at that time
SELECT a.assertion_id,
       a.assertion_text,
       s.new_state AS state_as_of_batch
FROM matter_fact_assertions a
JOIN LATERAL (
    SELECT l.new_state
    FROM fact_change_log l
    WHERE l.assertion_id = a.assertion_id
      AND l.batch_seq <= $2
    ORDER BY l.batch_seq DESC, l.change_id DESC
    LIMIT 1
) s ON TRUE
WHERE a.matter_id = $1
  AND a.evidence_only = FALSE
  AND a.learned_in_batch_seq <= $2
  AND (a.ended_in_batch_seq IS NULL OR a.ended_in_batch_seq > $2);
```

Query (b) for Batch 1 returns F1, F3 and F5 (all `ACTIVE`); for Batch 2 it returns F2, F4, F5, F6 and F7. Comparing the two gives the same four changes as the report, which is a useful self-check in testing. The UI uses query (b) for its "view as of batch N" selector.

### 8.6 Court directions and deadlines
Each direction is a fact (so it appears in the ledger) plus a row in `court_directions` with the details.

- **Procedural steps (fixed list):** written_statement, replication, rejoinder, admission_denial_of_documents, affidavit_of_evidence, list_of_witnesses, deposit, mediation, interim_relief, compliance_report, inspection, next_hearing, other.
- **Due dates are computed in code, never by the model.** Period text is kept verbatim ("within four weeks from today"), normalised (28 days), and added to the trigger date (by default the order date). Example: 12 Sep 2025 + 28 days = 10 Oct 2025.
- **Trigger unknown:** if the period runs "from receipt of the copy" and the receipt date is unknown, no due date is computed and the direction goes to the review queue.
- **Court holidays:** if a due date falls on a weekend, it is flagged. Under the General Clauses Act 1897 s.10, an act due on a day the court is closed may be done on the next working day. Court holiday calendars are not modelled.
- **Compliance:** when a later batch contains the matching filing (for example a REPLICATION by the responsible party), the direction is marked `COMPLIED` and the ledger records it. A direction is overdue when its due date has passed and it is still `PENDING`; this is computed at query time.
- **Undertakings and interim relief** are stored the same way, with kind `UNDERTAKING` or `INTERIM_RELIEF`.

### 8.7 Human review queue
Items needing a person: facts with `needs_review = TRUE` (rule R9, low-confidence classification, ambiguous contract reference, unknown trigger date), low-confidence OCR pages, and failed documents. A reviewer can confirm the outcome, choose a different rule, or correct a value. Each action writes a ledger row with `rule_id = 'MANUAL'`, the reviewer's name and a reason. During judging, unresolved items are shown as "disputed, needs review", never hidden.

---

## 9. Retrieval Harness

### 9.1 Router
1. **Rules first:** keyword patterns per intent (e.g. "what changed", "since the last batch" → WHAT_CHANGED; "deadline", "due", "directed" → DIRECTIONS).
2. **Otherwise Qwen3-4B** returns JSON: `intents[]`, optional party, document, date range.
3. **Multi-intent:** several plans run and their results merge.
4. Each plan is a typed Pydantic object. It is logged in `query_traces` and shown in the UI's retrieval trace, which demonstrates brief §7 ("the same retrieval plan should not be used for every request").
5. The default `as_of_batch_seq` is the latest committed batch.

### 9.2 Eight retrieval plans

| # | Intent | Reads from | Method | Output |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Gist / current position | Current facts (non-evidence), latest orders | Structured query; top evidence per fact | Summary with citations |
| 2 | Chronology | `matter_events` | SQL sort by event date; superseded shown struck through; disputed shown with both versions | Dated timeline |
| 3 | Claims, defences, relief | Facts by party and category | Filter by party and category | Per-party table |
| 4 | Evidence for / against | `fact_links`, then chunks | Follow links; then hybrid search + rerank for more ("possible evidence, not yet linked") | For and against lists |
| 5 | Directions and deadlines | `court_directions` | Filter current directions; latest order first; due dates and overdue status from code | Action list |
| 6 | What changed | `fact_change_log` | Ledger rows for Batch N (§8.5 query a) | Change report |
| 7 | Legal research | `legal_corpus.passages` | Hybrid search + issue-tag filter from the matter's disputed slots | Authorities with section or paragraph |
| 8 | Factual Q&A (fallback) | Child chunks | Hybrid search → rerank top 30 to 8 → parent sections → Qwen3-8B | Cited answer |

**Context budget:** at most 8 parent sections (about 6,000 tokens) plus fact summaries. This fits the 16K context with room for instructions and output. Every retrieved chunk carries the state of the facts sourced from it, for example `[SUPERSEDED by Amendment-1, p.2]`, so the model does not present superseded facts as current.

### 9.3 Hybrid search (dense + full-text, Reciprocal Rank Fusion)

```sql
-- $1 query embedding, $2 matter_id, $3 question text, $4 as-of batch
-- Run inside a transaction. pgvector >= 0.8: keep scanning the HNSW index
-- until enough rows pass the matter filter.
SET LOCAL hnsw.iterative_scan = relaxed_order;

WITH q AS (
    -- OR the terms together: plainto_tsquery ANDs them, which drops most
    -- natural-language questions. 'simple' keeps identifiers such as INV-014 and 12A.
    SELECT replace(plainto_tsquery('english', $3)::text, '&', '|')::tsquery
        || replace(plainto_tsquery('simple',  $3)::text, '&', '|')::tsquery AS tsq
),
vector_matches AS (
    SELECT chunk_id,
           ROW_NUMBER() OVER (ORDER BY dense_embedding <=> $1::vector) AS rank_vec
    FROM document_chunks
    WHERE matter_id = $2
      AND chunk_level = 'CHILD'
      AND batch_seq <= $4
    ORDER BY dense_embedding <=> $1::vector
    LIMIT 30
),
lexical_matches AS (
    SELECT c.chunk_id,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC) AS rank_lex
    FROM document_chunks c, q
    WHERE c.matter_id = $2
      AND c.chunk_level = 'CHILD'
      AND c.batch_seq <= $4
      AND c.tsv @@ q.tsq
    ORDER BY rank_lex
    LIMIT 30
),
fused AS (
    SELECT chunk_id, SUM(score) AS rrf_score
    FROM (
        SELECT chunk_id, 1.0 / (60 + rank_vec) AS score FROM vector_matches
        UNION ALL
        SELECT chunk_id, 1.0 / (60 + rank_lex) FROM lexical_matches
    ) s
    GROUP BY chunk_id
)
SELECT c.chunk_id, c.parent_chunk_id, c.document_id, c.page_start,
       c.structural_ref, c.chunk_text, f.rrf_score
FROM fused f
JOIN document_chunks c USING (chunk_id)
ORDER BY f.rrf_score DESC
LIMIT 30;
```

The top 30 fused chunks are reranked by bge-reranker-v2-m3; the best 8 go forward, expanded to their parent sections.

### 9.4 Hearing brief template
The brief is generated section by section (in parallel, each section verified separately), then assembled as Markdown. PDF export uses the browser's print function.

| Section | Fed by plans | Content |
| :--- | :--- | :--- |
| 1. Matter snapshot | 1 | Parties, forum, case number, stage, next hearing date |
| 2. Current position | 1, 3 | Each side's claims, defences and relief as they stand now |
| 3. Issues in dispute | 3, 4 | Each disputed key: both versions with sources |
| 4. Evidence for and against | 4 | Per issue: supporting and contradicting evidence |
| 5. Directions and compliance | 5 | Due, overdue and complied directions; undertakings |
| 6. Changes since the last hearing | 6 | What-Changed rows since the batch before the last hearing |
| 7. Authorities | 7 | Statutes and judgments with section or paragraph and source link |
| 8. Open risks and to-do | 3, 4, 5 | Missing evidence, pending directions, review-queue items |

---

## 10. Grounding and Citation Verification

| Step | What happens |
| :--- | :--- |
| 1. Retrieve | The plan returns evidence spans and facts, each with an ID |
| 2. Generate | Qwen3-8B returns JSON: one entry per sentence, listing the IDs it relies on and a short verbatim quote. Temperature 0 |
| 3. Verify (code) | (a) every cited ID was in the retrieved set; (b) the quote matches the cited page's text (fuzzy ≥ 90); (c) every number and date in the sentence appears, after normalisation, in the cited span or fact value; (d) a sentence citing only superseded facts is allowed only in change and chronology views |
| 4. Filter | Sentences that fail are removed from the answer and listed in the trace as "could not verify" |
| 5. Render | Each citation opens the PDF page with the span highlighted |

**When evidence is missing, the answer says so.** Example: *"Q: When was INV-014 paid in full? A: Not found. ₹6,00,000 was paid on 14 Mar 2025 (Bank statement, p.2). No record shows the balance of ₹12,40,000 being paid."*

**Legal authorities are never quoted from model memory.** Every statute or judgment citation must match a row in `legal_corpus.sources`; anything else is removed.

**Why in code:** a wrong page reference costs more than a shorter answer. ID and string checks are deterministic, fast, need no extra GPU memory, and are logged for every answer.

---

## 11. Public Legal Corpus

**Structure** (separate `legal_corpus` schema, §15):
1. **Statutes:** one passage per section; Act, section number, heading and India Code link.
2. **Judgments:** one passage per numbered paragraph; court, date, paragraph number, citation and source (SCR or eCourts).
3. **Issue tags**, e.g. time_essence, delay, liquidated_damages, penalty, part_payment, recovery_of_price, interest, service_of_notice, termination, cure_period, interim_injunction, specific_performance, arbitration_clause, interim_measures, pre_institution_mediation, summary_suit, summary_judgment, amendment_of_pleadings.
4. **Treatment note:** for example, a later amendment or judgment that narrows an authority.
5. **Verification:** every source records who verified it against the official text, and when.

Disputed slots map to issue tags in code (e.g. `notice/*/received` → service_of_notice; a delivery-date dispute → time_essence, delay), so Plan 7 searches the right authorities.

| Archetype | Starting provisions (confirm against India Code) |
| :--- | :--- |
| Breach / non-performance | Indian Contract Act ss.39, 55, 62, 73, 74; Specific Relief Act ss.10, 14, 20 |
| Payment / recovery | Indian Contract Act ss.73, 74; CPC Order XXXVII (summary suits), Order XIII-A (summary judgment, commercial disputes); Commercial Courts Act ss.2(1)(c), 12A |
| Termination / injunction | Specific Relief Act ss.14, 41, 42; CPC Order XXXIX Rules 1–2; Arbitration and Conciliation Act ss.8, 9, 11 where the contract has an arbitration clause |
| Procedure (all) | CPC Order VI Rule 17 (amendment of pleadings), Order VII Rule 11, Order VIII Rule 1; General Clauses Act 1897 s.10 (computation of time) |

**Candidate judgments** (each must be verified on SCR or eCourts before loading, with citation and paragraph numbers recorded at load time):
- *Kailash Nath Associates v. DDA*: s.74, stipulated damages and proof of loss.
- *ONGC v. Saw Pipes*: ss.73–74. Treatment note: its public-policy reasoning was narrowed by the 2015 amendment to s.34 of the Arbitration Act.
- *Hind Construction Contractors v. State of Maharashtra*; *Welspun Specialty Solutions v. ONGC*: time as the essence (s.55).
- *Patil Automation v. Rakheja Engineers*: s.12A pre-institution mediation is mandatory.
- *Dalpat Kumar v. Prahlad Singh*: tests for temporary injunctions (Order XXXIX).
- *Indian Oil Corporation v. Amritsar Gas Service*: termination of a determinable contract; no specific performance.

The corpus stays small. The goal is legal grounding, not an all-India search engine (brief §2).

---

## 12. Model Stack and Serving

### 12.1 Baseline models (frozen after the Day-3 benchmark)

| Role | Model | Licence | Runs on | Why |
| :--- | :--- | :--- | :--- | :--- |
| Main LLM: extraction, answers, hearing brief | Qwen3-8B (8.2B) | Apache-2.0 | AI node | Largest model within the track formula; strong JSON and instruction following; 32K native context |
| Fast LLM: router, classifier, standby | Qwen3-4B (4.0B) | Apache-2.0 | App node | Fast routing; same family, so it can stand in for the 8B model |
| Embeddings | BAAI/bge-m3 (0.57B, 1024-dim dense) | MIT | App node | Strong multilingual dense retrieval; exact terms come from PostgreSQL full-text |
| Reranker | BAAI/bge-reranker-v2-m3 (0.57B) | Apache-2.0 | App node | Served by TEI's `/rerank`; challenger on Day 3: Qwen3-Reranker-0.6B |
| Parsing and OCR | pypdfium2, pdfplumber, Docling, Tesseract | Apache / BSD / MIT | App node CPU | §7.2 |
| Serving | vLLM; Text Embeddings Inference | Apache-2.0 | Both nodes | OpenAI-compatible API; JSON-schema output |

**Not chosen:** legal fine-tunes of small models (unverified quality; often trained on criminal law, which is out of scope); Qwen3.5-9B, gpt-oss-20b and Qwen3.6-35B (over 24 GB by the formula); Llama models (licence, C4); InLegalBERT and OpenNyAI models (no role in this pipeline).

### 12.2 GPU memory budget

| Node | Allocation | Total |
| :--- | :--- | :--- |
| AI node (A10G, 24 GB) | Qwen3-8B BF16 weights ≈ 16.4 GB + KV cache and runtime (vLLM `--gpu-memory-utilization 0.90`) | ≈ 21.6 GB. Track formula: 8.2 × 2.2 + 5 = 23.0 GB ≤ 24 GB |
| App node (A10G, 24 GB) | Qwen3-4B BF16 ≈ 8 GB weights + KV cache (`0.50` → 12 GB); BGE-M3 ≈ 1.3 GB; reranker ≈ 1.3 GB | ≈ 16.4 GB |

### 12.3 Serving configuration
Pin exact image tags after the Day-3 benchmark; never deploy `:latest`.

```bash
# AI node: main model (reachable only from the App node's security group)
docker run -d --gpus all --name vllm-main -p 8000:8000 \
    -v /opt/models:/models \
    -e VLLM_API_KEY \
    vllm/vllm-openai:<pinned-tag> \
    --model /models/Qwen3-8B \
    --served-model-name qwen3-8b \
    --dtype bfloat16 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching

# App node: fast model, embeddings, reranker (bound to localhost)
docker run -d --gpus all --name vllm-fast -p 127.0.0.1:8001:8000 \
    -v /opt/models:/models \
    vllm/vllm-openai:<pinned-tag> \
    --model /models/Qwen3-4B \
    --served-model-name qwen3-4b \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.50 \
    --enable-prefix-caching

# The "86-" image prefix is the TEI build for A10G (compute capability 8.6)
docker run -d --gpus all --name tei-embed -p 127.0.0.1:8080:80 \
    -v /opt/models:/data \
    ghcr.io/huggingface/text-embeddings-inference:86-<pinned-version> \
    --model-id /data/bge-m3

docker run -d --gpus all --name tei-rerank -p 127.0.0.1:8081:80 \
    -v /opt/models:/data \
    ghcr.io/huggingface/text-embeddings-inference:86-<pinned-version> \
    --model-id /data/bge-reranker-v2-m3
```

Model weights are read from `/opt/models`, synced from S3, so neither node needs internet access at run time.

Every LLM call uses temperature 0, turns Qwen3 thinking mode off, and requests JSON-schema output:

```python
response = client.chat.completions.create(
    model="qwen3-8b",
    messages=messages,
    temperature=0,
    response_format={"type": "json_schema", "json_schema": {"name": "extraction", "schema": schema}},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```

**Prefix caching:** extraction prompts share long fixed instructions per document type, so vLLM reuses their cached computation across sections.

**Standby:** if the AI node fails its health check, the orchestrator routes answers to Qwen3-4B with a smaller context (top 5 parent sections). The UI shows a "standby model" badge.

### 12.4 Day-3 benchmark
Measured on our synthetic matters: JSON validity rate, slot extraction accuracy against gold slots, ingestion time per 20 pages, answer accuracy on 20 golden questions, reranker Recall@10. The results freeze the model line-up, image tags and context sizes.

---

## 13. Deployment, Security and Operations

### 13.1 Network and storage

| Item | Configuration |
| :--- | :--- |
| VPC | One VPC in us-east-1; public subnet (App node), private subnet (AI node) |
| App node | Elastic IP; SG allows 443 from allow-listed IPs (team and judges) and 22 from team IPs only |
| AI node | No public IP; SG allows 8000 from the App node's SG only; vLLM API key as a second check |
| S3 access | S3 gateway endpoint (free) for both nodes |
| Egress for the AI node | Model weights and container images staged through S3 (`docker save` on the App node, `docker load` on the AI node). A NAT gateway is created only for setup or patching windows, then deleted |
| EBS | gp3, encrypted. App root 200 GB; PostgreSQL data on its own 100 GB volume with `DeleteOnTermination = false`; AI root 100 GB |
| S3 | Encrypted, versioned, public access blocked: `originals/`, `models/`, `images/`, `backups/` |
| DNS / TLS | Route 53 record; Let's Encrypt certificate on Nginx |

### 13.2 Security controls
- IAM instance roles with least privilege; no access keys on servers.
- Secrets from GitHub secrets into a root-only environment file.
- Team login (JWT); every query is scoped to one `matter_id`.
- Document text is treated as untrusted data (§7.5).
- Only synthetic and public documents are used; no client data.

### 13.3 Operations
1. **CI on every pull request:** ruff, mypy, eslint, tsc, pytest, vitest; unit tests for the normaliser, key builder, authority rules and deadline calculator.
2. **Deploy script:** git pull, build images on the server, run migrations, health checks, then a 20-question evaluation smoke test against the deployed stack. GPU tests cannot run in CI, so they run here.
3. **Infrastructure runbook:** AWS CLI script in Git for VPC, subnets, security groups, IAM, S3 and the gateway endpoint.
4. **Observability:** JSON logs; `query_traces` (plan, retrieved IDs, citation checks, timings, model versions); per-stage timings in `ingestion_jobs`.
5. **Backups:** nightly `pg_dump` to S3; EBS snapshots before each judging round; one restore drill in Week 4.
6. **Freeze:** code freeze on Day 28.
7. **First-time setup:** plan for half a day (weight downloads, image builds, corpus load), not minutes.

### 13.4 Cost controls
- **Auto-stop:** a systemd timer on each node stops the instance after 60 minutes with no requests and no running jobs. The IAM permission is limited to the instance itself. Auto-stop is switched off during judging windows.
- **AWS Budgets:** alerts at $1,000, $1,600 and $2,200. A budget action at $2,200 stops both nodes; check it before judging day.
- **Day 1:** confirm the EC2 quota for G instances (24 vCPUs for both nodes) and that both nodes start.

---

## 14. Cost Plan (30 days)

| Item | Basis | Cost (USD) |
| :--- | :--- | :--- |
| AI node `g5.4xlarge` | 408 h × $1.624/h | $663 |
| App node `g5.2xlarge` | 408 h × $1.212/h | $494 |
| EBS gp3, 400 GB | $0.08 per GB-month | $32 |
| NAT gateway | Setup and patching windows only | $5 |
| S3, snapshots, data transfer | Estimate | $20 |
| Route 53 | One hosted zone | $1 |
| **Subtotal** | | **$1,215** |
| Contingency | 25% | $304 |
| **Planned total** | | **≈ $1,520 of $3,000** |

- **Hours:** 408 h per node averages about 13.6 h/day; auto-stop enforces it.
- **Worst case**, both nodes on 24/7 for 30 days: 730 h × ($1.624 + $1.212) ≈ $2,070 of compute, about $2,130 in total. Still under $3,000, so the $7,000 extension is not needed.
- **Prices:** on-demand us-east-1 rates as used in the team deck. Confirm them in the AWS Pricing Calculator.
- **Saving against the deck plan:** about $60 (no permanent NAT gateway; 400 GB instead of 500 GB EBS).

---

## 15. Database Schema (PostgreSQL 16 + pgvector ≥ 0.8)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- gen_random_uuid() is built into PostgreSQL 13+; no uuid extension is needed.

-- 1. MATTERS
CREATE TABLE matters (
    matter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_number VARCHAR(100) UNIQUE NOT NULL, -- e.g. 'CS(COMM) 123/2025'
    title TEXT NOT NULL,
    matter_type VARCHAR(30) NOT NULL
        CHECK (matter_type IN ('BREACH', 'PAYMENT_RECOVERY', 'TERMINATION_INJUNCTION')),
    current_forum VARCHAR(150), -- e.g. 'High Court of Delhi, Commercial Division'
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. PARTIES AND ALIASES
CREATE TABLE parties (
    party_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    canonical_name TEXT NOT NULL, -- 'Kestrel Ltd'
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('PLAINTIFF', 'DEFENDANT', 'PETITIONER', 'RESPONDENT', 'OTHER')),
    UNIQUE (matter_id, canonical_name)
);

CREATE TABLE party_aliases (
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    alias_normalised TEXT NOT NULL, -- 'defendant no. 1', 'kestrel limited', 'the customer'
    party_id UUID NOT NULL REFERENCES parties(party_id) ON DELETE CASCADE,
    PRIMARY KEY (matter_id, alias_normalised)
);

-- 3. INGESTION BATCHES (one row per upload round; Section 8.5)
CREATE TABLE ingestion_batches (
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL CHECK (batch_seq >= 1), -- 1 = initial documents, 2 = first additional set
    label TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'PROCESSING', 'COMMITTED', 'FAILED')),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at TIMESTAMPTZ,
    PRIMARY KEY (matter_id, batch_seq)
);

-- 4. DOCUMENTS
CREATE TABLE documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL,
    title TEXT NOT NULL,
    document_type VARCHAR(30) NOT NULL,   -- Section 7.3
    authority_class VARCHAR(20) NOT NULL
        CHECK (authority_class IN ('BILATERAL', 'COURT', 'PLEADING', 'SWORN', 'NOTICE',
                                   'RECORD', 'CORRESPONDENCE', 'INTERNAL')),
    document_date DATE,                   -- execution, filing, sending or order date
    author_party_id UUID REFERENCES parties(party_id), -- NULL for court orders and bilateral documents
    signed_by_all_parties BOOLEAN NOT NULL DEFAULT FALSE,
    classification_confidence REAL,
    s3_uri TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    total_pages INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'FAILED')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    UNIQUE (matter_id, sha256) -- a re-uploaded file is skipped, never ingested twice
);

-- 5. PAGES (page text for citation checks and the PDF viewer)
CREATE TABLE document_pages (
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    page_text TEXT NOT NULL,
    extraction_method VARCHAR(10) NOT NULL CHECK (extraction_method IN ('DIGITAL', 'DOCLING', 'OCR')),
    ocr_confidence REAL, -- NULL for digital pages; low values flagged in the UI
    PRIMARY KEY (document_id, page_number)
);

-- 6. CHUNKS (evidence layer: hybrid vector + full-text)
CREATE TABLE document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL, -- copied from documents; lets retrieval target "new evidence in Batch N"
    parent_chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE CASCADE, -- small-to-big
    chunk_level VARCHAR(10) NOT NULL CHECK (chunk_level IN ('PARENT', 'CHILD')),
    structural_ref VARCHAR(50),  -- 'cl. 4.2', '¶12', 'Direction 3', 'Email 4'
    heading TEXT,
    context_header TEXT NOT NULL, -- '[MSA | 12 Jan 2023 | Vardhan v Kestrel | cl. 4.2]'
    chunk_text TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    char_start INTEGER NOT NULL, -- offset in page_start's text
    char_end INTEGER NOT NULL,   -- offset in page_end's text
    bboxes JSONB,                -- [{"page": 4, "x0": 50, "y0": 120, "x1": 540, "y1": 380}]
    token_count INTEGER NOT NULL,
    dense_embedding vector(1024), -- BGE-M3 over context_header + chunk_text; CHILD chunks only
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', chunk_text) || to_tsvector('simple', chunk_text)
    ) STORED,
    CHECK (page_end >= page_start)
);

CREATE INDEX idx_chunks_hnsw ON document_chunks
    USING hnsw (dense_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_tsv ON document_chunks USING gin (tsv);
CREATE INDEX idx_chunks_matter ON document_chunks (matter_id, document_id, page_start);

-- 7. FACTS (knowledge layer)
--   effective_from / effective_to             : real-world time
--   learned_in_batch_seq / ended_in_batch_seq : batch time
-- Facts are never deleted. Replacing a fact = ending it + linking to its replacement.
CREATE TABLE matter_fact_assertions (
    assertion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,       -- built by code, e.g. 'contract/msa-2023/delivery_date' (Section 8.2)
    slot VARCHAR(60) NOT NULL,    -- from the fixed slot list
    assertion_category VARCHAR(20) NOT NULL
        CHECK (assertion_category IN ('TERM', 'CLAIM', 'COUNTERCLAIM', 'DEFENCE', 'DENIAL', 'ADMISSION',
                                      'RELIEF_SOUGHT', 'PAYMENT', 'EVENT_FACT', 'DIRECTION', 'UNDERTAKING')),
    asserting_party_id UUID REFERENCES parties(party_id), -- NULL for bilateral documents and orders
    assertion_text TEXT NOT NULL, -- readable sentence shown to users
    value_text TEXT,
    value_date DATE,
    value_amount NUMERIC(15, 2),  -- rupees, normalised in code
    value_bool BOOLEAN,
    originating_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,
    source_page INTEGER NOT NULL,
    source_quote TEXT NOT NULL,   -- verbatim span, checked against the page before commit
    assertion_date DATE,          -- date of the statement itself, e.g. plaint filing date
    effective_from DATE,          -- NULL when the document gives no effective date
    effective_to DATE,
    learned_in_batch_seq INTEGER NOT NULL,
    ended_in_batch_seq INTEGER,   -- NULL while the fact is current (ACTIVE or DISPUTED)
    state VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (state IN ('ACTIVE', 'DISPUTED', 'SUPERSEDED', 'WITHDRAWN')),
    evidence_only BOOLEAN NOT NULL DEFAULT FALSE, -- rules R1, R7, R8: shown as evidence, never as current position
    superseded_by_assertion_id UUID REFERENCES matter_fact_assertions(assertion_id),
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, learned_in_batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    FOREIGN KEY (matter_id, ended_in_batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    -- equal when a fact is learned and replaced in the same batch (e.g. contract + amendment together)
    CHECK (ended_in_batch_seq IS NULL OR ended_in_batch_seq >= learned_in_batch_seq),
    CHECK ((state IN ('SUPERSEDED', 'WITHDRAWN')) = (ended_in_batch_seq IS NOT NULL))
);

CREATE INDEX idx_facts_current_key ON matter_fact_assertions (matter_id, fact_key)
    WHERE ended_in_batch_seq IS NULL;
CREATE INDEX idx_facts_review ON matter_fact_assertions (matter_id)
    WHERE needs_review;

-- 8. BATCH LEDGER (time layer). Every fact gets a 'NEW' row in the batch it was learned in.
CREATE TABLE fact_change_log (
    change_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, -- also gives a stable order
    matter_id UUID NOT NULL,
    batch_seq INTEGER NOT NULL,
    assertion_id UUID NOT NULL REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    change_type VARCHAR(30) NOT NULL
        CHECK (change_type IN ('NEW', 'SUPERSEDED', 'NARROWED', 'DISPUTED',
                               'CONTRADICTED_BY_EVIDENCE', 'CORROBORATED', 'WITHDRAWN', 'COMPLIED')),
    previous_state VARCHAR(20), -- NULL for 'NEW'
    new_state VARCHAR(20) NOT NULL,
    related_assertion_id UUID REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    caused_by_document_id UUID REFERENCES documents(document_id) ON DELETE CASCADE, -- NULL for manual review
    rule_id VARCHAR(10) NOT NULL, -- 'R0'..'R9' (Section 8.3) or 'MANUAL'
    reviewer TEXT,                -- set when rule_id = 'MANUAL'
    reason TEXT,                  -- e.g. 'Amendment-1, signed by both parties, varies MSA cl. 4.2'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE
);

CREATE INDEX idx_change_log_batch ON fact_change_log (matter_id, batch_seq);
CREATE INDEX idx_change_log_assertion ON fact_change_log (assertion_id, batch_seq);

-- 9. EVIDENCE LINKS (claims board: for and against)
CREATE TABLE fact_links (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    assertion_id UUID NOT NULL REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    link_type VARCHAR(20) NOT NULL CHECK (link_type IN ('SUPPORTS', 'CONTRADICTS', 'SUPERSEDES')),
    target_assertion_id UUID REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    target_chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL,
    rule_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(target_assertion_id, target_chunk_id) = 1)
);

CREATE INDEX idx_links_assertion ON fact_links (assertion_id, link_type);

-- 10. EVENTS (chronology)
CREATE TABLE matter_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    date_precision VARCHAR(10) NOT NULL DEFAULT 'DAY' CHECK (date_precision IN ('DAY', 'MONTH', 'YEAR')),
    event_type VARCHAR(40) NOT NULL, -- 'CONTRACT_SIGNED', 'DELIVERY', 'INVOICE_RAISED', 'PAYMENT',
                                     -- 'NOTICE_SENT', 'SUIT_FILED', 'ORDER_PASSED', 'HEARING'
    description TEXT NOT NULL,
    party_id UUID REFERENCES parties(party_id),
    assertion_id UUID REFERENCES matter_fact_assertions(assertion_id) ON DELETE SET NULL,
        -- when set, the event shows that fact's state (struck through if superseded, flagged if disputed)
    source_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_page INTEGER NOT NULL,
    learned_in_batch_seq INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_events_matter_date ON matter_events (matter_id, event_date);

-- 11. COURT DIRECTIONS, DEADLINES AND UNDERTAKINGS (Section 8.6)
-- Current or superseded status comes from the linked fact.
CREATE TABLE court_directions (
    direction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    assertion_id UUID NOT NULL UNIQUE REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    order_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    order_date DATE NOT NULL,
    direction_ref VARCHAR(30), -- 'Direction 3', '¶5'
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('DIRECTION', 'UNDERTAKING', 'INTERIM_RELIEF', 'NEXT_HEARING')),
    procedural_step VARCHAR(40) NOT NULL, -- fixed list in Section 8.6
    direction_text TEXT NOT NULL,
    responsible_party_id UUID REFERENCES parties(party_id),
    period_text TEXT,        -- verbatim: 'within four weeks from today'
    period_days INTEGER,     -- normalised by code: 28
    period_months INTEGER,
    trigger_date DATE,       -- usually the order date
    due_date DATE,           -- computed by code, never by the model
    compliance_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (compliance_status IN ('PENDING', 'COMPLIED', 'NOT_APPLICABLE')),
    complied_by_document_id UUID REFERENCES documents(document_id),
    source_page INTEGER NOT NULL
);

CREATE INDEX idx_directions_due ON court_directions (matter_id, due_date);

-- 12. PUBLIC LEGAL CORPUS (separate schema, never mixed with matter facts)
CREATE SCHEMA IF NOT EXISTS legal_corpus;

CREATE TABLE legal_corpus.sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(10) NOT NULL CHECK (source_type IN ('STATUTE', 'JUDGMENT')),
    title TEXT NOT NULL,         -- 'Indian Contract Act, 1872' or the case name
    citation TEXT,               -- recorded from SCR or eCourts at load time
    court VARCHAR(150),
    decision_date DATE,
    source_url TEXT NOT NULL,    -- India Code, SCR or eCourts
    treatment_note TEXT,         -- later amendment or judgment that narrows it
    verified_by TEXT NOT NULL,
    verified_on DATE NOT NULL
);

CREATE TABLE legal_corpus.passages (
    passage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES legal_corpus.sources(source_id) ON DELETE CASCADE,
    section_ref VARCHAR(50),     -- 's.74', 'Order XXXIX r.1'
    paragraph_number INTEGER,    -- judgments
    heading TEXT,
    content TEXT NOT NULL,
    issue_tags TEXT[] NOT NULL DEFAULT '{}',
    dense_embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', content) || to_tsvector('simple', content)
    ) STORED
);

CREATE INDEX idx_corpus_hnsw ON legal_corpus.passages USING hnsw (dense_embedding vector_cosine_ops);
CREATE INDEX idx_corpus_tsv ON legal_corpus.passages USING gin (tsv);
CREATE INDEX idx_corpus_tags ON legal_corpus.passages USING gin (issue_tags);

-- 13. JOB QUEUE (PostgreSQL, FOR UPDATE SKIP LOCKED)
CREATE TABLE ingestion_jobs (
    job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    stage VARCHAR(20) NOT NULL CHECK (stage IN ('PARSE', 'EXTRACT', 'RECONCILE')),
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_jobs_queued ON ingestion_jobs (job_id) WHERE status = 'QUEUED';

-- 14. QUERY TRACES (retrieval trace in the UI; observability)
CREATE TABLE query_traces (
    trace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    as_of_batch_seq INTEGER NOT NULL,
    question TEXT NOT NULL,
    intents TEXT[] NOT NULL,
    routed_by VARCHAR(10) NOT NULL CHECK (routed_by IN ('RULES', 'MODEL')),
    plans JSONB NOT NULL,           -- typed retrieval plans executed
    retrieved JSONB NOT NULL,       -- chunk and fact IDs with scores
    citation_checks JSONB NOT NULL, -- per sentence: pass or fail, and why
    timings_ms JSONB NOT NULL,
    model_versions JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Worker claim query** (each worker takes one job; a job locked by another worker is skipped):

```sql
UPDATE ingestion_jobs
SET status = 'RUNNING', locked_at = now(), attempts = attempts + 1
WHERE job_id = (
    SELECT job_id
    FROM ingestion_jobs
    WHERE status = 'QUEUED'
    ORDER BY job_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING job_id, document_id, stage;
```

---

## 16. API (FastAPI, `/api/v1`)

| Method | Path | Purpose |
| :--- | :--- | :--- |
| POST | `/matters` | Create a matter: title, type, parties with roles and aliases |
| GET | `/matters`, `/matters/{matter_id}` | List or open matters |
| POST | `/matters/{matter_id}/batches` | Open a new batch; returns `batch_seq` |
| POST | `/matters/{matter_id}/batches/{batch_seq}/documents` | Upload a file (multipart; optional type hint). 202 accepted; 409 duplicate (same SHA-256) |
| POST | `/matters/{matter_id}/batches/{batch_seq}/commit` | Close the batch; the report is built when processing finishes |
| GET | `/matters/{matter_id}/batches/{batch_seq}` | Batch status per document |
| GET | `/matters/{matter_id}/batches/{batch_seq}/changes` | What-Changed Report |
| GET | `/matters/{matter_id}/gist?as_of=N` | Current position (Plan 1) |
| GET | `/matters/{matter_id}/chronology?as_of=N` | Timeline (Plan 2) |
| GET | `/matters/{matter_id}/claims?party_id=` | Claims board (Plans 3–4) |
| GET | `/matters/{matter_id}/directions?status=` | Directions and deadlines (Plan 5) |
| POST | `/matters/{matter_id}/ask` | Question with optional `as_of_batch_seq` and `intent_hint` (router decides otherwise) |
| POST | `/matters/{matter_id}/hearing-brief` | Generate the hearing brief (§9.4) |
| GET | `/matters/{matter_id}/review-queue` | Items needing review |
| POST | `/facts/{assertion_id}/review` | Resolve a review item; writes a `MANUAL` ledger row |
| GET | `/legal/search?q=&tags=` | Search the legal corpus |
| GET | `/documents/{document_id}/pages/{page}` | Page image and text for the viewer |
| GET | `/traces/{trace_id}` | Retrieval trace |
| GET | `/healthz` | Health of the API, database, both model servers and TEI |

**`POST /ask` response**

```json
{
  "answer_sentences": [
    {
      "text": "Delivery was due on 31 July 2024.",
      "status": "VERIFIED",
      "citations": [
        {
          "document_id": "uuid",
          "document_title": "Amendment-1",
          "page": 2,
          "structural_ref": "cl. 1",
          "quote": "The Go-Live Date shall be 31 July 2024"
        }
      ]
    }
  ],
  "not_found": [],
  "superseded_notes": [
    { "fact": "Delivery due 30 Jun 2024", "superseded_by": "Amendment-1, p.2", "batch_seq": 2 }
  ],
  "as_of_batch_seq": 2,
  "intents": ["FACTUAL_QA"],
  "trace_id": "uuid"
}
```

**`GET /changes` response:** `batch_seq`, `documents_processed`, `documents_failed[]`, `duplicates_skipped[]`, and `changes[]`, each with `change_type`, `rule_id`, `before`, `after`, `reason`, `source_document_title` and `page`.

---

## 17. User Interface

| View | Shows |
| :--- | :--- |
| Matters and upload | Create or open a matter; upload a batch; per-document progress; commit button |
| Gist | Current position, each sentence cited |
| Chronology | Dated timeline; superseded items struck through with the replacing document; disputed items with both versions |
| Claims board | Per party: claims, counterclaims, defences, relief; evidence for and against each |
| Directions | Due, overdue and complied directions with computed dates; undertakings |
| What changed | Report per batch; "view as of batch N" selector |
| Legal research | Authorities with section or paragraph and source link |
| Hearing brief | The template in §9.4; export to Markdown or PDF |
| Q&A | Questions with verified citations and "not found" answers |
| Review queue | Items needing a person (§8.7) |
| Retrieval trace | Plan chosen, items retrieved, citation checks, timings |
| PDF viewer | Click any citation to open the page with the span highlighted (pdf.js) |

---

## 18. Evaluation and Testing

### 18.1 Synthetic development matters (brief §5)

| Matter | Archetype | Batches | Typical documents |
| :--- | :--- | :--- | :--- |
| M1 | Breach / non-performance | 3 | MSA, SOW, change requests, delay emails, LD notice, plaint, written statement, order |
| M2 | Payment / recovery (Vardhan v Kestrel) | 2 | MSA, amendment, invoices, bank statement, legal notice, plaint, written statement, order |
| M3 | Termination / injunction | 3 | Distribution agreement with arbitration clause, cure notice, termination letter, Order XXXIX application, affidavit, interim order |
| M4 (held-out) | Any | 2–3 | Written by someone outside the extraction team; used only for final checks |

Across M1–M3, **each authority rule R0–R9 is planted at least once**, plus at least one duplicate upload, one scanned page and one direction whose trigger date is "from receipt of copy".

### 18.2 Golden set format

```yaml
- id: M2-B2-Q03
  batch: 2
  question: "How much is still unpaid on INV-014?"
  expected_facts: ["invoice/inv-014/amount_outstanding = 1240000"]
  expected_citations: [{ document: "Bank statement", page: 2 }]
  must_not_say: ["18,40,000 is unpaid"]   # superseded value presented as current
```

### 18.3 Tests and targets

| Test | Target |
| :--- | :--- |
| Golden Q&A, scripted checker | ≥ 90% correct on M4 |
| Citation precision (automated span check + manual sample of 50) | ≥ 95% |
| Planted changes detected with the correct rule | ≥ 90%; 0 superseded facts presented as current |
| Batch replay with timer | All documents in; ≤ 2 min per 20 digital pages |
| Duplicate upload | 0 duplicate facts |
| Chronology against gold timeline | ≥ 90% events correct |
| Retrieval Recall@10 on labelled chunks | ≥ 0.85 |
| Unanswerable questions | 100% answered "not found" |
| Out-of-scope question (e.g. criminal law) | Politely declined |

### 18.4 Automated tests
- **Unit (CI):** amount, date and period normaliser; key builder; authority rules (one table-driven test per rule); deadline calculator; citation verifier.
- **Integration (after deploy):** replay M1–M3 batch by batch; compare each What-Changed Report with the planted changes.
- **Evaluation smoke (after deploy):** 20 golden questions.
- **Rehearsals:** three full three-round dry runs in Week 4, the last on M4.

---

## 19. Delivery Plan (30 days)

| Week | Focus | Work | Exit test |
| :--- | :--- | :--- | :--- |
| 1 (Days 1–7) | Foundations | Day 1: GPU quota and both nodes up; infra runbook; CI skeleton; schema migrations. Day 3: model benchmark, freeze line-up and tags. Slot list and authority rules signed off. Synthetic matters, golden set, legal corpus loaded and verified | One matter answers one question end to end with a verified citation |
| 2 (Days 8–14) | Round 1 ready | Parse, chunk, embed; extraction, normalisation and keys; router with Plans 1–4; UI shell (matters, batch upload, Q&A, PDF viewer) | Round-1 questions answered with citations on our matters |
| 3 (Days 15–21) | Round 2 ready | Reconcile with authority rules; ledger and What-Changed; directions and deadlines; Plans 5–8; citation verifier; review queue | Round-2 replay detects all planted changes |
| 4 (Days 22–30) | Demo ready | Hearing brief; ingestion performance; evaluation hardening on M4; code freeze Day 28; restore drill; snapshots; 3 rehearsals | Full three-round dry run on M4 |

---

## 20. Risks

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| AI node down during the demo | High | Qwen3-4B standby on the App node; health checks; GPU kept warm; auto-stop off during judging |
| Wrong supersede or dispute call | High | Authority rules in code; conservative defaults (low confidence → lowest authority); review queue; one test per rule |
| Live ingestion too slow | High | Parallel documents; classification on the App node while the AI node extracts; thinking mode off; Day-3 benchmark |
| 8B model weaker at extraction | High | JSON schema, one prompt and examples per document type, normalisation in code, quote check on every item |
| Unseen matter has facts outside the slot list | Medium | Generic slots across all archetypes; `other` slot goes to the review queue; M4 written by an outsider |
| Hallucinated citations | Medium | Code verification; "not found" answers; legal citations only from the corpus |
| Database on the App node | Medium | Separate data volume kept on termination; nightly backups; snapshots before judging; restore drill |
| Overfitting to our own matters | Medium | Held-out M4; no matter-specific rules or prompts |
| Prompt injection inside documents | Medium | Document text treated as data; schema-constrained outputs; outcomes decided by code |
| Network rules at the judging venue | Medium | S3 staging needs no internet; allow-list judges' IPs in advance |
| Budget overrun | Low | Auto-stop; Budgets alerts and stop action; worst case stays under $3,000 |
| Scanned or poor-quality PDFs | Low | Tesseract fallback; low-confidence pages flagged |

---

## 21. Open Questions for the Organisers

1. Which formats will the judges' documents be in: scanned PDF, DOCX, EML, MSG?
2. How are batches delivered, and how long do we get to ingest each one?
3. Is a NAT gateway acceptable, or must model weights be staged through S3? (Our default is S3 staging.)
4. Could documents include Hindi or other languages?
5. Is there a required format for the hearing brief?
6. From which network or IP range will judges access the system?
7. Does the 24 GB GPU track formula apply per node?

---

## 22. Glossary

| Term | Meaning |
| :--- | :--- |
| Batch | One upload round of documents for a matter (Batch 1, Batch 2, ...) |
| Batch time | The batch in which the system learned a fact, or stopped treating it as current |
| Slot | A fixed box the model fills from a document, e.g. `delivery_date` |
| Fact key | An address built by code from subject + slot, e.g. `invoice/inv-014/amount_outstanding`; facts about the same thing share a key |
| Authority class | What kind of document it is legally (bilateral agreement, court order, pleading, record, ...) and therefore what it may change |
| Supersede | Replace an earlier fact, e.g. a signed amendment replacing a contract term |
| Dispute | Keep both versions because the parties disagree; the court decides |
| Ledger | `fact_change_log`: one row for every change to the system's understanding |
| As-of view | What the system believed after a given batch |
| Chunk | A piece of a document (a clause, a paragraph) stored with its page and position |
| Small-to-big | Search small chunks, then give the model the larger section around them |
| RRF | Reciprocal Rank Fusion: merges dense-vector and full-text results by rank |
| Reranker | A model that re-orders search results by relevance to the question |
| vLLM / TEI | Servers that run the language models / the embedding and reranking models |
| pgvector | PostgreSQL extension for storing and searching vectors |
