-- Atomic Execution finalization operation receipts. This is persistence
-- machinery only; Finalization is not a Core domain entity.
CREATE TABLE core_execution_finalizations (
    execution_id TEXT PRIMARY KEY REFERENCES core_executions(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    bundle_digest TEXT NOT NULL,
    execution_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
