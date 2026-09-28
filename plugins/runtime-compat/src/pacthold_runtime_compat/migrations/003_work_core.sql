-- Work Core v0.1
--
-- This schema deliberately stores only cross-provider correlation and
-- continuation state. Native transcripts, Git objects, artifact bodies and
-- legacy launch sessions remain owned by their existing providers.

CREATE TABLE IF NOT EXISTS works (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    project_ref_json TEXT NOT NULL,
    workflow_ref TEXT NOT NULL DEFAULT 'plan-execute-review',
    workflow_version TEXT NOT NULL DEFAULT '0.1',
    phase TEXT NOT NULL DEFAULT 'plan',
    status TEXT NOT NULL DEFAULT 'ready',
    role_bindings_json TEXT NOT NULL DEFAULT '{}',
    workspace_ref_json TEXT,
    final_result_json TEXT,
    cleanup_state TEXT NOT NULL DEFAULT 'not_started',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_attempts (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    role_key TEXT NOT NULL,
    binding_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    effective_resolution_json TEXT NOT NULL,
    native_session_ref_json TEXT,
    input_handoff_id TEXT,
    output_handoff_id TEXT,
    outcome TEXT,
    trace_ref_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    started_at TEXT,
    ended_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_work_attempts_work
    ON work_attempts(work_id, created_at);
CREATE INDEX IF NOT EXISTS idx_work_attempts_role
    ON work_attempts(work_id, role_key, binding_revision);

CREATE TABLE IF NOT EXISTS work_decisions (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'system',
    related_attempt_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_work_decisions_work
    ON work_decisions(work_id, created_at);

CREATE TABLE IF NOT EXISTS work_artifacts (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    producer_attempt_id TEXT,
    kind TEXT NOT NULL,
    locator TEXT NOT NULL,
    digest TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_work_artifacts_work
    ON work_artifacts(work_id, kind, created_at);

CREATE TABLE IF NOT EXISTS work_handoffs (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    from_attempt_id TEXT,
    to_role_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES work_artifacts(id),
    digest TEXT NOT NULL,
    payload_path TEXT NOT NULL,
    consumed_by_attempt_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_work_handoffs_work
    ON work_handoffs(work_id, created_at);
