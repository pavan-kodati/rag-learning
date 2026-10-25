-- Audit trail: who did what, when (enterprise requirement).
CREATE TABLE audit_log (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor TEXT NOT NULL,
    role TEXT,
    action TEXT NOT NULL,
    matter_id UUID,
    entity TEXT,
    entity_id TEXT,
    detail JSONB NOT NULL DEFAULT '{}',
    request_id TEXT
);
CREATE INDEX idx_audit_matter ON audit_log (matter_id, ts DESC);
CREATE INDEX idx_audit_ts ON audit_log (ts DESC);
