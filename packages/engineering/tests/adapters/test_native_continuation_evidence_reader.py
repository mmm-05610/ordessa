"""Native continuation evidence: only the original owners' own affirmative read.

Controlled peers only: no Unit, process or model runs. The Blob owner is the
real schema-17 store so the diagnostic reference is read through its authority.
"""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace as dc_replace
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.native_records.recorded_dispatch import (
    NativeContinuationEvidenceReader,
)
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary,
)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_observations import (
    ExecutionObservationRef, OriginPrewriteEvidence,
)
from ordessa_engineering.application.contracts.failure_diagnostic import (
    FAILURE_MEDIA_TYPE, FailureDiagnostic,
)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, DispatchOriginRef, package_ref_projection,
)
from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.encoding.immutable_json import safe_json

SCOPE = Scope('realm-a', 'project-a')
OTHER_SCOPE = Scope('realm-b', 'project-b')
UNIT = {'environmentNamespace': 'env-a', 'unitId': 'unit-a',
        'ownerProviderRef': {'provider': 'owner-a'}, 'sourceRevision': 'rev-1'}
UNIT_BYTES = canonical_bytes(UNIT)
UNIT_DIGEST = 'sha256:' + hashlib.sha256(safe_json(UNIT).encode()).hexdigest()


def digest(text):
    return Digest('sha256', hashlib.sha256(text).hexdigest())


def context(scope=SCOPE):
    return CommandContext(scope=scope, principal_id='principal-a',
                          authenticated_actor=ActorRef('agent', 'agent', 'principal-a'),
                          request_id='req-1', received_at='2026-10-17T14:00:00.000000Z',
                          trace_id='trace-1')


def binding(*, version=2, unit_bytes=UNIT_BYTES):
    package = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-a', digest(b'pkg'))
    common = dict(scope=SCOPE, run_id='w1:work-a', step_id='implement', attempt=1, fence=1,
                  action_instances=(('edit_repository', 'inst-1'),), unit_ref_bytes=unit_bytes,
                  execution_operation_ref='op-a',
                  prompt_ref=BlobRef(digest(b'prompt'), 10, 'application/json', 'prompt'),
                  prompt_input_digest=digest(b'prompt-input'),
                  expected_query_digest='sha256:' + 'q' * 64,
                  required_results=('implementation_report',),
                  package_ref=package,
                  approval_ref=ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-a', digest(b'grant')),
                  intent_digest=digest(b'intent'), control_version=1)
    if version == 1:
        return DispatchBinding(**common)
    return DispatchBinding(
        binding_version=2,
        work={'work_id': 'work-a', 'action_id': 'incremental.implement-package',
              'step_id': 'implement', 'dispatch_key': 'w1:work-a'},
        subject={'subject_kind': 'frozen_package',
                 'subject_ref': package_ref_projection(package)},
        **common)


def native_write(**overrides):
    value = {'contract': 'native-write-boundary/1', 'phase': 'effect_guard_acquire',
             'frame_bytes': 100, 'before_write': 'not_entered', 'write_stdin': 'not_entered',
             'acknowledged_bytes': None, 'operation_ref': 'op-a',
             'input_digest': 'sha256:' + digest(b'prompt-input').hex,
             'unit_ref_digest': UNIT_DIGEST, 'frame_digest': 'sha256:' + 'f' * 64}
    value.update(overrides)
    return value


class _Diagnostics:
    def __init__(self, store):
        self.store = store

    def put(self, diagnostic, **overrides):
        raw = diagnostic.encoded
        ref = self.store.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                      FAILURE_MEDIA_TYPE)
        return canonical_bytes(dict(digest=dict(algorithm=ref.digest.algorithm, hex=ref.digest.hex),
                                    byte_length=ref.byte_length, media_type=ref.media_type,
                                    storage_object_id=ref.storage_object_id)).decode()


