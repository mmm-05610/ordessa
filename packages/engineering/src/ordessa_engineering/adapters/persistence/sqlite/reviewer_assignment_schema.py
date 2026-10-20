"""Original schema15 physical layout for tagged current and historical roles.

Existing eng_unit_* table/column/index/trigger identifiers remain unchanged.
Current canonical_bytes carries engineering-agent-reviewer-assignment/2 and
Agent refs. Untagged Unit rows retain exact original bytes and are read-only
history; repository admission never upgrades them into active Agent roles.
"""

REVIEWER_ASSIGNMENT_SCHEMA_VERSION = 15
REVIEWER_ASSIGNMENT_TABLES = (
    "eng_unit_reviewer_assignments",
    "eng_unit_reviewer_assignment_controls",
    "eng_unit_reviewer_assignment_events",
)

REVIEWER_ASSIGNMENT_DDL = """
CREATE TABLE eng_unit_reviewer_assignments (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
 review_id TEXT NOT NULL, plan_digest TEXT NOT NULL,
 request_version INTEGER NOT NULL CHECK(typeof(request_version)='integer' AND request_version BETWEEN 0 AND 9007199254740991),
 fence INTEGER NOT NULL CHECK(typeof(fence)='integer' AND fence BETWEEN 1 AND 9007199254740991),
 method_ref_json TEXT NOT NULL CHECK(typeof(method_ref_json)='text'),
 reviewer_unit_ref_json TEXT NOT NULL CHECK(typeof(reviewer_unit_ref_json)='text'),
 author_unit_ref_json TEXT CHECK(author_unit_ref_json IS NULL OR typeof(author_unit_ref_json)='text'),
 roles_json TEXT NOT NULL CHECK(typeof(roles_json)='text'),
 issuer_principal_id TEXT NOT NULL, issuer_credential_epoch INTEGER NOT NULL
   CHECK(typeof(issuer_credential_epoch)='integer' AND issuer_credential_epoch BETWEEN 0 AND 9007199254740991),
 assigned_at TEXT NOT NULL, digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 262144),
 PRIMARY KEY(realm_id,project_id,assignment_id),
 UNIQUE(realm_id,project_id,assignment_id,digest),
 FOREIGN KEY(realm_id,project_id,review_id) REFERENCES eng_review_plans(realm_id,project_id,review_id)
);
CREATE TABLE eng_unit_reviewer_assignment_controls (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, assignment_id TEXT NOT NULL,
 review_id TEXT NOT NULL, request_version INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('active','revoked')),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991),
 revoked_at TEXT, revoke_reason TEXT,
 CHECK((state='active' AND version=0 AND revoked_at IS NULL AND revoke_reason IS NULL)
    OR (state='revoked' AND version=1 AND typeof(revoked_at)='text' AND typeof(revoke_reason)='text')),
 PRIMARY KEY(realm_id,project_id,assignment_id),
 FOREIGN KEY(realm_id,project_id,assignment_id) REFERENCES eng_unit_reviewer_assignments(realm_id,project_id,assignment_id)
);
CREATE UNIQUE INDEX eng_unit_reviewer_one_active_assignment
 ON eng_unit_reviewer_assignment_controls(realm_id,project_id,review_id,request_version)
 WHERE state='active';
CREATE TRIGGER eng_unit_reviewer_assignment_controls_transition BEFORE UPDATE ON eng_unit_reviewer_assignment_controls
WHEN OLD.state!='active' OR NEW.state!='revoked' OR NEW.version!=OLD.version+1
 OR NEW.realm_id!=OLD.realm_id OR NEW.project_id!=OLD.project_id
 OR NEW.assignment_id!=OLD.assignment_id OR NEW.review_id!=OLD.review_id
 OR NEW.request_version!=OLD.request_version OR NEW.revoked_at IS NULL OR NEW.revoke_reason IS NULL
BEGIN SELECT RAISE(ABORT, 'REVIEWER_ASSIGNMENT_CONTROL_INVALID'); END;
CREATE TABLE eng_unit_reviewer_assignment_events (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, event_id TEXT NOT NULL,
 assignment_id TEXT NOT NULL, from_version INTEGER NOT NULL,
 to_version INTEGER NOT NULL CHECK(typeof(to_version)='integer' AND to_version=from_version+1),
 action TEXT NOT NULL CHECK(action='revoke'),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 65536),
 PRIMARY KEY(realm_id,project_id,event_id),
 UNIQUE(realm_id,project_id,assignment_id,to_version),
 FOREIGN KEY(realm_id,project_id,assignment_id) REFERENCES eng_unit_reviewer_assignments(realm_id,project_id,assignment_id)
);
CREATE TRIGGER eng_unit_reviewer_assignments_no_update BEFORE UPDATE ON eng_unit_reviewer_assignments
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_unit_reviewer_assignments_no_delete BEFORE DELETE ON eng_unit_reviewer_assignments
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_unit_reviewer_assignment_events_no_update BEFORE UPDATE ON eng_unit_reviewer_assignment_events
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_unit_reviewer_assignment_events_no_delete BEFORE DELETE ON eng_unit_reviewer_assignment_events
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER eng_unit_reviewer_assignment_controls_no_delete BEFORE DELETE ON eng_unit_reviewer_assignment_controls
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
