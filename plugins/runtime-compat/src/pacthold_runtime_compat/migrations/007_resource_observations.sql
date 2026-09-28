-- Structured post-run ResourceObservation ledger (append-only).
--
-- One row is one observer's typed claim about one frozen INPUT
-- (contract_id, Ref) association of an Execution.  The table is a fact
-- ledger, not an entity: there is no update/delete path in the repository,
-- conflicting claims from multiple observers coexist, and nothing here
-- changes Execution phase/outcome or Work lifecycle.

BEGIN IMMEDIATE;

CREATE TABLE core_resource_observations (
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
    recorded_at TEXT NOT NULL
);

CREATE INDEX idx_core_resource_observations_exec
    ON core_resource_observations(execution_id, id);

CREATE INDEX idx_core_resource_observations_input
    ON core_resource_observations(execution_id, ref_identity_digest);

COMMIT;
