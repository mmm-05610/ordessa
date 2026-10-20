-- Neutral kernel schema (specs/010-platform-core T009).
--
-- Idempotent copy of the END STATE that the historical agent-box chain
-- (004-009, sealed in pacthold_runtime_compat) produces for the kernel-owned
-- core_* tables.  Everything below is CREATE ... IF NOT EXISTS: applying this
-- file over a database that already ran the legacy chain is a verified no-op,
-- and a bare kernel database ends table-structurally equivalent to the
-- assembled product database (dual-path equivalence test lives in
-- plugins/runtime-compat/tests).
--
-- This file must never gain an ALTER/DROP/UPDATE statement: it describes the
-- schema of new databases, it does not migrate old ones.

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
    contract_id TEXT,
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

-- Final shape produced by historical migration 006 (execution_id UNIQUE,
-- inputs_digest beside the preserved provider correlation).
CREATE TABLE IF NOT EXISTS core_dispatches (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE
        REFERENCES core_executions(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    provider_correlation_ref TEXT,
    inputs_digest TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_core_dispatches_execution
    ON core_dispatches(execution_id);

-- Final shape of the append-only ResourceObservation ledger (historical
-- migrations 007 + 008 combined; evidence_meta_json keeps the 008 position).
CREATE TABLE IF NOT EXISTS core_resource_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL
        REFERENCES core_executions(id) ON DELETE CASCADE,
    contract_id TEXT NOT NULL,
    ref_type TEXT NOT NULL,
    ref_provider TEXT NOT NULL,
    ref_native_id TEXT NOT NULL,
    ref_uri TEXT,
    ref_meta_json TEXT NOT NULL DEFAULT '{}',
    ref_identity_digest TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'projected', 'read_back', 'consumption_reported')),
    result TEXT NOT NULL CHECK (result IN (
        'match', 'mismatch', 'unknown', 'unverifiable')),
    observer_role TEXT NOT NULL CHECK (observer_role IN (
        'execution_provider', 'resource_provider', 'host_observer',
        'external_authority')),
    observer_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    coverage TEXT NOT NULL CHECK (coverage IN (
        'complete', 'partial', 'unknown')),
    evidence_type TEXT,
    evidence_provider TEXT,
    evidence_native_id TEXT,
    evidence_uri TEXT,
    detail TEXT,
    observation_digest TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    evidence_meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_core_resource_observations_exec
    ON core_resource_observations(execution_id, id);

CREATE INDEX IF NOT EXISTS idx_core_resource_observations_input
    ON core_resource_observations(execution_id, ref_identity_digest);

-- Atomic Execution finalization operation receipts (historical migration 009).
-- This is persistence machinery only; Finalization is not a Core domain entity.
CREATE TABLE IF NOT EXISTS core_execution_finalizations (
    execution_id TEXT PRIMARY KEY REFERENCES core_executions(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    bundle_digest TEXT NOT NULL,
    execution_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
