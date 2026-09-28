-- Additive persistence for the frozen Minimal Work Core v0.1.
-- Legacy works/work_attempts remain untouched.

CREATE TABLE IF NOT EXISTS core_works (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    closure_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS core_executions (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES core_works(id) ON DELETE RESTRICT,
    provider_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    outcome TEXT,
    resumable_now INTEGER,
    freshness TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    dispatched_at TEXT,
    started_at TEXT,
    ended_at TEXT,
    version INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_core_executions_work ON core_executions(work_id, created_at);

CREATE TABLE IF NOT EXISTS core_execution_refs (
    execution_id TEXT NOT NULL REFERENCES core_executions(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    type TEXT NOT NULL,
    provider TEXT NOT NULL,
    native_id TEXT NOT NULL,
    uri TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY (execution_id, relation, type, provider, native_id)
);

CREATE TABLE IF NOT EXISTS core_events (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS core_dispatches (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES core_executions(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    provider_correlation_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
