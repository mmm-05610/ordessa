"""Frozen plans, complete review predicates and controls on the original UoW.

This adapter owns neither a connection nor authentication. Callers isolate
mutations in their active UoW, and trusted application ports admit evidence.
"""
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.changes.refs import (ProposalRef)
from ordessa_engineering.domain.reviews.refs import (ReviewRef)
from ordessa_engineering.domain.common.models.values import (Digest, validate_id)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.reviews.models import (
    ControlledReview,
    ReviewControl,
    ReviewControlExpectation,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    ReviewSetExpectation,
    ReviewSetKey,
    ReviewSetSnapshot,
    ReviewRequestState,
    ReviewRequestExpectation,
)
from ordessa_engineering.domain.reviews.targets import SourceTargetRef
from ordessa_engineering.domain.common.models.values import (MAX_VERSION)
from .artifact_repository import SQLiteArtifactRepository
from .material_validation import MaterialBudget
from .blob_bytes import BlobBytesError, read_bytes, validate_ref
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION
from .dispatch_schema import WORK_DISPATCH_SCHEMA_VERSION
from ordessa_engineering.domain.reviews.codec import (
    decode_control, decode_key, decode_plan, decode_record, decode_requirement,
    encode_control, encode_key, encode_plan, encode_record, encode_requirement,
)

_MAX_ROWS = 4096
_MAX_SET_BYTES = 64 * 1024 * 1024
_MAX_RAW_SET_BYTES = 64 * 1024 * 1024
# SQLite returns at most the bounded record; corrupt CHECK-bypass rows never
# materialize an unbounded BLOB in Python. Invalid types/lengths decode closed.
_BYTES = "CASE WHEN typeof(canonical_bytes)='blob' AND length(canonical_bytes)<=2097152 THEN canonical_bytes ELSE NULL END"
_KEY_BYTES = "CASE WHEN typeof(canonical_key)='blob' AND length(canonical_key)<=2097152 THEN canonical_key ELSE NULL END"


def _fail(code):
    raise ApplicationError(code)


def _version(value):
    if type(value) is not int or not 0 <= value <= MAX_VERSION:
        _fail('INVALID_ARGUMENT')


def _decode(function, raw):
    try:
        return function(raw)
    except (ReferenceError, TypeError, ValueError, OverflowError, RecursionError):
        _fail('RECORD_CORRUPT')


def _encode(function, value):
    try:
        return function(value)
    except (ReferenceError, TypeError, ValueError, OverflowError, RecursionError):
        _fail('INVALID_ARGUMENT')


