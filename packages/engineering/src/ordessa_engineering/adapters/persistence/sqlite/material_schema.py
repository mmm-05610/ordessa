"""Explicit schema6: material revisions v1 history and v2 provenance.

The original application DDL remains immutable. Fresh creation and migration
replay the same rebuild so SQL identity, foreign keys and triggers agree.
"""
MATERIAL_SCHEMA_VERSION = 6
MATERIAL_DDL = """
CREATE TABLE eng_artifact_revisions_material_upgrade (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL, revision_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL, digest TEXT NOT NULL,
  schema_version INTEGER NOT NULL CHECK (schema_version IN (1,2)),
  canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
  PRIMARY KEY (realm_id, project_id, revision_id),
  UNIQUE (realm_id, project_id, artifact_id, revision_id),
  FOREIGN KEY (realm_id, project_id, artifact_id)
    REFERENCES eng_artifacts(realm_id, project_id, artifact_id)
);
INSERT INTO eng_artifact_revisions_material_upgrade
  (realm_id, project_id, revision_id, artifact_id, digest, schema_version, canonical_bytes)
  SELECT realm_id, project_id, revision_id, artifact_id, digest, schema_version, canonical_bytes
  FROM eng_artifact_revisions;
DROP TABLE eng_artifact_revisions;
ALTER TABLE eng_artifact_revisions_material_upgrade RENAME TO eng_artifact_revisions;
CREATE TRIGGER eng_artifact_revisions_no_update BEFORE UPDATE ON eng_artifact_revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_artifact_revisions_no_delete BEFORE DELETE ON eng_artifact_revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
