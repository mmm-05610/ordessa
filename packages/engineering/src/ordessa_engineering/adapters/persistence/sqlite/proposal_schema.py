"""Additive schema7 on the original EngineeringLibrary; no changed old DDL."""
PROPOSAL_SCHEMA_VERSION=7
PROPOSAL_TABLES=('eng_changes','eng_proposals','eng_proposal_mutations','eng_proposal_controls','eng_proposal_control_events')
PROPOSAL_DDL="""
CREATE TABLE eng_changes (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, change_id TEXT NOT NULL,
 created_at TEXT NOT NULL, selected_proposal_id TEXT,
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991),
 PRIMARY KEY(realm_id,project_id,change_id),
 FOREIGN KEY(realm_id,project_id,change_id,selected_proposal_id)
 REFERENCES eng_proposals(realm_id,project_id,change_id,proposal_id)
);
CREATE TABLE eng_proposals (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 change_id TEXT NOT NULL, digest TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version=1),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,proposal_id),
 UNIQUE(realm_id,project_id,change_id,proposal_id),
 FOREIGN KEY(realm_id,project_id,change_id) REFERENCES eng_changes(realm_id,project_id,change_id)
);
CREATE TABLE eng_proposal_mutations (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(typeof(position)='integer' AND position BETWEEN 0 AND 4095),
 artifact_id TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('create','revise')),
 base_revision_id TEXT, proposed_revision_id TEXT NOT NULL,
 CHECK((operation='create' AND base_revision_id IS NULL) OR (operation='revise' AND base_revision_id IS NOT NULL AND base_revision_id!=proposed_revision_id)),
 PRIMARY KEY(realm_id,project_id,proposal_id,position),
 UNIQUE(realm_id,project_id,proposal_id,artifact_id),
 FOREIGN KEY(realm_id,project_id,proposal_id) REFERENCES eng_proposals(realm_id,project_id,proposal_id),
 FOREIGN KEY(realm_id,project_id,artifact_id,base_revision_id) REFERENCES eng_artifact_revisions(realm_id,project_id,artifact_id,revision_id),
 FOREIGN KEY(realm_id,project_id,artifact_id,proposed_revision_id) REFERENCES eng_artifact_revisions(realm_id,project_id,artifact_id,revision_id)
);
CREATE TABLE eng_proposal_controls (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,proposal_id),
 FOREIGN KEY(realm_id,project_id,proposal_id) REFERENCES eng_proposals(realm_id,project_id,proposal_id)
);
CREATE TABLE eng_proposal_control_events (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,proposal_id,version),
 FOREIGN KEY(realm_id,project_id,proposal_id) REFERENCES eng_proposals(realm_id,project_id,proposal_id)
);
CREATE TRIGGER eng_proposals_no_update BEFORE UPDATE ON eng_proposals
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposals_no_delete BEFORE DELETE ON eng_proposals
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposal_mutations_no_update BEFORE UPDATE ON eng_proposal_mutations
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposal_mutations_no_delete BEFORE DELETE ON eng_proposal_mutations
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposal_control_events_no_update BEFORE UPDATE ON eng_proposal_control_events
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposal_control_events_no_delete BEFORE DELETE ON eng_proposal_control_events
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
