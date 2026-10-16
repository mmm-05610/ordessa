"""Schema4 application artifact/journal slice; no consent or executor tables."""
APPLICATION_SCHEMA_VERSION = 4
APPLICATION_DDL = """
CREATE TABLE eng_artifacts (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
  kind TEXT NOT NULL, created_at TEXT NOT NULL, head_revision_id TEXT,
  version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version >= 0),
  PRIMARY KEY (realm_id, project_id, artifact_id),
  FOREIGN KEY (realm_id, project_id, artifact_id, head_revision_id)
    REFERENCES eng_artifact_revisions(realm_id, project_id, artifact_id, revision_id)
    DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE eng_artifact_revisions (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL, revision_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL, digest TEXT NOT NULL,
  schema_version INTEGER NOT NULL CHECK (schema_version=1),
  canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
  PRIMARY KEY (realm_id, project_id, revision_id),
  UNIQUE (realm_id, project_id, artifact_id, revision_id),
  FOREIGN KEY (realm_id, project_id, artifact_id)
    REFERENCES eng_artifacts(realm_id, project_id, artifact_id)
);
CREATE TABLE eng_revision_parents (
  realm_id TEXT NOT NULL, project_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
  revision_id TEXT NOT NULL, parent_revision_id TEXT NOT NULL,
  PRIMARY KEY (realm_id, project_id, revision_id, parent_revision_id),
  CHECK (revision_id != parent_revision_id),
  FOREIGN KEY (realm_id, project_id, artifact_id, revision_id)
    REFERENCES eng_artifact_revisions(realm_id, project_id, artifact_id, revision_id),
  FOREIGN KEY (realm_id, project_id, artifact_id, parent_revision_id)
    REFERENCES eng_artifact_revisions(realm_id, project_id, artifact_id, revision_id)
);
CREATE TABLE eng_commands (
  realm_id TEXT NOT NULL, principal_id TEXT NOT NULL, request_id TEXT NOT NULL,
  project_id TEXT NOT NULL, operation TEXT NOT NULL, operation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','completed','rejected')),
  result_bytes BLOB,
  version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version>=0),
  PRIMARY KEY (realm_id, principal_id, request_id),
  UNIQUE (realm_id, operation_id),
  CHECK ((state='pending' AND result_bytes IS NULL) OR
    (state!='pending' AND typeof(result_bytes)='blob' AND length(result_bytes)<=2097152))
);
CREATE TRIGGER eng_artifact_revisions_no_update BEFORE UPDATE ON eng_artifact_revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_artifact_revisions_no_delete BEFORE DELETE ON eng_artifact_revisions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_revision_parents_no_update BEFORE UPDATE ON eng_revision_parents
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_revision_parents_no_delete BEFORE DELETE ON eng_revision_parents
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
