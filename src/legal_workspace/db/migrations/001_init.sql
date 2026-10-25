-- Legal Workspace schema v1 (blueprint v3 §15 + additions; see docs/sections/S02-data-layer).
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. MATTERS -------------------------------------------------------------------------------------
CREATE TABLE matters (
    matter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_number VARCHAR(100) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    matter_type VARCHAR(30) NOT NULL
        CHECK (matter_type IN ('BREACH', 'PAYMENT_RECOVERY', 'TERMINATION_INJUNCTION')),
    current_forum VARCHAR(150),
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. PARTIES -------------------------------------------------------------------------------------
CREATE TABLE parties (
    party_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    canonical_name TEXT NOT NULL,
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('PLAINTIFF', 'DEFENDANT', 'PETITIONER', 'RESPONDENT', 'OTHER')),
    UNIQUE (matter_id, canonical_name)
);

CREATE TABLE party_aliases (
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    alias_normalised TEXT NOT NULL,
    party_id UUID NOT NULL REFERENCES parties(party_id) ON DELETE CASCADE,
    PRIMARY KEY (matter_id, alias_normalised)
);

-- 3. BATCHES -------------------------------------------------------------------------------------
CREATE TABLE ingestion_batches (
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL CHECK (batch_seq >= 1),
    label TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'PROCESSING', 'COMMITTED', 'FAILED')),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at TIMESTAMPTZ,
    PRIMARY KEY (matter_id, batch_seq)
);

-- 4. DOCUMENTS -----------------------------------------------------------------------------------
CREATE TABLE documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime_type TEXT,
    document_type VARCHAR(30),
    authority_class VARCHAR(20)
        CHECK (authority_class IN ('BILATERAL', 'COURT', 'PLEADING', 'SWORN', 'NOTICE',
                                   'RECORD', 'CORRESPONDENCE', 'INTERNAL')),
    document_date DATE,
    author_party_id UUID REFERENCES parties(party_id) ON DELETE SET NULL,
    signed_by_all_parties BOOLEAN NOT NULL DEFAULT FALSE,
    classification_confidence REAL,
    contract_id TEXT,
    contract_aliases TEXT[] NOT NULL DEFAULT '{}',
    amends_ref TEXT,
    amends_contract_id TEXT,
    defined_terms JSONB NOT NULL DEFAULT '[]',
    storage_uri TEXT NOT NULL,
    pdf_uri TEXT,
    sha256 CHAR(64) NOT NULL,
    text_sha CHAR(64),
    total_pages INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'EXTRACTED', 'PROCESSED', 'FAILED')),
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    UNIQUE (matter_id, sha256)
);
CREATE INDEX idx_documents_matter ON documents (matter_id, batch_seq);

CREATE TABLE batch_duplicates (
    duplicate_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matter_id UUID NOT NULL,
    batch_seq INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    duplicate_of_document_id UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE
);

-- 5. PAGES ---------------------------------------------------------------------------------------
CREATE TABLE document_pages (
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    page_text TEXT NOT NULL,
    extraction_method VARCHAR(10) NOT NULL CHECK (extraction_method IN ('DIGITAL', 'DOCLING', 'OCR')),
    ocr_confidence REAL,
    page_width REAL,
    page_height REAL,
    PRIMARY KEY (document_id, page_number)
);