class SQLiteReviewRepository:
    def __init__(self, access):
        self.access = access
        self.artifacts = SQLiteArtifactRepository(access)

    def _scope(self):
        self.access.check_active()
        scope = self.access.scope
        if type(scope) is not Scope:
            _fail('SCOPE_MISMATCH')
        return scope

    def _prefix(self):
        scope = self._scope()
        return scope.realm_id, scope.project_id

    def _scoped(self, value_scope):
        if value_scope != self._scope():
            _fail('SCOPE_MISMATCH')

    @staticmethod
    def validate_id(value):
        try:
            validate_id(value)
        except (ReferenceError, TypeError, ValueError):
            _fail('INVALID_ARGUMENT')

    def _targets(self, requirement, *, budget=None, checks=None):
        budget=MaterialBudget(self.access) if budget is None else budget
        if type(budget) is not MaterialBudget or budget.access is not self.access:
            _fail('INVALID_ARGUMENT')
        # Exact references resolve against their actual same-TX owners.
        revisions={}
        artifact_refs=tuple(t.ref for t in requirement.expected_targets.targets if type(t.ref) is ArtifactRevisionRef)
        if artifact_refs:
            revisions={r.ref:r for r in self.artifacts.resolve_graph(artifact_refs,budget=budget)}
        for target in requirement.expected_targets.targets:
            if type(target.ref) is ProposalRef:
                if getattr(self.access._connection,'_ordessa_schema_version',None) not in (7, 8, 9, 10, 11, 12, 13, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                    _fail('UNSUPPORTED_REFERENCE_KIND')
                from .proposal_repository import SQLiteProposalRepository
                SQLiteProposalRepository(self.access).get_proposal(target.ref,budget=budget)
            elif type(target.ref) is SourceTargetRef:
                # External pins are validated by the guarded application source
                # admission before writes. Historical reads verify only the
                # immutable canonical record and never require the provider to
                # remain available.
                if requirement.schema_version != 2 or target.ref.scope != requirement.scope:
                    _fail('UNSUPPORTED_REFERENCE_KIND')
            elif type(target.ref) is not ArtifactRevisionRef:
                _fail('UNSUPPORTED_REFERENCE_KIND')
        for key in requirement.required_check_keys if checks is None else checks:
            if key.claim_id is not None:
                revision=revisions.get(key.target.ref)
                if revision is None or not any(c.claim_id==key.claim_id for c in revision.claims):
                    _fail('UNSUPPORTED_CLAIM')
        return budget

    def _resolve_record(self, record, *, stored=False, verified_raw=None, budget=None):
        budget=MaterialBudget(self.access) if budget is None else budget
        try:
            if record.raw_response_ref is not None:
                try:
                    ref = validate_ref(self.access.authority_id, record.raw_response_ref)
                    identity = (ref.digest.hex, ref.byte_length)
                    budget.reserve((ref,))
                    if verified_raw is None or identity not in verified_raw:
                        read_bytes(self.access,self.access.authority_id,ref)
                        if verified_raw is not None:
                            verified_raw.add(identity)
                except BlobBytesError:
                    _fail("RECORD_CORRUPT" if stored else "REVIEW_RAW_RESPONSE_INVALID")
            self._targets(record.plan.requirement,budget=budget,checks=record.plan.check_keys)
            refs = [r for obs in record.observations for r in obs.evidence_refs]
            refs.extend(r for proof in record.applicability_proofs for r in proof.evidence_refs)
            if record.body_ref is not None:
                refs.append(record.body_ref)
            if refs:
                self.artifacts.resolve_graph(tuple(dict.fromkeys(refs)),budget=budget)
        except ApplicationError as exc:
            if stored and exc.code in {"NOT_FOUND", "UNSUPPORTED_REFERENCE_KIND", "UNSUPPORTED_CLAIM",
                                       "SCOPE_MISMATCH", "RECORD_CORRUPT"}:
                _fail("RECORD_CORRUPT")
            raise

    def _requirement(self, identifier, version):
        row = self.access.execute(
            'SELECT digest,' + _BYTES + ' FROM eng_review_requirements '
            'WHERE realm_id=? AND project_id=? AND requirement_id=? AND requirement_version=?',
            self._prefix() + (identifier, version)).fetchone()
        if row is None:
            _fail('NOT_FOUND')
        requirement = _decode(decode_requirement, row[1])
        if (requirement.scope != self._scope() or requirement.requirement_id != identifier
                or requirement.requirement_version != version or requirement.digest.hex != row[0]):
            _fail('RECORD_CORRUPT')
        return requirement, row[1]

    def get_requirement(self, identifier, requirement_version):
        self.validate_id(identifier)
        _version(requirement_version)
        if requirement_version == 0:
            _fail("INVALID_ARGUMENT")
        return self._requirement(identifier, requirement_version)[0]

    def ensure_requirement(self, requirement, *, budget=None):
        self.access.require_write()
        raw = _encode(encode_requirement, requirement)
        self._scoped(requirement.scope)
        self._targets(requirement,budget=budget)
        prefix = self._prefix()
        identity = prefix + (requirement.requirement_id, requirement.requirement_version)
        existing = self.access.execute(
            'SELECT digest,' + _BYTES + ' FROM eng_review_requirements '
            'WHERE realm_id=? AND project_id=? AND requirement_id=? AND requirement_version=?', identity).fetchone()
        if existing is None:
            self.access.execute('INSERT INTO eng_review_requirements VALUES (?,?,?,?,?,?)',
                identity + (requirement.digest.hex, raw))
            key = ReviewSetKey.for_requirement(requirement)
            self.access.execute('INSERT INTO eng_review_sets VALUES (?,?,?,?,?,?,0)',
                prefix + (key.digest.hex, requirement.requirement_id, requirement.requirement_version,
                          _encode(encode_key, key)))
        else:
            self._requirement(requirement.requirement_id, requirement.requirement_version)
            if existing != (requirement.digest.hex, raw):
                _fail('REQUIREMENT_CONFLICT')
        key = ReviewSetKey.for_requirement(requirement)
        self._set(key)
        return key

    def _set(self, key):
        if type(key) is not ReviewSetKey:
            _fail('INVALID_ARGUMENT')
        self._scoped(key.scope)
        row = self.access.execute(
            'SELECT requirement_id,requirement_version,' + _KEY_BYTES + ',set_version '
            'FROM eng_review_sets WHERE realm_id=? AND project_id=? AND set_digest=?',
            self._prefix() + (key.digest.hex,)).fetchone()
        if row is None:
            _fail('NOT_FOUND')
        stored_key = _decode(decode_key, row[2])
        requirement, _ = self._requirement(row[0], row[1])
        if (stored_key != key or ReviewSetKey.for_requirement(requirement) != key
                or type(row[3]) is not int or not 0 <= row[3] <= MAX_VERSION):
            _fail('RECORD_CORRUPT')
        return requirement, row[3]

    def create_plan(self, plan):
        self.access.require_write()
        raw = _encode(encode_plan, plan)
        self._scoped(plan.scope)
        budget=self._targets(plan.requirement,checks=plan.check_keys)
        key = self.ensure_requirement(plan.requirement,budget=budget)
        existing = self.access.execute('SELECT ' + _BYTES + ' FROM eng_review_plans '
            'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (plan.review_id,)).fetchone()
        if existing is not None:
            stored = self.get_plan(plan.review_id)
            if stored != plan or existing[0] != raw:
                _fail('REVIEW_IDENTITY_CONFLICT')
            return self.get_request(plan.review_id)
        self.access.execute('INSERT INTO eng_review_plans VALUES (?,?,?,?,?,?)',
            self._prefix() + (plan.review_id, key.digest.hex, plan.plan_digest.hex, raw))
        self.access.execute('INSERT INTO eng_review_requests VALUES (?,?,?,\'requested\',1,0)',
            self._prefix() + (plan.review_id,))
        return self.get_request(plan.review_id)

    def get_plan(self, review_id):
        self.validate_id(review_id)
        row = self.access.execute('SELECT set_digest,plan_digest,' + _BYTES + ' FROM eng_review_plans '
            'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (review_id,)).fetchone()
        if row is None:
            _fail('NOT_FOUND')
        plan = _decode(decode_plan, row[2])
        key = ReviewSetKey.for_requirement(plan.requirement)
        if (plan.review_id != review_id or plan.scope != self._scope()
                or plan.plan_digest.hex != row[1] or key.digest.hex != row[0]):
            _fail('RECORD_CORRUPT')
        requirement, _ = self._set(key)
        if plan.requirement != requirement:
            _fail('RECORD_CORRUPT')
        return plan

    def get_request(self, review_id):
        self.get_plan(review_id)
        row = self.access.execute('SELECT state,fence,version FROM eng_review_requests '
            'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (review_id,)).fetchone()
        if (row is None or row[0] not in {'requested', 'recorded', 'withdrawn'}
                or type(row[1]) is not int or not 1 <= row[1] <= MAX_VERSION
                or type(row[2]) is not int or not 0 <= row[2] <= MAX_VERSION):
            _fail('RECORD_CORRUPT')
        return ReviewRequestState(self._scope(), review_id, *row)

    def withdraw_request(self, review_id, *, expected_version, fence):
        self.access.require_write()
        _version(expected_version)
        _version(fence)
        request = self.get_request(review_id)
        if request.state != 'requested' or request.version != expected_version or request.fence != fence:
            _fail('REVIEW_REQUEST_CHANGED')
        if max(request.version, request.fence) == MAX_VERSION:
            _fail('VERSION_EXHAUSTED')
        cursor = self.access.execute('UPDATE eng_review_requests SET state=\'withdrawn\',fence=fence+1,version=version+1 '
            'WHERE realm_id=? AND project_id=? AND review_id=? AND state=\'requested\' AND fence=? AND version=?',
            self._prefix() + (review_id, fence, expected_version))
        if cursor.rowcount != 1:
            _fail('REVIEW_REQUEST_CHANGED')
        return self.get_request(review_id)

    def _bump(self, key, expected):
        if expected == MAX_VERSION:
            _fail('VERSION_EXHAUSTED')
        cursor = self.access.execute('UPDATE eng_review_sets SET set_version=set_version+1 '
            'WHERE realm_id=? AND project_id=? AND set_digest=? AND set_version=?',
            self._prefix() + (key.digest.hex, expected))
        if cursor.rowcount != 1:
            _fail('REVIEW_SET_CHANGED')

    def insert_review(self, record, *, expected_request_version, fence):
        self.access.require_write()
        raw = _encode(encode_record, record)
        self._scoped(record.plan.scope)
        _version(expected_request_version)
        _version(fence)
        plan = self.get_plan(record.plan.review_id)
        if plan != record.plan:
            _fail('REVIEW_STALE')
        existing = self.access.execute('SELECT ' + _BYTES + ' FROM eng_reviews '
            'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (plan.review_id,)).fetchone()
        if existing is not None:
            current = self.get_review(record.ref)
            if existing[0] != raw or current.record != record:
                _fail('REVIEW_IDENTITY_CONFLICT')
            return current.record.ref
        request = self.get_request(plan.review_id)
        if request.state != 'requested' or request.version != expected_request_version or request.fence != fence:
            _fail('REVIEW_REQUEST_CHANGED')
        if request.version == MAX_VERSION:
            _fail('VERSION_EXHAUSTED')
        self._resolve_record(record)
        key = ReviewSetKey.for_requirement(plan.requirement)
        _, set_version = self._set(key)
        if set_version == MAX_VERSION:
            _fail('VERSION_EXHAUSTED')
        control = ReviewControl(self._scope(), plan.review_id)
        control_bytes = _encode(encode_control, control)
        self.access.execute('INSERT INTO eng_reviews VALUES (?,?,?,?,?,?)',
            self._prefix() + (plan.review_id, key.digest.hex, record.digest.hex, raw))
        self.access.execute('INSERT INTO eng_review_controls VALUES (?,?,?,\'active\',0,?)',
            self._prefix() + (plan.review_id, control_bytes))
        self.access.execute('INSERT INTO eng_review_control_events VALUES (?,?,?,0,?)',
            self._prefix() + (plan.review_id, control_bytes))
        cursor = self.access.execute('UPDATE eng_review_requests SET state=\'recorded\',version=version+1 '
            'WHERE realm_id=? AND project_id=? AND review_id=? AND state=\'requested\' AND fence=? AND version=?',
            self._prefix() + (plan.review_id, fence, expected_request_version))
        if cursor.rowcount != 1:
            _fail('REVIEW_REQUEST_CHANGED')
        self._bump(key, set_version)
        return record.ref

    def _control(self, record):
        prefix = self._prefix() + (record.plan.review_id,)
        row = self.access.execute('SELECT state,version,' + _BYTES + ' FROM eng_review_controls '
            'WHERE realm_id=? AND project_id=? AND review_id=?', prefix).fetchone()
        if row is None:
            _fail('RECORD_CORRUPT')
        control = _decode(decode_control, row[2])
        if (control.scope != self._scope() or control.review_id != record.plan.review_id
                or (control.state, control.version) != row[:2]):
            _fail('RECORD_CORRUPT')
        # The only permitted lifecycle is active v0 -> terminal v1. History
        # and its materialized projection must agree, including their bytes.
        events = self.access.execute('SELECT version,' + _BYTES + ' FROM eng_review_control_events '
            'WHERE realm_id=? AND project_id=? AND review_id=? ORDER BY version LIMIT 3', prefix).fetchall()
        if control.version not in {0, 1} or len(events) != control.version + 1:
            _fail('RECORD_CORRUPT')
        initial = _encode(encode_control, ReviewControl(self._scope(), record.plan.review_id))
        if events[0] != (0, initial) or events[-1] != (control.version, row[2]):
            _fail('RECORD_CORRUPT')
        if control.version == 1 and control.state == 'active':
            _fail('RECORD_CORRUPT')
        return control

    def get_review(self, ref):
        return self._get_review(ref)

    def _get_review(self, ref, verified_raw=None, *, budget=None):
        if type(ref) is not ReviewRef:
            _fail('INVALID_ARGUMENT')
        self._scoped(Scope(ref.realm_id, ref.project_id))
        row = self.access.execute('SELECT set_digest,digest,' + _BYTES + ' FROM eng_reviews '
            'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (ref.review_id,)).fetchone()
        if row is None:
            _fail('NOT_FOUND')
        record = _decode(decode_record, row[2])
        if (record.plan.review_id != ref.review_id or record.plan.scope != self._scope()
                or record.digest.hex != row[1] or ReviewSetKey.for_requirement(record.plan.requirement).digest.hex != row[0]
                or record.plan != self.get_plan(ref.review_id)):
            _fail('RECORD_CORRUPT')
        self._resolve_record(record, stored=True, verified_raw=verified_raw,budget=budget)
        if record.ref != ref:
            _fail('REVIEW_IDENTITY_CONFLICT')
        request = self.get_request(ref.review_id)
        if request.state != 'recorded':
            _fail('RECORD_CORRUPT')
        return ControlledReview(record, self._control(record))

    def read_set(self, key, *, budget=None):
        budget=MaterialBudget(self.access) if budget is None else budget
        requirement, set_version = self._set(key)
        cursor = self.access.execute('SELECT review_id,digest,length(canonical_bytes) FROM eng_reviews '
            'WHERE realm_id=? AND project_id=? AND set_digest=? ORDER BY review_id LIMIT ?',
            self._prefix() + (key.digest.hex, _MAX_ROWS + 1))
        rows = cursor.fetchall()
        if (len(rows) > _MAX_ROWS or any(type(row[2]) is not int or not 0 <= row[2] <= 2097152 for row in rows)
                or sum(row[2] for row in rows) > _MAX_SET_BYTES):
            _fail('REVIEW_SET_LIMIT')
        # Before reading any response bodies, bound the distinct content set.
        # A tiny record must not multiply 2 MiB blobs into an unbounded query.
        raw_sizes = {}
        for identifier, _, _ in rows:
            body = self.access.execute('SELECT ' + _BYTES + ' FROM eng_reviews '
                'WHERE realm_id=? AND project_id=? AND review_id=?', self._prefix() + (identifier,)).fetchone()
            if body is None:
                _fail('RECORD_CORRUPT')
            record = _decode(decode_record, body[0])
            ref = record.raw_response_ref
            if ref is not None:
                previous = raw_sizes.setdefault(ref.digest.hex, ref.byte_length)
                if previous != ref.byte_length:
                    _fail('RECORD_CORRUPT')
        if sum(raw_sizes.values()) > _MAX_RAW_SET_BYTES:
            _fail('REVIEW_SET_LIMIT')
        reviews = []
        verified_raw = set()
        for identifier, digest, _ in rows:
            try:
                ref = ReviewRef(*self._prefix(), identifier, Digest('sha256', digest))
            except (ReferenceError, TypeError, ValueError):
                _fail('RECORD_CORRUPT')
            item = self._get_review(ref, verified_raw,budget=budget)
            if item.record.plan.requirement != requirement:
                _fail('RECORD_CORRUPT')
            reviews.append(item)
        try:
            return ReviewSetSnapshot(key, set_version, tuple(reviews))
        except ReferenceError:
            _fail('RECORD_CORRUPT')

    def check_expectations(self, sets=(), controls=(), requests=()):
        budget=MaterialBudget(self.access)
        if (type(sets) is not tuple or type(controls) is not tuple
                or any(type(item) is not ReviewSetExpectation for item in sets)
                or any(type(item) is not ReviewControlExpectation for item in controls)
                or len({item.key for item in sets}) != len(sets)
                or len({item.review_ref for item in controls}) != len(controls)):
            _fail('INVALID_ARGUMENT')
        if (type(requests) is not tuple or len(requests) > _MAX_ROWS
                or any(type(item) is not ReviewRequestExpectation for item in requests)
                or len({item.review_id for item in requests}) != len(requests)):
            _fail('INVALID_ARGUMENT')
        for item in requests:
            if item.scope != self._scope():
                _fail('SCOPE_MISMATCH')
            plan = self.get_plan(item.review_id)
            request = self.get_request(item.review_id)
            if (plan.plan_digest != item.expected_plan_digest
                    or request.version != item.expected_request_version
                    or request.fence != item.expected_fence
                    or request.state != item.expected_state):
                _fail('REVIEW_REQUEST_CHANGED')
        for item in sets:
            if self.read_set(item.key,budget=budget).set_version != item.set_version:
                _fail('REVIEW_SET_CHANGED')
        for item in controls:
            if self._get_review(item.review_ref,budget=budget).control.version != item.version:
                _fail('REVIEW_CONTROL_CHANGED')

    def control_group(self, expectations, *, state, reason, evidence, replacement_ref=None):
        """Trusted control command; all members change or caller rolls back."""
        self.access.require_write()
        if (type(expectations) is not tuple or not expectations or len(expectations) > _MAX_ROWS
                or any(type(item) is not ReviewControlExpectation for item in expectations)
                or len({item.review_ref for item in expectations}) != len(expectations)
                or type(state) is not str or state not in {'voided', 'replaced'}):
            _fail('INVALID_ARGUMENT')
        budget=MaterialBudget(self.access)
        originals = tuple(self._get_review(item.review_ref,budget=budget) for item in expectations)
        requirement = originals[0].record.plan.requirement
        if any(item.record.plan.requirement != requirement for item in originals):
            _fail('REVIEW_STALE')
        key = ReviewSetKey.for_requirement(requirement)
        _, set_version = self._set(key)
        if set_version == MAX_VERSION:
            _fail('VERSION_EXHAUSTED')
        if state == 'replaced':
            replacement = self._get_review(replacement_ref,budget=budget)
            if (replacement.record.plan.requirement != requirement or replacement.control.state != 'active'
                    or replacement_ref in {item.review_ref for item in expectations}):
                _fail('REVIEW_STALE')
        elif replacement_ref is not None:
            _fail('INVALID_ARGUMENT')
        mutations = []
        for expected, original in zip(expectations, originals):
            control = original.control
            if control.state != 'active' or control.version != expected.version:
                _fail('REVIEW_CONTROL_CHANGED')
            try:
                new_control = ReviewControl(self._scope(), control.review_id, state,
                    replacement_ref, reason, evidence, control.version + 1)
            except (ReferenceError, TypeError, ValueError):
                _fail('INVALID_ARGUMENT')
            mutations.append((control, new_control, _encode(encode_control, new_control)))
        for old, new, raw in mutations:
            self.access.execute('INSERT INTO eng_review_control_events VALUES (?,?,?,?,?)',
                self._prefix() + (old.review_id, new.version, raw))
            cursor = self.access.execute('UPDATE eng_review_controls SET state=?,version=?,canonical_bytes=? '
                'WHERE realm_id=? AND project_id=? AND review_id=? AND state=\'active\' AND version=?',
                (new.state, new.version, raw) + self._prefix() + (old.review_id, old.version))
            if cursor.rowcount != 1:
                _fail('REVIEW_CONTROL_CHANGED')
        self._bump(key, set_version)
        return self.read_set(key,budget=budget)
