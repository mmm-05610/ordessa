"""Explicit schema12 widens the original action ledger and adds immutable facts."""
from .apply_schema import APPLY_DDL

SUBMISSION_SCHEMA_VERSION = 12
SUBMISSION_TABLES = ('eng_submissions',)
_ACTION_CHECK = "CHECK(action IN ('apply_change','generate_package','edit_repository','run_checks','create_local_commit','export_bundle','publish_branch','deploy'))"
IMPLEMENTATION_APPLY_DDL = APPLY_DDL.replace("CHECK(action='apply_change')", _ACTION_CHECK).replace("CREATE TABLE eng_action_consumptions", 'CREATE TABLE "eng_action_consumptions"')
SUBMISSION_DDL = """
CREATE TABLE eng_submissions (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, submission_id TEXT NOT NULL,
 digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,submission_id)
);
CREATE TRIGGER eng_submissions_no_update BEFORE UPDATE ON eng_submissions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_submissions_no_delete BEFORE DELETE ON eng_submissions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
# With the original migration's verified FK-OFF boundary, replace only the
# existing ledger table, retaining every row and its native identity. No second
# consumption authority remains after COMMIT; apply-record FK names stay exact.
MIGRATION11_DDL = """
CREATE TABLE eng_action_consumptions_upgrade (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, action_instance_id TEXT NOT NULL,
 approval_id TEXT NOT NULL, action TEXT NOT NULL ACTION_CHECK,
 intent_digest TEXT NOT NULL, target_digest TEXT NOT NULL, consumed_at TEXT NOT NULL,
 PRIMARY KEY(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
INSERT INTO eng_action_consumptions_upgrade SELECT * FROM eng_action_consumptions;
DROP TABLE eng_action_consumptions;
ALTER TABLE eng_action_consumptions_upgrade RENAME TO eng_action_consumptions;
CREATE TRIGGER eng_action_consumptions_no_update BEFORE UPDATE ON eng_action_consumptions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_action_consumptions_no_delete BEFORE DELETE ON eng_action_consumptions
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
""".replace('ACTION_CHECK', _ACTION_CHECK) + SUBMISSION_DDL
