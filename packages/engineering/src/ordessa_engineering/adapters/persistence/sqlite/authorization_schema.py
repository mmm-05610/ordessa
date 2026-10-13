"""Explicit additive schema8; old native tables/DDL and default schema2 stay."""
AUTHORIZATION_SCHEMA_VERSION = 8
AUTHORIZATION_TABLES = ('eng_notices', 'eng_authorization_intents', 'eng_consent_challenges',
    'eng_consent_receipts', 'eng_approval_grants', 'eng_receipt_bindings',
    'eng_approval_controls', 'eng_approval_control_events')
AUTHORIZATION_DDL = """
CREATE TABLE eng_notices (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, notice_id TEXT NOT NULL, digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,notice_id)
);
CREATE TABLE eng_authorization_intents (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, intent_id TEXT NOT NULL, digest TEXT NOT NULL,
 notice_id TEXT NOT NULL, method_digest TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,intent_id),
 FOREIGN KEY(realm_id,project_id,notice_id) REFERENCES eng_notices(realm_id,project_id,notice_id)
);
CREATE TABLE eng_consent_challenges (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, challenge_id TEXT NOT NULL, intent_id TEXT NOT NULL,
 binding_digest TEXT NOT NULL, presented_digest TEXT NOT NULL, nonce_digest TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','granted','cancelled','expired')),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991),
 expires_at TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,challenge_id),
 UNIQUE(realm_id,project_id,nonce_digest),
 FOREIGN KEY(realm_id,project_id,intent_id) REFERENCES eng_authorization_intents(realm_id,project_id,intent_id)
);
CREATE TABLE eng_consent_receipts (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, receipt_id TEXT NOT NULL,
 issuer TEXT NOT NULL, external_event_id TEXT NOT NULL, binding_digest TEXT NOT NULL, challenge_id TEXT NOT NULL,
 evidence_bytes BLOB NOT NULL CHECK(typeof(evidence_bytes)='blob' AND length(evidence_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,receipt_id), UNIQUE(issuer,external_event_id),
 FOREIGN KEY(realm_id,project_id,challenge_id) REFERENCES eng_consent_challenges(realm_id,project_id,challenge_id)
);
CREATE UNIQUE INDEX eng_consent_one_pending_intent
 ON eng_consent_challenges(realm_id,project_id,intent_id) WHERE state='pending';
CREATE TABLE eng_approval_grants (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, approval_id TEXT NOT NULL, intent_id TEXT NOT NULL,
 digest TEXT NOT NULL, challenge_id TEXT NOT NULL, attestor_id TEXT NOT NULL,
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,approval_id), UNIQUE(realm_id,project_id,challenge_id),
 FOREIGN KEY(realm_id,project_id,intent_id) REFERENCES eng_authorization_intents(realm_id,project_id,intent_id),
 FOREIGN KEY(realm_id,project_id,challenge_id) REFERENCES eng_consent_challenges(realm_id,project_id,challenge_id)
);
CREATE TABLE eng_receipt_bindings (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, receipt_id TEXT NOT NULL, intent_id TEXT NOT NULL, approval_id TEXT NOT NULL,
 PRIMARY KEY(realm_id,project_id,receipt_id), UNIQUE(realm_id,project_id,approval_id),
 FOREIGN KEY(realm_id,project_id,receipt_id) REFERENCES eng_consent_receipts(realm_id,project_id,receipt_id),
 FOREIGN KEY(realm_id,project_id,intent_id) REFERENCES eng_authorization_intents(realm_id,project_id,intent_id),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
CREATE TABLE eng_approval_controls (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, approval_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('granted','revoked')),
 version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version BETWEEN 0 AND 9007199254740991), revoked_at TEXT,
 CHECK((state='granted' AND revoked_at IS NULL) OR (state='revoked' AND revoked_at IS NOT NULL)),
 PRIMARY KEY(realm_id,project_id,approval_id),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
CREATE TABLE eng_approval_control_events (
 realm_id TEXT NOT NULL, project_id TEXT NOT NULL, event_id TEXT NOT NULL, approval_id TEXT NOT NULL,
 from_version INTEGER NOT NULL, to_version INTEGER NOT NULL CHECK(to_version=from_version+1), action TEXT NOT NULL CHECK(action='revoke'),
 canonical_bytes BLOB NOT NULL CHECK(typeof(canonical_bytes)='blob' AND length(canonical_bytes) BETWEEN 1 AND 2097152),
 PRIMARY KEY(realm_id,project_id,event_id), UNIQUE(realm_id,project_id,approval_id,to_version),
 FOREIGN KEY(realm_id,project_id,approval_id) REFERENCES eng_approval_grants(realm_id,project_id,approval_id)
);
"""
AUTHORIZATION_DDL += """
CREATE TRIGGER eng_consent_binding_immutable BEFORE UPDATE ON eng_consent_challenges
WHEN OLD.state!='pending' OR NEW.state='pending' OR NEW.version!=OLD.version+1
 OR NEW.realm_id!=OLD.realm_id OR NEW.project_id!=OLD.project_id OR NEW.challenge_id!=OLD.challenge_id
 OR NEW.intent_id!=OLD.intent_id OR NEW.binding_digest!=OLD.binding_digest
 OR NEW.presented_digest!=OLD.presented_digest OR NEW.nonce_digest!=OLD.nonce_digest
 OR NEW.expires_at!=OLD.expires_at OR NEW.canonical_bytes!=OLD.canonical_bytes
BEGIN SELECT RAISE(ABORT, 'CONSENT_BINDING_IMMUTABLE'); END;
CREATE TRIGGER eng_approval_revocation_irreversible BEFORE UPDATE ON eng_approval_controls
WHEN OLD.state='revoked' OR NEW.state!='revoked' OR NEW.version!=OLD.version+1
 OR NEW.realm_id!=OLD.realm_id OR NEW.project_id!=OLD.project_id OR NEW.approval_id!=OLD.approval_id
BEGIN SELECT RAISE(ABORT, 'APPROVAL_REVOCATION_IRREVERSIBLE'); END;
"""
for _table in ('eng_notices', 'eng_authorization_intents', 'eng_consent_receipts',
               'eng_approval_grants', 'eng_receipt_bindings', 'eng_approval_control_events'):
    AUTHORIZATION_DDL += f"""
CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table}
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RECORD'); END;
"""
