-- Resource Contract inputs for the Preview Dispatch protocol.
--
-- Some local Preview databases already applied an older migration 005 which
-- rebuilt core_dispatches around submission_digest and
-- requested/starting/started.  Fresh databases still have the simpler 004
-- shape.  The columns selected below are common to both shapes.

BEGIN IMMEDIATE;

ALTER TABLE core_execution_refs
    ADD COLUMN contract_id TEXT;

-- Preserve every legacy column/value for audit without pretending that an
-- old submission_digest is the new frozen inputs_digest.
CREATE TABLE core_dispatches_pre_v006_archive AS
    SELECT * FROM core_dispatches;

DROP TABLE core_dispatches;

CREATE TABLE core_dispatches (
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

INSERT INTO core_dispatches (
    id,
    execution_id,
    idempotency_key,
    state,
    provider_correlation_ref,
    inputs_digest,
    created_at,
    updated_at
)
SELECT
    id,
    execution_id,
    idempotency_key,
    CASE
        WHEN state = 'started' THEN 'accepted'
        WHEN state IN ('accepted', 'failed') THEN state
        ELSE 'legacy-unverifiable'
    END,
    provider_correlation_ref,
    NULL,
    created_at,
    updated_at
FROM core_dispatches_pre_v006_archive;

CREATE UNIQUE INDEX IF NOT EXISTS idx_core_dispatches_execution
    ON core_dispatches(execution_id);

COMMIT;