class _Factory:
    def __init__(self, row, *, authority_id=None):
        self.row = row
        self.authority_id = authority_id

    @contextmanager
    def begin(self, scope, mode='read'):
        class _UoW:
            work_dispatch = None
        uow = _UoW()
        uow.work_dispatch = SimpleNamespace(get=lambda *args: self.row)
        yield uow


class _Records:
    def __init__(self, *, state='unknown', termination=None, query_digest=None,
                 receipt=None):
        self.state = state
        self.termination = termination
        self.query = query_digest or 'sha256:' + 'q' * 64
        self.receipt = dict(receipt or {})
        self.acp_turn_evidence_max_bytes = 1 << 20

    def acp_turn_query_digest(self, unit, operation_ref, expected_prompt):
        return self.query

    def query_acp_turn(self, unit, operation_ref, invocation, *, input_digest,
                       expected_prompt_input_digest):
        body = {'contractVersion': 'unit-acp-turn/1', 'unitRef': dict(unit),
                'operationRef': operation_ref, 'inputDigest': expected_prompt_input_digest,
                'state': self.state, 'revision': 2,
                'request': None, 'events': [], 'response': None}
        body.update(self.receipt)
        return body

    def owner_read_termination(self, unit_id, action):
        if self.termination is None:
            return None
        if isinstance(self.termination, Exception):
            raise self.termination
        record = dict(self.termination)
        record['action'] = action
        return record


def _origin(binding_value, *, bytes_digest=None, record_digest=None, operation='op-a',
            version=2):
    encoded = encode_dispatch(binding_value)
    return DispatchOriginRef(
        scope=SCOPE, dispatch_key='w1:work-a', step_id='implement', attempt=1,
        execution_operation_ref=operation,
        binding_bytes_digest=bytes_digest or Digest('sha256', hashlib.sha256(encoded).hexdigest()),
        binding_record_digest=record_digest or binding_value.digest,
        expected_dispatch_version=version, expected_acp_revision=2)


def _row(binding_value, *, phase='unknown', version=2, result_json=None, operation='op-a'):
    return {'binding_bytes': encode_dispatch(binding_value),
            'execution_operation_ref': operation, 'dispatch_phase': phase,
            'dispatch_version': version, 'result_blob_json': result_json,
            'continuation': None}


def _reader(factory_row, records, store, *, authority_id='__store__'):
    factory = _Factory(factory_row,
                       authority_id=(store.authority_id if authority_id == '__store__'
                                     else authority_id))
    return NativeContinuationEvidenceReader(
        factory, records, store,
        lambda _binding: SimpleNamespace(facts={'inputDigest': records.query}))


TERMINATION_VERSION = 'harness-unit-termination/1'


def _confirmed(action='stop', **overrides):
    record = {'version': TERMINATION_VERSION, 'projection': 'owner-read', 'action': action,
              'state': 'confirmed', 'sourceRevision': 2,
              'identity': {'unitRef': dict(UNIT), 'operationRef': 'op-a'},
              'outcome': {'confirmation': 'confirmed', 'providerRef': 'provider-a'}}
    record.update(overrides)
    return record


def test_affirmative_prewrite_origin_returns_owner_evidence(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('guard refused'), 'handoff_enter',
                                           native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'case.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = _reader(row, records, store)
        evidence = reader.read_origin(context(), _origin(value))
        assert type(evidence) is OriginPrewriteEvidence
        assert type(evidence.acp_observation) is ExecutionObservationRef
        assert evidence.acp_observation.state == 'unknown'
        assert evidence.stop_record['state'] == 'confirmed'
        assert evidence.release_record['action'] == 'release'
    finally:
        library.close()


def test_operation_bytes_and_record_digests_are_bound(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'a.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value, operation='op-b'))
        assert refused.value.code == 'CONTINUATION_ORIGIN_IDENTITY_MISMATCH'

        # The two digests are different facts: swapping them is refused.
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(
                value, bytes_digest=value.digest, record_digest=Digest(
                    'sha256', hashlib.sha256(encode_dispatch(value)).hexdigest())))
        assert refused.value.code == 'CONTINUATION_ORIGIN_IDENTITY_MISMATCH'

        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value, version=3))
        assert refused.value.code == 'CONTINUATION_ORIGIN_IDENTITY_MISMATCH'

        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(OTHER_SCOPE), _origin(value))
        assert refused.value.code == 'CONTINUATION_ORIGIN_UNAVAILABLE'
    finally:
        library.close()


