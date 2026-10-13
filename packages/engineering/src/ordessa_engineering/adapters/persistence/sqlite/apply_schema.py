"""Explicit schema9: immutable action consumption and whole-batch apply receipt."""
APPLY_SCHEMA_VERSION = 9
APPLY_TABLES = ('eng_action_consumptions', 'eng_apply_records')
APPLY_DDL = """
CREATE TABLE eng_action_consumptions (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, action_instance_id TEXT NOT NULL,
 approval_id TEXT NOT NULL, action TEXT NOT NULL CHECK(action='apply_change'),
 intent_digest TEXT NOT NULL, target_digest TEXT NOT NULL, consumed_at TEXT NOT NULL,
 PRIMARY KEY(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
CREATE TABLE eng_apply_records (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, apply_id TEXT NOT NULL,
 action_instance_id TEXT NOT NULL, approval_id TEXT NOT NULL, digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,apply_id), UNIQUE(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,action_instance_id) REFERENCES eng_action_consumptions(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
"""
for _table in APPLY_TABLES:
    APPLY_DDL += f"""
CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
