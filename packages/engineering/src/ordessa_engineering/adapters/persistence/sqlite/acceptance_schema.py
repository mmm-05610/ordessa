"""Explicit schema14 action acceptance and immutable adoption facts."""

from .apply_schema import APPLY_DDL

ACCEPTANCE_SCHEMA_VERSION = 14
ACCEPTANCE_TABLES = ('eng_acceptance_receipts',)

_ACTION_CHECK = "CHECK(action IN ('apply_change','generate_package','edit_repository','run_checks','create_local_commit','export_bundle','publish_branch','deploy','accept_artifact'))"
ACCEPTANCE_LEDGER_DDL = APPLY_DDL.replace(
    "CHECK(action='apply_change')", _ACTION_CHECK
).replace('CREATE TABLE eng_action_consumptions', 'CREATE TABLE "eng_action_consumptions"')

MIGRATION13_DDL = """
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
""".replace('ACTION_CHECK', _ACTION_CHECK)

ACCEPTANCE_DDL = """
CREATE TABLE eng_acceptance_receipts (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, adoption_id TEXT NOT NULL,
 action_instance_id TEXT NOT NULL, approval_id TEXT NOT NULL,
 intent_digest TEXT NOT NULL, plan_digest TEXT NOT NULL, receipt_digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,adoption_id),
 UNIQUE(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,action_instance_id)
   REFERENCES eng_action_consumptions(realm_id,project_id,action_instance_id),
 FOREIGN KEY(realm_id,project_id,approval_id)
   REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
CREATE TRIGGER eng_acceptance_receipts_bound_insert BEFORE INSERT ON eng_acceptance_receipts
WHEN NOT EXISTS (
 SELECT 1 FROM eng_action_consumptions c
 WHERE c.realm_id=NEW.realm_id AND c.project_id=NEW.project_id
   AND c.action_instance_id=NEW.action_instance_id AND c.approval_id=NEW.approval_id
   AND c.action='accept_artifact' AND c.intent_digest=NEW.intent_digest
   AND c.target_digest=NEW.plan_digest
)
BEGIN SELECT RAISE(ABORT, 'ACCEPTANCE_ACTION_BINDING_INVALID'); END;
CREATE TRIGGER eng_acceptance_receipts_no_update BEFORE UPDATE ON eng_acceptance_receipts
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_acceptance_receipts_no_delete BEFORE DELETE ON eng_acceptance_receipts
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""

ACCEPTANCE_MIGRATION_DDL = MIGRATION13_DDL + ACCEPTANCE_DDL
