"""Explicit schema10: project method selection history and controlled snapshots."""
METHOD_SCHEMA_VERSION = 10
METHOD_TABLES = ('eng_method_adoptions', 'eng_method_controls', 'eng_method_control_events')
METHOD_DDL = """
CREATE TABLE eng_method_adoptions (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, adoption_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version BETWEEN 1 AND 9223372036854775807),
 method_snapshot_digest TEXT NOT NULL REFERENCES eng_method_snapshots(snapshot_digest),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,adoption_id), UNIQUE(realm_id,project_id,version)
);
CREATE TABLE eng_method_controls (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL,
 method_snapshot_digest TEXT NOT NULL REFERENCES eng_method_snapshots(snapshot_digest),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 version INTEGER NOT NULL CHECK(version BETWEEN 0 AND 9223372036854775807),
 event_ref TEXT NOT NULL,
 PRIMARY KEY(realm_id,project_id,method_snapshot_digest)
);
CREATE TABLE eng_method_control_events (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, method_snapshot_digest TEXT NOT NULL,
 version INTEGER NOT NULL CHECK(version BETWEEN 0 AND 9223372036854775807),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,method_snapshot_digest,version),
 FOREIGN KEY(realm_id,project_id,method_snapshot_digest) REFERENCES eng_method_controls(realm_id,project_id,method_snapshot_digest)
);
"""
for _table in ('eng_method_adoptions','eng_method_control_events'):
    METHOD_DDL += f"""
CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
