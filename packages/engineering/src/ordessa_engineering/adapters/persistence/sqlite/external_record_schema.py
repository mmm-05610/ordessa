"""Explicit schema16 widening of immutable proposal record versions."""

EXTERNAL_RECORD_SCHEMA_VERSION = 16

# This is an explicit same-table migration. It preserves every proposal row's
# identity, digest and canonical bytes while allowing the new source-only v2
# proposal alongside historical v1 records.
EXTERNAL_RECORD_DDL = """
CREATE TABLE eng_proposals_v16 (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, proposal_id TEXT NOT NULL,
 change_id TEXT NOT NULL, digest TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version IN (1,2)),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,proposal_id),
 UNIQUE(realm_id,project_id,change_id,proposal_id),
 FOREIGN KEY(realm_id,project_id,change_id) REFERENCES eng_changes(realm_id,project_id,change_id)
);
INSERT INTO eng_proposals_v16(realm_id,project_id,proposal_id,change_id,digest,schema_version,canonical_bytes)
 SELECT realm_id,project_id,proposal_id,change_id,digest,schema_version,canonical_bytes FROM eng_proposals;
DROP TABLE eng_proposals;
ALTER TABLE eng_proposals_v16 RENAME TO eng_proposals;
CREATE TRIGGER eng_proposals_no_update BEFORE UPDATE ON eng_proposals
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_proposals_no_delete BEFORE DELETE ON eng_proposals
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""

EXTERNAL_RECORD_TABLES = (
    "eng_changes", "eng_proposals", "eng_proposal_mutations",
    "eng_proposal_controls", "eng_proposal_control_events",
)
