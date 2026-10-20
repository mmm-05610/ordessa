"""Authorization storage primitives on the original scope-bound SQLite UoW."""
from dataclasses import asdict
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import (
    ConversationNotice, WorkPackageNotice, AuthorizationIntent, ChangeAuthorizationIntent, ConsentChallenge,
    ConversationEvidence, CapturedInstructionEvidence, ApprovalGrant,
)
from ordessa_engineering.domain.approvals.consent_codec import encode_record, decode_record
from ordessa_engineering.domain.common.models.values import validate_id
from ordessa_engineering.domain.changes.application_plan import ChangeApplicationReceipt, decode_application_receipt
from ordessa_engineering.domain.approvals.implementation import (
    ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent,
)
from ordessa_engineering.domain.common.models.values import Digest
from .apply_schema import APPLY_SCHEMA_VERSION
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION


class SQLiteAuthorizationRepository:
    def __init__(self, access):
        self.access = access

    def _prefix(self):
        self.access.check_active()
        return self.access.scope.realm_id, self.access.scope.project_id

    def _scope(self, record):
        scope = record.intent.scope if type(record) is ApprovalGrant else record.scope
        if scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')

    def _get(self, table, column, identifier, cls):
        validate_id(identifier)
        row = self.access.execute(f'SELECT canonical_bytes FROM {table} WHERE realm_id=? AND project_id=? AND {column}=?',
            self._prefix() + (identifier,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        record = decode_record(bytes(row[0]), cls)
        self._scope(record)
        if getattr(record, column) != identifier:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        return record

    def put_notice(self, notice):
        self.access.require_write()
        self._scope(notice)
        if type(notice) is WorkPackageNotice:
            self.require_work_package_authorization_schema()
        self.access.execute('INSERT INTO eng_notices VALUES (?,?,?,?,?)',
            self._prefix() + (notice.notice_id, notice.digest.hex, encode_record(notice)))

    def get_notice(self, ref):
        if ref.scope != self.access.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        notice = self._get('eng_notices', 'notice_id', ref.notice_id, ConversationNotice)
        if notice.ref != ref:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        return notice

    def put_intent(self, intent):
        self.access.require_write()
        self._scope(intent)
        self.get_notice(intent.notice_ref)
        if type(intent) is ImplementationAuthorizationIntent:
            self.require_implementation_authorization_schema()
        elif type(intent) is WorkPackageAuthorizationIntent:
            self.require_work_package_authorization_schema()
        self.access.execute('INSERT INTO eng_authorization_intents VALUES (?,?,?,?,?,?,?)',
            self._prefix() + (intent.intent_id, intent.digest.hex, intent.notice_ref.notice_id,
                            intent.method_ref.snapshot_digest.hex, encode_record(intent)))

    def get_intent(self, identifier):
        return self._get('eng_authorization_intents', 'intent_id', identifier, AuthorizationIntent)

    def put_challenge(self, challenge):
        self.access.require_write()
        self._scope(challenge)
        intent = self.get_intent(challenge.intent_id)
        if challenge.binding_digest != intent.digest:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        self.access.execute('INSERT INTO eng_consent_challenges VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            self._prefix() + (challenge.challenge_id, challenge.intent_id, challenge.binding_digest.hex,
                challenge.presented_digest.hex, challenge.nonce_digest.hex, 'pending', 0,
                challenge.expires_at, encode_record(challenge)))

    def get_challenge(self, identifier):
        challenge = self._get('eng_consent_challenges', 'challenge_id', identifier, ConsentChallenge)
        row = self.access.execute('SELECT state,version FROM eng_consent_challenges WHERE realm_id=? AND project_id=? AND challenge_id=?',
            self._prefix() + (identifier,)).fetchone()
        return challenge, row[0], row[1]

    def list_pending(self, *, limit, after_challenge_id):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ApplicationError('INVALID_ARGUMENT')
        prefix = self._prefix()
        if after_challenge_id is not None:
            # The cursor is an existing identity in this exact scope, never a
            # client-supplied project or a cross-project lookup.
            self.get_challenge(after_challenge_id)
        rows = self.access.execute(
            'SELECT challenge_id FROM eng_consent_challenges '
            'WHERE realm_id=? AND project_id=? AND state=? AND challenge_id>? '
            'ORDER BY challenge_id LIMIT ?',
            prefix + ('pending', after_challenge_id or '', limit + 1)).fetchall()
        items = []
        for (identifier,) in rows[:limit]:
            challenge, state, version = self.get_challenge(identifier)
            intent = self.get_intent(challenge.intent_id)
            notice = self.get_notice(intent.notice_ref)
            if challenge.binding_digest != intent.digest or challenge.presented_digest != notice.digest:
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            items.append({'challenge': asdict(challenge), 'state': state, 'version': version,
                          'intent': asdict(intent), 'notice': asdict(notice)})
        return {'items': items, 'next_after_challenge_id': rows[limit - 1][0] if len(rows) > limit else None}

    def transition_challenge(self, identifier, expected_version, state):
        self.access.require_write()
        if state not in ('granted', 'cancelled', 'expired') or type(expected_version) is not int:
            raise ApplicationError('INVALID_ARGUMENT')
        cursor = self.access.execute('UPDATE eng_consent_challenges SET state=?,version=version+1 WHERE realm_id=? AND project_id=? AND challenge_id=? AND version=? AND state=?',
            (state,) + self._prefix() + (identifier, expected_version, 'pending'))
        if cursor.rowcount != 1:
            raise ApplicationError('CONSENT_CHALLENGE_CHANGED')

    def put_receipt(self, challenge, evidence):
        self.access.require_write()
        intent = self.get_intent(challenge.intent_id)
        if (challenge.scope != self.access.scope or evidence.intent_digest != intent.digest
                or evidence.notice_ref != intent.notice_ref or evidence.policy_ref != intent.policy_ref):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        raw = encode_record(evidence)
        prefix = self._prefix()
        # Dedup uses actual available source identity, not a client-renamable
        # evidence_id. When message refs are absent, honestly use captured
        # question/context/answer plus locator/time; no platform ID is invented.
        source = evidence.source
        if type(evidence) is CapturedInstructionEvidence:
            # One actual instruction can authorize one exact Grant here. A new
            # capture time, intent, context or evidence id cannot turn the same
            # source messages into another authorization event. Without message
            # refs, use the unchanged instruction bytes conservatively.
            identity = {'kind': 'captured_instruction', 'locator': source.locator,
                        'message_refs': sorted(set(source.message_refs))}
            if not source.message_refs:
                identity['instruction'] = evidence.instruction
        else:
            # Preserve historical Q&A source keys and their canonical bytes.
            identity = {'locator': source.locator, 'message_refs': list(source.message_refs),
                        'captured_at': source.captured_at}
            if not source.message_refs:
                identity.update(question=evidence.question, necessary_context=evidence.necessary_context,
                                user_answer=evidence.user_answer)
        event_key = hashlib.sha256(canonical_bytes(identity)).hexdigest()
        existing = self.access.execute('SELECT realm_id,project_id,challenge_id,evidence_bytes FROM eng_consent_receipts WHERE issuer=? AND external_event_id=?',
            (source.attestor_id, event_key)).fetchone()
        if existing is not None:
            if existing != prefix + (challenge.challenge_id, raw):
                raise ApplicationError('CONSENT_RECEIPT_CONFLICT')
            return False
        self.access.execute('INSERT INTO eng_consent_receipts VALUES (?,?,?,?,?,?,?,?)',
            prefix + (evidence.evidence_id, source.attestor_id, event_key,
                evidence.intent_digest.hex, challenge.challenge_id, raw))
        return True

    def put_grant(self, grant):
        self.access.require_write()
        self._scope(grant)
        prefix = self._prefix()
        if grant.intent != self.get_intent(grant.intent.intent_id):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        challenge, state, _version = self.get_challenge(grant.challenge_id)
        if state != 'pending' or challenge.binding_digest != grant.intent.digest:
            raise ApplicationError('CONSENT_CHALLENGE_CHANGED')
        receipt = self.access.execute('SELECT challenge_id,evidence_bytes FROM eng_consent_receipts WHERE realm_id=? AND project_id=? AND receipt_id=?',
            prefix + (grant.evidence.evidence_id,)).fetchone()
        if receipt != (grant.challenge_id, encode_record(grant.evidence)):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        self.access.execute('INSERT INTO eng_approval_grants VALUES (?,?,?,?,?,?,?,?)',
            prefix + (grant.approval_id, grant.intent.intent_id, grant.digest.hex, grant.challenge_id,
                      grant.evidence.source.attestor_id, encode_record(grant)))
        self.access.execute('INSERT INTO eng_receipt_bindings VALUES (?,?,?,?,?)',
            prefix + (grant.evidence.evidence_id, grant.intent.intent_id, grant.approval_id))
        self.access.execute('INSERT INTO eng_approval_controls VALUES (?,?,?,?,?,?)',
            prefix + (grant.approval_id, 'granted', 0, None))

    def get_grant(self, ref):
        if (ref.realm_id, ref.project_id) != self._prefix():
            raise ApplicationError('SCOPE_MISMATCH')
        grant = self._get('eng_approval_grants', 'approval_id', ref.approval_id, ApprovalGrant)
        if grant.ref != ref:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        return grant

    def get_control(self, ref):
        self.get_grant(ref)
        row = self.access.execute('SELECT state,version,revoked_at FROM eng_approval_controls WHERE realm_id=? AND project_id=? AND approval_id=?',
            self._prefix() + (ref.approval_id,)).fetchone()
        if row is None:
            raise ApplicationError('STORAGE_CONSTRAINT')
        return {'state': row[0], 'version': row[1], 'revoked_at': row[2]}

    def find_work_package_grants(self, *, work_id, work_revision, work_digest,
                                 action_id, step_id, package_ref, method_ref, now):
        """Exact current subject lookup; ambiguity is returned, never ranked.

        The Work is frozen before a grant exists, so adding the resulting Grant
        ref to its associations would invalidate the very digest it authorizes.
        Selection stays on the original grant/control tables in this UoW.
        """
        self.require_work_package_authorization_schema()
        for value in (work_id, action_id, step_id):
            validate_id(value)
        if (type(work_revision) is not int or work_revision < 1
                or type(work_digest) is not Digest
                or (package_ref.realm_id, package_ref.project_id) != self._prefix()):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        rows = self.access.execute(
            'SELECT g.approval_id FROM eng_approval_grants g '
            'JOIN eng_authorization_intents i ON i.realm_id=g.realm_id '
            'AND i.project_id=g.project_id AND i.intent_id=g.intent_id '
            'JOIN eng_approval_controls c ON c.realm_id=g.realm_id '
            'AND c.project_id=g.project_id AND c.approval_id=g.approval_id '
            'WHERE g.realm_id=? AND g.project_id=? AND c.state=? '
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.schema_version')=2 "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.work_id')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.work_revision')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.work_digest.hex')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.action_id')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.step_id')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.package_ref')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.method_ref')=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.not_before')<=? "
            "AND json_extract(CAST(i.canonical_bytes AS TEXT),'$.authorization.expires_at')>? LIMIT 2",
            self._prefix() + ('granted', work_id, work_revision, work_digest.hex,
                action_id, step_id, canonical_bytes(asdict(package_ref)).decode('utf-8'),
                canonical_bytes(asdict(method_ref)).decode('utf-8'), now, now)).fetchall()
        grants = []
        for (identifier,) in rows:
            grant = self._get('eng_approval_grants', 'approval_id', identifier, ApprovalGrant)
            intent = grant.intent
            if type(intent) is not WorkPackageAuthorizationIntent:
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            authorization = intent.authorization
            if ((authorization.work_id, authorization.work_revision,
                 authorization.work_digest, authorization.action_id,
                 authorization.step_id, authorization.package_ref, authorization.method_ref)
                    != (work_id, work_revision, work_digest, action_id, step_id,
                        package_ref, method_ref)
                    or intent != self.get_intent(intent.intent_id)
                    or self.get_control(grant.ref)['state'] != 'granted'
                    or not intent.not_before <= now < intent.expires_at):
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            grants.append(grant)
        return tuple(grants)

    def revoke(self, ref, expected_version, occurred_at, reason, event_id):
        self.access.require_write()
        self.get_grant(ref)
        cursor = self.access.execute('UPDATE eng_approval_controls SET state=?,version=version+1,revoked_at=? WHERE realm_id=? AND project_id=? AND approval_id=? AND state=? AND version=?',
            ('revoked', occurred_at) + self._prefix() + (ref.approval_id, 'granted', expected_version))
        if cursor.rowcount != 1:
            raise ApplicationError('APPROVAL_CONTROL_CHANGED')
        body = {'approval_ref': asdict(ref), 'reason': reason, 'occurred_at': occurred_at}
        self.access.execute('INSERT INTO eng_approval_control_events VALUES (?,?,?,?,?,?,?,?)',
            self._prefix() + (event_id, ref.approval_id, expected_version, expected_version + 1,
                              'revoke', canonical_bytes(body)))

    def require_apply_schema(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('APPLY_SCHEMA_REQUIRED')

    def require_implementation_authorization_schema(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
            raise ApplicationError('IMPLEMENTATION_AUTHORIZATION_SCHEMA_REQUIRED')

    def require_work_package_authorization_schema(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) != WORK_DISPATCH_SCHEMA_VERSION:
            raise ApplicationError('WORK_DISPATCH_SCHEMA_REQUIRED')

    def consume_action(self, ref, *, action, action_instance_id, target_digest, now):
        """Called only inside the original application's effect transaction."""
        self.require_apply_schema()
        self.access.require_write()
        validate_id(action_instance_id)
        grant = self.get_grant(ref)
        intent = grant.intent
        if type(intent) is ChangeAuthorizationIntent:
            if action != 'apply_change' or action not in intent.actions:
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            if target_digest != intent.change_set.digest:
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            limit = intent.action_budget
        elif type(intent) is AuthorizationIntent:
            if (getattr(self.access._connection, '_ordessa_schema_version', None) not in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION)
                    or action != 'accept_artifact' or action not in intent.actions
                    or type(target_digest) is not Digest):
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            limit = intent.action_budget
        elif type(intent) is ImplementationAuthorizationIntent:
            self.require_implementation_authorization_schema()
            if action not in intent.actions or type(target_digest) is not Digest:
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            limit = next(slot.limit for slot in intent.action_budgets if slot.action == action)
        elif type(intent) is WorkPackageAuthorizationIntent:
            self.require_work_package_authorization_schema()
            if action not in intent.actions or type(target_digest) is not Digest:
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            limit = next(slot.limit for slot in intent.authorization.action_budgets
                         if slot.action == action)
        else:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        if self.get_control(ref)['state'] != 'granted':
            raise ApplicationError('AUTHORIZATION_REVOKED')
        if not intent.not_before <= now < intent.expires_at:
            raise ApplicationError('AUTHORIZATION_EXPIRED')
        count = self.access.execute('SELECT count(*) FROM eng_action_consumptions '
            'WHERE realm_id=? AND project_id=? AND approval_id=? AND action=?',
            self._prefix() + (ref.approval_id, action)).fetchone()[0]
        if count >= limit:
            raise ApplicationError('ACTION_BUDGET_EXHAUSTED')
        self.access.execute('INSERT INTO eng_action_consumptions VALUES (?,?,?,?,?,?,?,?)',
            self._prefix() + (action_instance_id, ref.approval_id, action, intent.digest.hex, target_digest.hex, now))

    def check_action_consumptions(self, ref, *, intent_digest, target_digest, action_instances):
        """Verify original immutable reservations; never consume or refund at send."""
        self.access.require_write()
        self.require_implementation_authorization_schema()
        grant = self.get_grant(ref)
        if (type(grant.intent) not in (ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent)
                or grant.intent.digest != intent_digest or type(target_digest) is not Digest):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        if type(grant.intent) is WorkPackageAuthorizationIntent:
            self.require_work_package_authorization_schema()
            slots = grant.intent.authorization.action_budgets
        else:
            slots = grant.intent.action_budgets
        limits = {slot.action: slot.limit for slot in slots}
        for action, instance in action_instances:
            if action not in limits:
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            row = self.access.execute('SELECT approval_id,action,intent_digest,target_digest '
                'FROM eng_action_consumptions WHERE realm_id=? AND project_id=? AND action_instance_id=?',
                self._prefix() + (instance,)).fetchone()
            if row != (ref.approval_id, action, intent_digest.hex, target_digest.hex):
                raise ApplicationError('DISPATCH_BUDGET_BINDING_MISMATCH')
            count = self.access.execute('SELECT count(*) FROM eng_action_consumptions '
                'WHERE realm_id=? AND project_id=? AND approval_id=? AND action=?',
                self._prefix() + (ref.approval_id, action)).fetchone()[0]
            if count > limits[action]:
                raise ApplicationError('ACTION_BUDGET_EXHAUSTED')

    def action_budget(self, ref):
        self.require_apply_schema()
        grant = self.get_grant(ref)
        if type(grant.intent) in (ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent):
            self.require_implementation_authorization_schema()
            if type(grant.intent) is WorkPackageAuthorizationIntent:
                self.require_work_package_authorization_schema()
                slots = grant.intent.authorization.action_budgets
            else:
                slots = grant.intent.action_budgets
            return {'actions': [{'action': slot.action, 'limit': slot.limit, 'consumed':
                self.access.execute('SELECT count(*) FROM eng_action_consumptions WHERE realm_id=? AND project_id=? AND approval_id=? AND action=?',
                    self._prefix() + (ref.approval_id, slot.action)).fetchone()[0]}
                for slot in slots], 'control': self.get_control(ref)}
        if type(grant.intent) is ChangeAuthorizationIntent:
            action = 'apply_change'
        elif (type(grant.intent) is AuthorizationIntent
                and getattr(self.access._connection, '_ordessa_schema_version', None) in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION)):
            action = 'accept_artifact'
        else:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        count = self.access.execute('SELECT count(*) FROM eng_action_consumptions '
            'WHERE realm_id=? AND project_id=? AND approval_id=? AND action=?',
            self._prefix() + (ref.approval_id, action)).fetchone()[0]
        return {'action': action, 'limit': grant.intent.action_budget, 'consumed': count,
                'control': self.get_control(ref)}

    def put_apply(self, receipt):
        self.require_apply_schema()
        self.access.require_write()
        if type(receipt) is not ChangeApplicationReceipt:
            raise ApplicationError('INVALID_ARGUMENT')
        self._scope(receipt)
        grant = self.get_grant(receipt.approval_ref)
        intent = grant.intent
        if (type(intent) is not ChangeAuthorizationIntent or receipt.intent_digest != intent.digest
                or receipt.change_set != intent.change_set
                or {m.proposed_ref for m in receipt.mutations} != set(intent.targets)
                or tuple(m.expected for m in receipt.mutations) != tuple(sorted(intent.expected_heads, key=lambda h: h.artifact_id))
                or self.get_control(receipt.approval_ref) != {'state': 'granted',
                    'version': receipt.grant_control_version, 'revoked_at': None}):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        row = self.access.execute('SELECT approval_id,action,intent_digest,target_digest,consumed_at '
            'FROM eng_action_consumptions WHERE realm_id=? AND project_id=? AND action_instance_id=?',
            self._prefix() + (receipt.action_instance_id,)).fetchone()
        if row != (receipt.approval_ref.approval_id, 'apply_change', intent.digest.hex,
                   intent.change_set.digest.hex, receipt.applied_at):
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        from .artifact_repository import SQLiteArtifactRepository
        artifacts = SQLiteArtifactRepository(self.access)
        for mutation in receipt.mutations:
            owner = artifacts.get_artifact(mutation.expected.artifact_id)
            if owner.version != mutation.expected.version + 1 or owner.head_revision_id != mutation.proposed_ref.revision_id:
                raise ApplicationError('VERSION_CONFLICT')
            artifacts.resolve_revision(mutation.proposed_ref)
        raw = canonical_bytes(asdict(receipt))
        if decode_application_receipt(raw) != receipt:
            raise ApplicationError('RECORD_CORRUPT')
        self.access.execute('INSERT INTO eng_apply_records VALUES (?,?,?,?,?,?,?)',
            self._prefix() + (receipt.apply_id, receipt.action_instance_id,
                receipt.approval_ref.approval_id, receipt.digest.hex, raw))

    def get_apply(self, apply_id):
        self.require_apply_schema()
        validate_id(apply_id)
        row = self.access.execute('SELECT digest,canonical_bytes FROM eng_apply_records '
            'WHERE realm_id=? AND project_id=? AND apply_id=?', self._prefix() + (apply_id,)).fetchone()
        if row is None:
            raise ApplicationError('NOT_FOUND')
        from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
        try:
            receipt = decode_application_receipt(bytes(row[1]))
            self._scope(receipt)
            if receipt.apply_id != apply_id or receipt.digest.hex != row[0]:
                raise ApplicationError('RECORD_CORRUPT')
            return receipt
        except ReferenceError as exc:
            raise ApplicationError('RECORD_CORRUPT') from exc
