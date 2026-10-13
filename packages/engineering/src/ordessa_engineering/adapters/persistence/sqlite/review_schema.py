"""Schema5 reviews on the same Engineering authority and transaction."""
REVIEW_SCHEMA_VERSION = 5
REVIEW_TABLES = ('eng_review_requirements', 'eng_review_sets', 'eng_review_plans',
                'eng_review_requests', 'eng_reviews', 'eng_review_controls', 'eng_review_control_events')
REVIEW_DDL = """
CREATE TABLE eng_review_requirements (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL,
 requirement_id TEXT NOT NULL, requirement_version INTEGER NOT NULL CHECK (typeof(requirement_version)='integer' AND requirement_version>0),
 digest TEXT NOT NULL, canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
 PRIMARY KEY (realm_id,project_id,requirement_id,requirement_version)
);
CREATE TABLE eng_review_sets (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, set_digest TEXT NOT NULL,
 requirement_id TEXT NOT NULL, requirement_version INTEGER NOT NULL,
 canonical_key BLOB NOT NULL CHECK (typeof(canonical_key)='blob' AND length(canonical_key)<=2097152),
 set_version INTEGER NOT NULL CHECK (typeof(set_version)='integer' AND set_version>=0),
 PRIMARY KEY (realm_id,project_id,set_digest),
 UNIQUE (realm_id,project_id,requirement_id,requirement_version),
 FOREIGN KEY (realm_id,project_id,requirement_id,requirement_version)
 REFERENCES eng_review_requirements(realm_id,project_id,requirement_id,requirement_version)
);
CREATE TABLE eng_review_plans (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, review_id TEXT NOT NULL,
 set_digest TEXT NOT NULL, plan_digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
 PRIMARY KEY (realm_id,project_id,review_id),
 UNIQUE (realm_id,project_id,review_id,set_digest),
 FOREIGN KEY (realm_id,project_id,set_digest) REFERENCES eng_review_sets(realm_id,project_id,set_digest)
);
CREATE TABLE eng_review_requests (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, review_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('requested','recorded','withdrawn')),
 fence INTEGER NOT NULL CHECK (typeof(fence)='integer' AND fence>0),
 version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version>=0),
 PRIMARY KEY (realm_id,project_id,review_id),
 FOREIGN KEY (realm_id,project_id,review_id) REFERENCES eng_review_plans(realm_id,project_id,review_id)
);
CREATE TABLE eng_reviews (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, review_id TEXT NOT NULL,
 set_digest TEXT NOT NULL, digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
 PRIMARY KEY (realm_id,project_id,review_id),
 FOREIGN KEY (realm_id,project_id,review_id,set_digest)
 REFERENCES eng_review_plans(realm_id,project_id,review_id,set_digest)
);
CREATE INDEX eng_reviews_set_index ON eng_reviews(realm_id,project_id,set_digest,review_id);
CREATE TABLE eng_review_controls (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, review_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('active','voided','replaced')),
 version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version>=0),
 canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
 PRIMARY KEY (realm_id,project_id,review_id),
 FOREIGN KEY (realm_id,project_id,review_id) REFERENCES eng_reviews(realm_id,project_id,review_id)
);
CREATE TABLE eng_review_control_events (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, review_id TEXT NOT NULL,
 version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version>=0),
 canonical_bytes BLOB NOT NULL CHECK (typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152),
 PRIMARY KEY (realm_id,project_id,review_id,version),
 FOREIGN KEY (realm_id,project_id,review_id) REFERENCES eng_reviews(realm_id,project_id,review_id)
);
"""
for _table in ('eng_review_requirements', 'eng_review_plans', 'eng_reviews', 'eng_review_control_events'):
    REVIEW_DDL += f"""
CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
del _table