def test_only_an_unknown_frozen_package_row_qualifies(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'b.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value, phase='possibly_written')
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_ORIGIN_NOT_PREWRITE'

        v1 = binding(version=1)
        v1_row = _row(v1)
        v1_row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        v1_reader = NativeContinuationEvidenceReader(
            _Factory(v1_row, authority_id=store.authority_id), records, store, lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            v1_reader.read_origin(context(), _origin(v1))
        assert refused.value.code == 'CONTINUATION_BINDING_NOT_ELIGIBLE'
    finally:
        library.close()


@pytest.mark.parametrize('overrides,code', [
    ({'before_write': 'entered'}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
    ({'write_stdin': 'entered'}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
    ({'acknowledged_bytes': 10, 'write_stdin': 'returned'}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
    ({'phase': 'before_write'}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
    ({'operation_ref': 'op-other'}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
    ({'unit_ref_digest': 'sha256:' + '0' * 64}, 'CONTINUATION_ORIGIN_NOT_PREWRITE'),
])
def test_diagnostic_must_prove_the_frame_stayed_before_write(tmp_path, overrides, code):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter',
                                           native_write=native_write(**overrides))
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'c.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == code
    finally:
        library.close()


def test_missing_or_incomplete_diagnostic_is_refused(tmp_path):
    value = binding()
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'd.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        reader = NativeContinuationEvidenceReader(
            _Factory(_row(value), authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_DIAGNOSTIC_UNAVAILABLE'

        incomplete = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter',
                                               native_write=native_write()).with_recording_failure(
                                                   RuntimeError('blob write failed'))
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(incomplete)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_DIAGNOSTIC_INCOMPLETE'
    finally:
        library.close()


@pytest.mark.parametrize('state', ['completed', 'failed', 'reserved', 'possibly-written'])
def test_observation_must_stay_unconfirmed(tmp_path, state):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(state=state, termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'e.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_OBSERVATION_UNAVAILABLE'
    finally:
        library.close()


@pytest.mark.parametrize('termination,fragment', [
    (None, 'owner read missing'),
    (_confirmed(state='unknown'), 'state not confirmed'),
    (_confirmed(identity={'unitRef': dict(UNIT, unitId='other-unit')}), 'identity'),
    (_confirmed(version='harness-unit-termination/2'), 'wrong contract version'),
    (_confirmed(projection='projection'), 'wrong projection'),
    (_confirmed(sourceRevision=True), 'non-integer revision'),
    (_confirmed(outcome=None), 'missing provenance outcome'),
    (_confirmed(outcome={}), 'empty outcome'),
    (RuntimeError('historical Unit stays fenced'), 'owner fence'),
])
def test_termination_proof_must_be_the_owners_confirmed_record(tmp_path, termination, fragment):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=termination)
    library = EngineeringLibrary.create((tmp_path / 'f.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_TERMINATION_UNAVAILABLE'
    finally:
        library.close()


def test_empty_events_alone_are_not_enough(tmp_path):
    """An unknown ACP state with no linked diagnostic still never qualifies."""
    value = binding()
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'g.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        reader = NativeContinuationEvidenceReader(
            _Factory(_row(value, result_json=None), authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_DIAGNOSTIC_UNAVAILABLE'
    finally:
        library.close()


def test_missing_query_authority_is_refused(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'h.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = NativeContinuationEvidenceReader(_Factory(row, authority_id=store.authority_id), records, store, lambda _b: None)
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_OBSERVATION_UNAVAILABLE'
    finally:
        library.close()


def test_diagnostic_must_carry_the_failure_media_type(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'i.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        raw = diagnostic.encoded
        wrong = store.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                   'application/json')
        row = _row(value)
        row['result_blob_json'] = canonical_bytes(dict(
            digest=dict(algorithm=wrong.digest.algorithm, hex=wrong.digest.hex),
            byte_length=wrong.byte_length, media_type=wrong.media_type,
            storage_object_id=wrong.storage_object_id)).decode()
        reader = NativeContinuationEvidenceReader(
            _Factory(row, authority_id=store.authority_id), records, store,
            lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_DIAGNOSTIC_UNAVAILABLE'
    finally:
        library.close()


@pytest.mark.parametrize('receipt', [
    {'request': {'frame': 'delivered'}},
    {'response': {'text': 'synthetic'}},
    {'events': [{'method': 'session/prompt'}]},
    {'revision': 3},
])
def test_observation_receipt_must_contradict_a_delivered_frame(tmp_path, receipt):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed(), receipt=receipt)
    library = EngineeringLibrary.create((tmp_path / 'j.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = _reader(row, records, store)
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_OBSERVATION_UNAVAILABLE'
    finally:
        library.close()


def test_observation_query_digest_must_match_the_binding(tmp_path):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed(), query_digest='sha256:' + 'z' * 64)
    library = EngineeringLibrary.create((tmp_path / 'k.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = _reader(row, records, store)
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(), _origin(value))
        assert refused.value.code == 'CONTINUATION_OBSERVATION_UNAVAILABLE'
    finally:
        library.close()


def test_factory_and_blob_authority_must_be_the_same(tmp_path):
    value = binding()
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'l.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        with pytest.raises(ApplicationError) as refused:
            NativeContinuationEvidenceReader(
                _Factory(_row(value), authority_id='another-library'), records, store,
                lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        assert refused.value.code == 'CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE'
        with pytest.raises(ApplicationError) as refused:
            NativeContinuationEvidenceReader(
                _Factory(_row(value)), records, store,
                lambda _b: SimpleNamespace(facts={'inputDigest': records.query}))
        assert refused.value.code == 'CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE'
    finally:
        library.close()


@pytest.mark.parametrize('change', ['dispatch_key', 'step_id', 'attempt', 'scope'])
def test_origin_must_match_the_stored_binding_identity(tmp_path, change):
    value = binding()
    diagnostic = FailureDiagnostic.capture(ValueError('x'), 'handoff_enter', native_write=native_write())
    records = _Records(termination=_confirmed())
    library = EngineeringLibrary.create((tmp_path / 'm.sqlite').resolve(),
                                        library_id='continuation-evidence', schema_version=17)
    store = SQLiteBlobStore(library)
    try:
        row = _row(value)
        row['result_blob_json'] = _Diagnostics(store).put(diagnostic)
        reader = _reader(row, records, store)
        origin = _origin(value)
        if change == 'dispatch_key':
            origin = dc_replace(origin, dispatch_key='w1:other')
        elif change == 'step_id':
            origin = dc_replace(origin, step_id='review')
        elif change == 'attempt':
            origin = dc_replace(origin, attempt=2)
        else:
            origin = dc_replace(origin, scope=Scope('realm-a', 'project-b'))
        with pytest.raises(ApplicationError) as refused:
            reader.read_origin(context(origin.scope), origin)
        assert refused.value.code == 'CONTINUATION_ORIGIN_IDENTITY_MISMATCH'
    finally:
        library.close()


def test_reader_construction_requires_the_original_owners():
    with pytest.raises(ApplicationError) as refused:
        NativeContinuationEvidenceReader(None, None, None, None)
    assert refused.value.code == 'CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE'