-- 6. CHUNKS --------------------------------------------------------------------------------------
CREATE TABLE document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL,
    parent_chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    chunk_level VARCHAR(10) NOT NULL CHECK (chunk_level IN ('PARENT', 'CHILD')),
    ordinal INTEGER NOT NULL DEFAULT 0,
    structural_ref VARCHAR(50),
    heading TEXT,
    context_header TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    bboxes JSONB,
    token_count INTEGER NOT NULL,
    dense_embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', chunk_text) || to_tsvector('simple', chunk_text)
    ) STORED,
    CHECK (page_end >= page_start)
);
CREATE INDEX idx_chunks_hnsw ON document_chunks
    USING hnsw (dense_embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_tsv ON document_chunks USING gin (tsv);
CREATE INDEX idx_chunks_matter ON document_chunks (matter_id, document_id, page_start);
CREATE INDEX idx_chunks_parent ON document_chunks (parent_chunk_id);

-- 7. FACTS ---------------------------------------------------------------------------------------
CREATE TABLE matter_fact_assertions (
    assertion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    subject_type VARCHAR(20) NOT NULL,
    slot VARCHAR(60) NOT NULL,
    assertion_category VARCHAR(20) NOT NULL
        CHECK (assertion_category IN ('TERM', 'CLAIM', 'COUNTERCLAIM', 'DEFENCE', 'DENIAL', 'ADMISSION',
                                      'RELIEF_SOUGHT', 'PAYMENT', 'EVENT_FACT', 'DIRECTION', 'UNDERTAKING')),
    asserting_party_id UUID REFERENCES parties(party_id) ON DELETE SET NULL,
    assertion_text TEXT NOT NULL,
    value_text TEXT,
    value_date DATE,
    value_amount NUMERIC(15, 2),
    value_bool BOOLEAN,
    value_number INTEGER,
    originating_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_chunk_id UUID REFERENCES document_chunks(chunk_id) ON DELETE SET NULL,
    source_page INTEGER NOT NULL,
    source_quote TEXT NOT NULL,
    assertion_date DATE,
    effective_from DATE,
    effective_to DATE,
    learned_in_batch_seq INTEGER NOT NULL,
    ended_in_batch_seq INTEGER,
    state VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (state IN ('ACTIVE', 'DISPUTED', 'SUPERSEDED', 'WITHDRAWN')),
    evidence_only BOOLEAN NOT NULL DEFAULT FALSE,
    derived BOOLEAN NOT NULL DEFAULT FALSE,
    superseded_by_assertion_id UUID REFERENCES matter_fact_assertions(assertion_id),
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, learned_in_batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    FOREIGN KEY (matter_id, ended_in_batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    CHECK (ended_in_batch_seq IS NULL OR ended_in_batch_seq >= learned_in_batch_seq),
    CHECK ((state IN ('SUPERSEDED', 'WITHDRAWN')) = (ended_in_batch_seq IS NOT NULL))
);
CREATE INDEX idx_facts_current_key ON matter_fact_assertions (matter_id, fact_key)
    WHERE ended_in_batch_seq IS NULL;
CREATE INDEX idx_facts_matter ON matter_fact_assertions (matter_id, learned_in_batch_seq);
CREATE INDEX idx_facts_review ON matter_fact_assertions (matter_id) WHERE needs_review;

-- 8. LEDGER --------------------------------------------------------------------------------------
CREATE TABLE fact_change_log (
    change_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matter_id UUID NOT NULL,
    batch_seq INTEGER NOT NULL,
    assertion_id UUID NOT NULL REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    change_type VARCHAR(30) NOT NULL
        CHECK (change_type IN ('NEW', 'SUPERSEDED', 'NARROWED', 'DISPUTED',
                               'CONTRADICTED_BY_EVIDENCE', 'CORROBORATED', 'WITHDRAWN', 'COMPLIED')),
    previous_state VARCHAR(20),
    new_state VARCHAR(20) NOT NULL,
    related_assertion_id UUID REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    caused_by_document_id UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    rule_id VARCHAR(10) NOT NULL,
    reviewer TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE
);
CREATE INDEX idx_change_log_batch ON fact_change_log (matter_id, batch_seq);
CREATE INDEX idx_change_log_assertion ON fact_change_log (assertion_id, batch_seq);

-- 9. EVIDENCE LINKS ------------------------------------------------------------------------------
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
CREATE INDEX idx_links_target ON fact_links (target_assertion_id);

-- 10. EVENTS -------------------------------------------------------------------------------------
CREATE TABLE matter_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    date_precision VARCHAR(10) NOT NULL DEFAULT 'DAY' CHECK (date_precision IN ('DAY', 'MONTH', 'YEAR')),
    event_type VARCHAR(40) NOT NULL,
    description TEXT NOT NULL,
    party_id UUID REFERENCES parties(party_id) ON DELETE SET NULL,
    assertion_id UUID REFERENCES matter_fact_assertions(assertion_id) ON DELETE SET NULL,
    source_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_page INTEGER NOT NULL,
    learned_in_batch_seq INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_matter_date ON matter_events (matter_id, event_date);

-- 11. COURT DIRECTIONS ---------------------------------------------------------------------------
CREATE TABLE court_directions (
    direction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    assertion_id UUID NOT NULL UNIQUE REFERENCES matter_fact_assertions(assertion_id) ON DELETE CASCADE,
    order_document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    order_date DATE NOT NULL,
    direction_ref VARCHAR(30),
    kind VARCHAR(20) NOT NULL CHECK (kind IN ('DIRECTION', 'UNDERTAKING', 'INTERIM_RELIEF', 'NEXT_HEARING')),
    procedural_step VARCHAR(40) NOT NULL,
    direction_text TEXT NOT NULL,
    responsible_party_id UUID REFERENCES parties(party_id) ON DELETE SET NULL,
    period_text TEXT,
    period_days INTEGER,
    period_months INTEGER,
    trigger_date DATE,
    due_date DATE,
    weekend_flag BOOLEAN NOT NULL DEFAULT FALSE,
    compliance_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (compliance_status IN ('PENDING', 'COMPLIED', 'NOT_APPLICABLE')),
    complied_by_document_id UUID REFERENCES documents(document_id) ON DELETE SET NULL,
    complied_late BOOLEAN,
    source_page INTEGER NOT NULL
);
CREATE INDEX idx_directions_due ON court_directions (matter_id, due_date);

-- 12. PUBLIC LEGAL CORPUS ------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS legal_corpus;

CREATE TABLE legal_corpus.sources (
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key TEXT UNIQUE NOT NULL,
    source_type VARCHAR(10) NOT NULL CHECK (source_type IN ('STATUTE', 'JUDGMENT')),
    title TEXT NOT NULL,
    citation TEXT,
    court VARCHAR(150),
    decision_date DATE,
    source_url TEXT NOT NULL,
    treatment_note TEXT,
    verified_by TEXT NOT NULL,
    verified_on DATE NOT NULL,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (verification_status IN ('UNVERIFIED', 'VERIFIED'))
);

CREATE TABLE legal_corpus.passages (
    passage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES legal_corpus.sources(source_id) ON DELETE CASCADE,
    section_ref VARCHAR(50),
    paragraph_number INTEGER,
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

-- 13. JOB QUEUE ----------------------------------------------------------------------------------
CREATE TABLE ingestion_jobs (
    job_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    batch_seq INTEGER NOT NULL,
    document_id UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    stage VARCHAR(20) NOT NULL CHECK (stage IN ('PARSE', 'EXTRACT', 'RECONCILE')),
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED', 'RUNNING', 'DONE', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_error TEXT,
    timings_ms JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (matter_id, batch_seq)
        REFERENCES ingestion_batches(matter_id, batch_seq) ON DELETE CASCADE,
    CHECK ((stage = 'RECONCILE') = (document_id IS NULL))
);
CREATE INDEX idx_jobs_queued ON ingestion_jobs (job_id) WHERE status = 'QUEUED';
CREATE UNIQUE INDEX uq_jobs_doc_stage ON ingestion_jobs (document_id, stage) WHERE document_id IS NOT NULL;
CREATE UNIQUE INDEX uq_jobs_batch_reconcile ON ingestion_jobs (matter_id, batch_seq) WHERE stage = 'RECONCILE';

CREATE TABLE document_extractions (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    items JSONB NOT NULL DEFAULT '[]',
    dropped JSONB NOT NULL DEFAULT '[]',
    model_info JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 14. QUERY TRACES -------------------------------------------------------------------------------
CREATE TABLE query_traces (
    trace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    matter_id UUID NOT NULL REFERENCES matters(matter_id) ON DELETE CASCADE,
    as_of_batch_seq INTEGER NOT NULL,
    question TEXT NOT NULL,
    intents TEXT[] NOT NULL,
    routed_by VARCHAR(10) NOT NULL CHECK (routed_by IN ('RULES', 'MODEL', 'HINT')),
    plans JSONB NOT NULL,
    retrieved JSONB NOT NULL,
    citation_checks JSONB NOT NULL,
    timings_ms JSONB NOT NULL,
    model_versions JSONB NOT NULL,
    answer JSONB,
    actor TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_traces_matter ON query_traces (matter_id, created_at DESC);
