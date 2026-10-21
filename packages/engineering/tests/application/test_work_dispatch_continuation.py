"""Segment-B qualification, unique claim and relation checks for a continuation.

The Execution owner (segment C) is not bound here and is deliberately replaced by
explicit controlled peers: this file proves the owner-side rules that must hold
before any new Unit exists, not a real native read or a real Unit creation.
"""
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from types import MappingProxyType, SimpleNamespace
from dataclasses import asdict, replace

import pytest

from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.failure_diagnostic import FailureDiagnostic
from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
    affirmative_prewrite, claim_continuation, continuation_operation_id,
    verify_continuation_reservation, resolve_continuation_root, ContinuationCandidate,
)
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, DispatchContinuation, DispatchOriginRef, package_ref_projection,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_continuation, encode_continuation, decode_dispatch
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes
from test_review_usecases import SyntheticAccess
from test_review_usecases import _context as _review_context

SCOPE = Scope('realm-1', 'project-1')
WORK_ID, ACTION_ID, STEP = 'work-1', 'implement-package', 'implement'
DISPATCH_KEY = work_dispatch_key(WORK_ID, ACTION_ID, STEP)


def _digest(char):
    return Digest('sha256', char * 64)


def _unit():
    return {'environmentNamespace': 'env-1', 'unitId': 'unit-1',
            'ownerProviderRef': {'brand': 'pi'}, 'sourceRevision': 'rev-1'}


def _package():
    return ImplementationPackageRef('realm-1', 'project-1', 'package-1', _digest('c'))


def _work_binding():
    from ordessa_engineering.application.contracts.work_context import WorkBinding
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    return WorkBinding('work-1', SCOPE,
        MethodRef('ordessa.incremental-engineering', '2.7.2', 1, _digest('8')), 1, ())


def _binding(attempt=1, *, action_instances=(('edit_repository', 'instance-1'),)):
    return DispatchBinding(
        scope=SCOPE, run_id=DISPATCH_KEY, step_id=STEP, attempt=attempt, fence=1,
        package_ref=_package(),
        approval_ref=ApprovalRef('realm-1', 'project-1', 'approval-1', _digest('d')),
        intent_digest=_digest('e'), control_version=0,
        action_instances=action_instances, unit_ref_bytes=canonical_bytes(_unit()),
        execution_operation_ref=f'op-{attempt}',
        prompt_ref=BlobRef(_digest('f'), 10, 'application/json', 'blob-1'),
        prompt_input_digest=_digest('1'), expected_query_digest='query-1',
        required_results=('implementation-report',), binding_version=2,
        work={'work_id': WORK_ID, 'action_id': ACTION_ID, 'step_id': STEP,
              'dispatch_key': DISPATCH_KEY},
        subject={'subject_kind': 'frozen_package',
                 'subject_ref': package_ref_projection(_package())},
    )


def _origin(binding, *, attempt=None, step=None, scope=None, acp_revision=1, dispatch_version=1):
    raw = encode_dispatch_bytes(binding)
    return DispatchOriginRef(
        scope=scope or SCOPE, dispatch_key=DISPATCH_KEY, step_id=step or STEP,
        attempt=attempt if attempt is not None else binding.attempt,
        execution_operation_ref=binding.execution_operation_ref,
        binding_bytes_digest=Digest('sha256', hashlib.sha256(raw).hexdigest()),
        binding_record_digest=binding.digest, expected_dispatch_version=dispatch_version,
        expected_acp_revision=acp_revision)


def encode_dispatch_bytes(binding):
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
    return encode_dispatch(binding)


def _continuation(origin, successor, **overrides):
    values = dict(
        origin=origin, reservation_origin=origin,
        causal_operation_id=continuation_operation_id(origin.scope, origin),
        failure_evidence_ref=BlobRef(_digest('2'), 10, 'application/json', 'diag-blob'),
        acp_observation_ref=BlobRef(_digest('3'), 10, 'application/json', 'acp-blob'),
        acp_revision=1, stop_proof_ref='stop-proof-1', release_proof_ref='release-proof-1',
        semantic_prompt_digest=Digest('sha256', hashlib.sha256(canonical_bytes([])).hexdigest()),
        successor_binding_record_digest=successor.digest)
    values.update(overrides)
    return DispatchContinuation(**values)


def _context(request_id='continuation-request-1', principal='principal-1'):
    return replace(_review_context(SCOPE, request_id), principal_id=principal)


class _Entry:
    def __init__(self, operation_id, principal_id, request_id, state='pending', version=0):
        self.operation_id, self.principal_id = operation_id, principal_id
        self.request_id, self.state, self.version = request_id, state, version


class _Reservation:
    def __init__(self, entry, created):
        self.entry, self.created = entry, created


class _Journal:
    """Controlled journal peer: the one (realm, operation_id) uniqueness rule."""

    def __init__(self):
        self.by_key = {}
        self.by_operation = {}

    def reserve(self, key, *, project_id, operation, operation_id, request_digest):
        existing = self.by_key.get((key.realm_id, key.principal_id, key.request_id))
        if existing is not None:
            return _Reservation(existing, False)
        if operation_id in self.by_operation:
            raise ApplicationError('OPERATION_ID_CONFLICT')
        entry = _Entry(operation_id, key.principal_id, key.request_id)
        self.by_key[(key.realm_id, key.principal_id, key.request_id)] = entry
        self.by_operation[operation_id] = entry
        return _Reservation(entry, True)

    def find_operation(self, scope, operation_id, *, operation):
        return self.by_operation.get(operation_id)


class _Uow:
    def __init__(self):
        self.commands = _Journal()
        self.authorization = _RecordingAuthorization()


class _RecordingAuthorization:
    def __init__(self):
        self.calls = []

    def check_action_consumptions(self, ref, *, intent_digest, target_digest, action_instances):
        self.calls.append({'ref': ref, 'intent_digest': intent_digest,
                           'target_digest': target_digest, 'action_instances': action_instances})


def _candidate(origin, binding, attempt=None):
    return ContinuationCandidate(
        work=None, origin=origin, origin_binding=binding,
        diagnostic=FailureDiagnostic.capture(ValueError('controlled'), 'native_send'),
        failure_evidence_ref=BlobRef(_digest('5'), 10, 'application/json', 'diag-blob'),
        evidence=None, attempt=attempt if attempt is not None else origin.attempt + 1,
        actions=tuple(action for action, _ in binding.action_instances))


def test_operation_id_is_derived_from_the_origin_and_never_caller_selected():
    binding = _binding()
    origin = _origin(binding)
    first = continuation_operation_id(SCOPE, origin)
    assert first == continuation_operation_id(SCOPE, _origin(_binding()))
    assert first.startswith('work-continuation-')
    assert len(first) == len('work-continuation-') + 64
    assert first != continuation_operation_id(SCOPE, _origin(_binding(attempt=2)))
    assert first != continuation_operation_id(SCOPE, _origin(binding, step='other-step'))
    other_scope = Scope('realm-2', 'project-1')
    assert first != continuation_operation_id(
        other_scope, _origin(binding, scope=other_scope))
    with pytest.raises(ApplicationError, match='CONTINUATION_ORIGIN_INVALID'):
        continuation_operation_id(SCOPE, 'not-an-origin')


def test_claim_creates_one_row_and_a_competing_request_only_sees_it():
    binding = _binding()
    origin = _origin(binding)
    uow = _Uow()
    first = claim_continuation(uow, _context('request-a'), _candidate(origin, binding), _digest('a'))
    assert first.created is True
    assert first.operation_id.startswith('work-continuation-')

    # A different request id and a different principal derive the same causal
    # operation id: only the occupied row is visible, nothing is created twice.
    second = claim_continuation(uow, _context('request-b', 'principal-2'),
                                _candidate(origin, binding), _digest('b'))
    assert second.created is False
    assert second.operation_id == first.operation_id
    assert second.entry.principal_id == 'principal-1'
    assert second.entry.request_id == 'request-a'
    assert len(uow.commands.by_operation) == 1


def test_claim_replays_the_same_request_without_a_second_row():
    binding = _binding()
    origin = _origin(binding)
    uow = _Uow()
    context = _context('request-a')
    first = claim_continuation(uow, context, _candidate(origin, binding), _digest('a'))
    replay = claim_continuation(uow, context, _candidate(origin, binding), _digest('a'))
    assert replay.created is False
    assert replay.operation_id == first.operation_id
    assert len(uow.commands.by_key) == 1


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def get(self, key, step, attempt, scope):
        return self.rows[(key, step, attempt)]


class _Causal:
    def __init__(self, entries):
        self.entries = entries

    def find_operation(self, scope, operation_id, *, operation):
        return self.entries.get(operation_id)


class _Blobs:
    def __init__(self):
        self.reads = []

    def read_blob(self, ref):
        self.reads.append(ref)
        return b'{}'


class _VerifyUow:
    def __init__(self, rows, entries):
        self.work_dispatch = _Rows(rows)
        self.commands = _Causal(entries)
        self.implementation = _Blobs()
        payloads = {}
        for row in rows.values():
            binding = decode_dispatch(row['binding_bytes'])
            payloads[binding.prompt_ref] = canonical_bytes({'prompt': []})
            continuation = row.get('continuation')
            if continuation is None:
                continue
            ref = continuation.origin
            predecessor = decode_dispatch(rows[(ref.dispatch_key, ref.step_id, ref.attempt)]['binding_bytes'])
            native = _native(operation_ref=predecessor.execution_operation_ref,
                input_digest='sha256:' + predecessor.prompt_input_digest.hex,
                unit_ref_digest='sha256:' + hashlib.sha256(predecessor.unit_ref_bytes).hexdigest())
            payloads[continuation.failure_evidence_ref] = _diagnostic(native).encoded
            payloads[continuation.acp_observation_ref] = canonical_bytes({'state': 'unknown',
                'revision': continuation.acp_revision, 'operationRef': predecessor.execution_operation_ref,
                'unitRef': json.loads(predecessor.unit_ref_bytes),
                'inputDigest': 'sha256:' + predecessor.prompt_input_digest.hex,
                'request': None, 'response': None, 'events': []})
        self.implementation.read_blob = lambda ref: payloads[ref]
        self.authorization = _RecordingAuthorization()


def _row(binding, continuation=None, dispatch_version=1):
    raw = encode_dispatch_bytes(binding)
    return {'run_id': binding.run_id, 'step_id': binding.step_id, 'attempt': binding.attempt,
            # The row stores the digest of the exact stored bytes; the record
            # digest is a different value and is only used by continuation refs
            # and the original consumption check.
            'binding_bytes': raw, 'binding_digest': Digest('sha256', hashlib.sha256(raw).hexdigest()),
            'execution_operation_ref': binding.execution_operation_ref,
            'dispatch_version': dispatch_version, 'dispatch_phase': 'unknown',
            'result_blob_json': None if continuation is not None else canonical_bytes(asdict(
                BlobRef(_digest('2'), 10, 'application/json', 'diag-blob'))).decode(),
            'continuation': continuation}


def _entry(state='pending'):
    return _Entry('work-continuation-' + '0' * 64, 'principal-1', 'request-a', state=state)


def test_verify_walks_the_stored_marker_chain_and_returns_the_root():
    origin = _binding()
    successor = _binding(attempt=2)
    origin_ref = _origin(origin)
    continuation = _continuation(origin_ref, successor)
    rows = {(DISPATCH_KEY, STEP, 1): _row(origin), (DISPATCH_KEY, STEP, 2): _row(successor, continuation)}
    causal = _entry()
    causal.operation_id = continuation_operation_id(SCOPE, origin_ref)
    entries = {causal.operation_id: causal}
    uow = _VerifyUow(rows, entries)

    root = verify_continuation_reservation(uow, successor)
    assert root == origin                      # the root comes from the stored rows
    assert len(uow.authorization.calls) == 1
    call = uow.authorization.calls[0]
    assert call['ref'] == origin.approval_ref
    assert call['target_digest'] == origin.digest   # record digest, not the bytes digest
    assert call['action_instances'] == origin.action_instances
    # An ordinary first-attempt marker claims no predecessor: None, no refusal.
    assert verify_continuation_reservation(uow, origin) is None

    # A successor that does not name this exact binding is refused.
    other = _binding(attempt=2, action_instances=(('edit_repository', 'instance-2'),))
    with pytest.raises(ApplicationError, match='CONTINUATION_RELATION_INVALID'):
        verify_continuation_reservation(_VerifyUow({**rows, (DISPATCH_KEY, STEP, 2): _row(other, continuation)}, entries), other)
    # A missing causal journal row is refused.
    with pytest.raises(ApplicationError, match='CONTINUATION_RELATION_INVALID'):
        verify_continuation_reservation(_VerifyUow(rows, {}), successor)
    # A predecessor whose bytes/record digests disagree with the named origin is refused.
    shifted = _continuation(origin_ref, successor, successor_binding_record_digest=successor.digest)
    bad_rows = {**rows, (DISPATCH_KEY, STEP, 2): _row(successor, shifted)}
    tampered = {**rows, (DISPATCH_KEY, STEP, 1): {**_row(origin), 'dispatch_version': 7}}
    with pytest.raises(ApplicationError, match='CONTINUATION_ORIGIN_MISMATCH'):
        verify_continuation_reservation(_VerifyUow({**tampered, (DISPATCH_KEY, STEP, 2): _row(successor, shifted)}, entries), successor)
    # A chain that skips an attempt is refused: attempt 3 may only follow 2.
    third = _binding(attempt=3)
    with pytest.raises(ApplicationError, match='CONTINUATION_RELATION_INVALID'):
        verify_continuation_reservation(
            _VerifyUow({**rows, (DISPATCH_KEY, STEP, 3): _row(third, _continuation(origin_ref, third))},
                       entries), third)


def _native(**overrides):
    value = {'contract': 'native-write-boundary/1', 'phase': 'effect_guard_acquire',
             'frame_bytes': 42, 'before_write': 'not_entered', 'write_stdin': 'not_entered',
             'acknowledged_bytes': None, 'operation_ref': 'op-1',
             'input_digest': 'sha256:' + _binding().prompt_input_digest.hex,
             'unit_ref_digest': 'sha256:' + hashlib.sha256(_binding().unit_ref_bytes).hexdigest(),
             'frame_digest': 'sha256:' + 'c' * 64}
    value.update(overrides)
    return value


def _diagnostic(native):
    return FailureDiagnostic.capture(ValueError('controlled'), 'native_send', native_write=native)


def test_only_an_affirmative_prewrite_diagnostic_qualifies():
    binding = _binding()
    affirmative_prewrite(_diagnostic(_native()), binding)
    for entered in ({'phase': 'write_stdin'},
                    {'before_write': 'entered'},
                    {'write_stdin': 'entered'},
                    {'phase': 'before_write'},
                    {'operation_ref': 'op-2'}):
        with pytest.raises(ApplicationError, match='CONTINUATION_EVIDENCE_INVALID'):
            affirmative_prewrite(_diagnostic(_native(**entered)), binding)
    with pytest.raises(ApplicationError, match='CONTINUATION_EVIDENCE_INVALID'):
        affirmative_prewrite(_diagnostic(None), binding)


def test_continuation_codec_keeps_its_own_closed_shape():
    origin_binding = _binding()
    successor = _binding(attempt=2)
    continuation = _continuation(_origin(origin_binding), successor)
    raw = encode_continuation(continuation)
    # The round trip keeps the exact bytes, and an unknown version/field is
    # refused rather than being read as a binding or the v1 marker.
    assert encode_continuation(decode_continuation(raw)) == raw
    assert decode_continuation(raw) == continuation
    altered = canonical_bytes(dict(__import__('json').loads(raw), schema_version=2))
    with pytest.raises(Exception):
        decode_continuation(altered)


def _work_use_cases():
    from ordessa_engineering.application.usecases.works import WorkUseCases
    return WorkUseCases(None, SyntheticAccess())


def test_invoke_v2_is_its_own_closed_identity_next_to_the_untouched_v1():
    from ordessa_engineering.application.contracts.commands import (
        ReadSet, request_digest, read_set_projection)
    from ordessa_engineering.application.usecases.works import (
        _CONTINUATION_SCHEMA_BYTES, _SCHEMA_BYTES, input_schema)
    from ordessa_engineering.domain.common.models.values import Digest
    from test_review_usecases import _context as review_context

    usecases = _work_use_cases()
    context = review_context(SCOPE, 'continuation-request-1')
    v1 = {'work_id': 'work-1', 'action_id': 'implement-package', 'inputs': {}}
    v2 = {'invocation_version': 2, 'work_id': 'work-1', 'action_id': 'implement-package',
          'inputs': {}, 'continuation_of': {'execution_operation_ref': 'op-1',
                                             'expected_dispatch_version': 1,
                                             'expected_acp_revision': 1}}
    # The v1 schema keeps its id, required set and byte digest; the v2 schema is
    # a separate closed identity and never accepts the other shape.
    assert input_schema('engineering.work.invoke')['$id'].endswith(':input:1')
    assert input_schema('engineering.work.invoke', 2)['$id'].endswith(':input:2')
    assert input_schema('engineering.work.invoke')['required'] == ['work_id', 'action_id', 'inputs']
    for rejected, version in ((v1, 2), (v2, 1)):
        with pytest.raises(ApplicationError, match='INVALID_INPUT'):
            usecases._input('engineering.work.invoke', rejected, context, None, version=version)
    for broken in ({**v2, 'continuation_of': {**v2['continuation_of'], 'attempt': 2}},
                   {**v2, 'continuation_of': {**v2['continuation_of'],
                                              'expected_acp_revision': True}},
                   {**v2, 'continuation_of': {**v2['continuation_of'],
                                              'expected_dispatch_version': 0}},
                   {**v2, 'attempt': 2}):
        with pytest.raises(ApplicationError, match='INVALID_INPUT'):
            usecases._input('engineering.work.invoke', broken, context, None, version=2)

    _, reads, v1_digest = usecases._input('engineering.work.invoke', v1, context, None)
    _, _, v2_digest = usecases._input('engineering.work.invoke', v2, context, None, version=2)
    assert v1_digest != v2_digest
    # The v2 digest is the documented identity: v2 schema id, schema-2 bytes and
    # interface version "2" — not the v1 identity recomputed with new content.
    expected = request_digest('engineering.work.invoke', context, v2,
        read_set_projection(ReadSet(context.scope, ())),
        input_schema_id='urn:ordessa:engineering:operations:engineering.work.invoke:input:2',
        input_schema_digest=Digest('sha256', hashlib.sha256(
            _CONTINUATION_SCHEMA_BYTES['engineering.work.invoke']).hexdigest()),
        interface_version='2')
    assert v2_digest == expected
    assert v1_digest == request_digest('engineering.work.invoke', context, v1,
        read_set_projection(ReadSet(context.scope, ())),
        input_schema_id='urn:ordessa:engineering:operations:engineering.work.invoke:input:1',
        input_schema_digest=Digest('sha256', hashlib.sha256(
            _SCHEMA_BYTES['engineering.work.invoke']).hexdigest()),
        interface_version='1')


def test_continuation_claim_requires_a_candidate_and_digest():
    from ordessa_engineering.application.usecases.works import WorkUseCases
    from ordessa_engineering.application.contracts.commands import CommandContext
    from test_review_usecases import _context as review_context

    class _Factory:
        def begin(self, scope, mode='write'):
            raise AssertionError('a refused claim must not open a transaction')

    usecases = WorkUseCases(_Factory(), SyntheticAccess())
    context = review_context(SCOPE, 'continuation-request-1')
    # A claim carries the request digest of the exact v2 request; anything that
    # is not a digest is refused before a transaction is opened.
    with pytest.raises(ApplicationError, match='INVALID_INPUT'):
        usecases.begin_continuation_claim(context, 'not-a-candidate', 'not-a-digest')


def _bootstrap_owner(factory):
    """The two owner methods only need their own factory and the send capability."""
    from types import SimpleNamespace
    from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
    owner = object.__new__(EngineeringOwnerOperations)
    owner.factory = factory
    owner.dispatch = SimpleNamespace(_access=lambda context, operation: None)
    return owner


def _real_factory(tmp_path):
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import WORK_DISPATCH_SCHEMA_VERSION
    lib = EngineeringLibrary.create((tmp_path / 'continuation.sqlite').resolve(),
                                    library_id='continuation-test',
                                    schema_version=WORK_DISPATCH_SCHEMA_VERSION)
    return SQLiteUoWFactory(lib)


def test_continuation_unit_bootstrap_reserves_once_completes_only_its_row(tmp_path):
    from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
        CONTINUATION_OPERATION, ContinuationCandidate, continuation_operation_id)
    from ordessa_engineering.domain.changes.dispatch import DispatchOriginRef
    from test_review_usecases import _context as review_context

    factory = _real_factory(tmp_path)
    origin_binding = _binding()
    origin = _origin(origin_binding)
    candidate = ContinuationCandidate(
        work=_work_binding(), origin=origin, origin_binding=origin_binding,
        diagnostic=FailureDiagnostic.capture(ValueError('controlled'), 'native_send'),
        failure_evidence_ref=BlobRef(_digest('5'), 10, 'application/json', 'diag-blob'),
        evidence=None, attempt=2, actions=('edit_repository',))
    context = review_context(SCOPE, continuation_operation_id(SCOPE, origin))
    # The causal continuation claim this caller already owns must be pending.
    with factory.begin(SCOPE) as uow:
        uow.commands.reserve(context.key, project_id=SCOPE.project_id,
            operation=CONTINUATION_OPERATION, operation_id=context.request_id,
            request_digest=_digest('9'))
        uow.commit()

    owner = _bootstrap_owner(factory)
    profile = {'profile_id': 'profile-1'}
    identity = 'sha256:' + 'a' * 64
    first = owner.reserve_continuation_unit_bootstrap(context, candidate, profile, identity)
    assert first.created is True
    # A second reservation on the same identity only observes the pending row.
    second = owner.reserve_continuation_unit_bootstrap(context, candidate, profile, identity)
    assert second.created is False
    assert second.entry == first.entry

    unit = {'environmentNamespace': 'env-1', 'unitId': 'unit-1',
            'ownerProviderRef': {'brand': 'pi'}, 'sourceRevision': 'rev-1'}
    owner.complete_continuation_unit_bootstrap(context, first, unit)
    with factory.begin(SCOPE, 'read') as uow:
        bootstrap = uow.commands.find_operation(SCOPE, first.entry.operation_id,
            operation='engineering.execution.unit-bootstrap') if hasattr(uow.commands, 'find_operation') else None
        claim = uow.commands.find_operation(SCOPE, context.request_id, operation=CONTINUATION_OPERATION)
    assert claim is not None and claim.state == 'pending'   # claim stays for dispatch
    # Completing again is refused: the bootstrap row is no longer pending.
    with pytest.raises(ApplicationError, match='CONTINUATION_BOOTSTRAP_BINDING_MISMATCH'):
        owner.complete_continuation_unit_bootstrap(context, first, unit)


def test_continuation_unit_bootstrap_refuses_foreign_or_stale_identity(tmp_path):
    from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
        ContinuationCandidate, continuation_operation_id)
    from test_review_usecases import _context as review_context

    factory = _real_factory(tmp_path)
    candidate = ContinuationCandidate(
        work=_work_binding(), origin=_origin(_binding()), origin_binding=_binding(),
        diagnostic=FailureDiagnostic.capture(ValueError('controlled'), 'native_send'),
        failure_evidence_ref=BlobRef(_digest('5'), 10, 'application/json', 'diag-blob'),
        evidence=None, attempt=2, actions=('edit_repository',))
    owner = _bootstrap_owner(factory)
    # A context whose request id is not this origin's causal id is refused before
    # any row is written.
    with pytest.raises(ApplicationError, match='CONTINUATION_OPERATION_MISMATCH'):
        owner.reserve_continuation_unit_bootstrap(review_context(SCOPE, 'some-other-request'),
            candidate, {'profile_id': 'profile-1'}, 'sha256:' + 'a' * 64)
    # Without the pending continuation claim the bootstrap is refused too.
    context = review_context(SCOPE, continuation_operation_id(SCOPE, candidate.origin))
    with pytest.raises(ApplicationError, match='CONTINUATION_CLAIM_UNAVAILABLE'):
        owner.reserve_continuation_unit_bootstrap(context, candidate,
            {'profile_id': 'profile-1'}, 'sha256:' + 'a' * 64)


# Public schema17 graph. Only the native transport, Unit bootstrap and historical
# evidence producer below are controlled peers. Work/Grant/debits/dispatch/blobs/
# reports/independent review/assignment/journal use their original repositories.

from test_work_package_dispatch_v2 import dispatch_fixture, UNIT, ENVIRONMENT
from test_declared_implementation_results import _prepare_flow
from test_real_source_chain import context as graph_context, SCOPE as GRAPH_SCOPE
from ordessa_engineering.application.contracts.execution_observations import (
    ExecutionObservationRef, OriginPrewriteEvidence)


@contextmanager
def _public_continuation_graph(tmp_path, monkeypatch, review='pass', boundary='effect_guard_acquire',
                               align_unit_scope=False):
    import test_work_package_dispatch_v2 as fixture_module
    if align_unit_scope:
        selected = replace(ENVIRONMENT, environment_id=GRAPH_SCOPE.realm_id)
        monkeypatch.setattr(fixture_module, 'ENVIRONMENT', selected)
        monkeypatch.setattr(fixture_module, 'UNIT', {**UNIT, 'environmentNamespace': GRAPH_SCOPE.realm_id})
    seed_unit = fixture_module.UNIT
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        f, parameters, seed_context, _, _ = _prepare_flow(f, review, 'seed-unknown-work')
        service, transport, access = f['service'], f['transport'], f['access']
        active = ContextVar('controlled-work-sub-admission', default=None)
        original_admit = access.admit_work_step

        @contextmanager
        def admit(ctx, operation, *, request_id):
            with original_admit(ctx, operation, request_id=request_id) as child:
                token = active.set((operation, child))
                try:
                    yield child
                finally:
                    active.reset(token)
        monkeypatch.setattr(access, 'admit_work_step', admit)

        def freeze(unit, task):
            transport.freezes += 1
            raw = canonical_bytes({**task, 'sessionId': 'controlled-session-' + unit['unitId']})
            return raw, Digest('sha256', hashlib.sha256(raw).hexdigest())

        @contextmanager
        def select(ctx, package, unit, authorization, params):
            assert unit in f['controlled_units']
            assert params['sessionId'] == 'controlled-session-' + unit['unitId']
            assert authorization.package_ref == package.ref
            yield dict(f['authorization'].scope_by_action)['edit_repository'].environment_refs[0]
        f['controlled_units'] = [seed_unit]
        monkeypatch.setattr(transport, 'freeze_input', freeze)
        monkeypatch.setattr(f['selection'], 'guard_work_selection', select)

        def send(binding, *, timeout):
            transport.binding = binding
            if transport.before_write:
                transport.before_write(binding)
            async def write():
                identity = {'unitRef': json.loads(binding.unit_ref_bytes),
                    'operationRef': binding.execution_operation_ref,
                    'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
                    'requestId': 'controlled-native-frame', 'frameDigest': 'sha256:' + 'e' * 64}
                async with transport.dispatch.acquire_effect_write(transport.ctx, binding, identity,
                        asyncio.get_running_loop().time() + 2, handoff=transport.handoff):
                    transport.sends += 1
            if 'effect_executor' in f:
                f['effect_executor'].submit(lambda: asyncio.run(write())).result()
            else:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(lambda: asyncio.run(write())).result()
        monkeypatch.setattr(transport, 'send', send)

        def diagnostic(binding, error, stage):
            return FailureDiagnostic.capture(error, stage, native_write={
                'contract': 'native-write-boundary/1', 'phase': boundary, 'frame_bytes': 42,
                'before_write': 'not_entered', 'write_stdin': 'not_entered',
                'acknowledged_bytes': None, 'operation_ref': binding.execution_operation_ref,
                'input_digest': 'sha256:' + binding.prompt_input_digest.hex,
                'unit_ref_digest': 'sha256:' + hashlib.sha256(binding.unit_ref_bytes).hexdigest(),
                'frame_digest': 'sha256:' + 'e' * 64})
        monkeypatch.setattr(transport, 'failure_diagnostic', diagnostic, raising=False)
        def fail_before_write(_binding):
            raise OSError('controlled affirmative prewrite failure')
        transport.before_write = fail_before_write
        with pytest.raises(ApplicationError, match='WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'):
            asyncio.run(service.execute('engineering.work.invoke', parameters, seed_context))
        transport.before_write = None
        auth = f['authorization']
        key = work_dispatch_key(auth.work_id, auth.action_id, auth.step_id)
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            origin_row = uow.work_dispatch.get(key, auth.step_id, 1, GRAPH_SCOPE)
            origin = decode_dispatch(origin_row['binding_bytes'])
        assert origin_row['dispatch_phase'] == 'unknown' and transport.sends == 0
        counters = {'reader': 0, 'bootstrap': 0}
        def check_admission(ctx):
            assert active.get() == ('engineering.executions.dispatch', ctx)
        f['check_query_admission'] = check_admission

        class Reader:
            def read_origin(self, ctx, ref):
                f['check_query_admission'](ctx)
                counters['reader'] += 1
                with f['factory'].begin(ctx.scope, 'read') as uow:
                    recorded = uow.work_dispatch.get(ref.dispatch_key, ref.step_id, ref.attempt, ctx.scope)
                    source = decode_dispatch(recorded['binding_bytes'])
                # Explicit controlled historical owner, never a real history claim.
                body = canonical_bytes({'contractVersion': 'unit-acp-turn/1', 'state': 'unknown',
                    'revision': 2, 'operationRef': ref.execution_operation_ref,
                    'unitRef': json.loads(source.unit_ref_bytes),
                    'inputDigest': 'sha256:' + source.prompt_input_digest.hex,
                    'request': None, 'response': None, 'events': []})
                blob = f['env'].blobs.put_verified(body,
                    Digest('sha256', hashlib.sha256(body).hexdigest()), 'application/json')
                observation = ExecutionObservationRef(json.loads(source.unit_ref_bytes),
                    ref.execution_operation_ref, 'sha256:' + source.prompt_input_digest.hex,
                    source.expected_query_digest, 'unknown', 2, blob, f['factory'].authority_id)
                def proof(action):
                    return {'version': 'harness-unit-termination/1', 'projection': 'owner-read',
                        'action': action, 'state': 'confirmed', 'sourceRevision': 2,
                        'identity': {'unitRef': json.loads(source.unit_ref_bytes)},
                        'outcome': MappingProxyType({'terminationEvidenceRef': 'controlled-' + action + '-proof'})}
                return OriginPrewriteEvidence(observation, proof('stop'), proof('release'))

        def bootstrap(ctx, candidate, inputs):
            f['check_query_admission'](ctx)
            owner = f['service']._execution_dispatch
            reservation = owner.reserve_continuation_unit_bootstrap(
                ctx, candidate, inputs['profile'], 'sha256:' + 'a' * 64)
            assert reservation.created
            from contextlib import nullcontext
            with f['bootstrap_guard'](ctx) if 'bootstrap_guard' in f else nullcontext():
                counters['bootstrap'] += 1
                unit = {**seed_unit, 'unitId': 'controlled-successor-' + str(candidate.attempt)}
                f['controlled_units'].append(unit)
            owner.complete_continuation_unit_bootstrap(ctx, reservation, unit)
            return unit
        service._continuation_evidence = Reader()
        service._continuation_unit_resolver = bootstrap
        value = {**parameters, 'invocation_version': 2,
            'continuation_of': {'execution_operation_ref': origin.execution_operation_ref,
                'expected_dispatch_version': origin_row['dispatch_version'], 'expected_acp_revision': 2}}
        origin_sql = tuple(f['env'].library._connection.execute(
            'SELECT * FROM work_step_log WHERE dispatch_key=? AND step_id=? AND attempt=1',
            (key, auth.step_id)).fetchone())
        f.update(v2=value, origin=origin, origin_row=origin_row, origin_sql=origin_sql, seed_context=seed_context,
                 counters=counters, dispatch_key=key)
        yield f


def _protected_rows(f):
    db = f['env'].library._connection
    return {table: tuple(tuple(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY rowid'))
            for table in ('eng_approval_grants', 'eng_action_consumptions')}


@pytest.mark.parametrize('review', ['pass', 'fail'])
def test_public_v2_continuation_registers_new_report_review_and_preserves_business_round(
        tmp_path, monkeypatch, review):
    with _public_continuation_graph(tmp_path, monkeypatch, review) as f:
        before = _protected_rows(f)
        service = f['service']
        ctx = graph_context('public-continuation-' + review)
        answer = asyncio.run(service.execute('engineering.work.invoke', f['v2'], ctx))
        assert answer.status == 'completed'
        assert len(answer.result['steps']) == 4
        assert answer.result['method_result']['disposition'] == ('accepted' if review == 'pass' else 'rejected')
        assert (answer.result['method_result']['rework_request'] is not None) is (review == 'fail')
        assert f['counters'] == {'reader': 1, 'bootstrap': 1}
        assert f['transport'].sends == 1 and len(f['review_source'].calls) == 1
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            old = uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 1, GRAPH_SCOPE)
            new = uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 2, GRAPH_SCOPE)
            bound = decode_dispatch(new['binding_bytes'])
            root = resolve_continuation_root(uow, bound)
            assert root == f['origin'] and root.attempt == 1
            assert old == f['origin_row']
            assert bound.action_instances == root.action_instances
            assert bound.unit_ref_bytes != root.unit_ref_bytes
            assert bound.execution_operation_ref != root.execution_operation_ref
            assert answer.result['method_result']['implementation_operation_ref'] == bound.execution_operation_ref
            from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref
            submission = uow.submissions.resolve(decode_subject_ref(answer.result['method_result']['submission_ref']))
            assert submission.execution_ref.operation_ref == bound.execution_operation_ref
            assert submission.execution_ref.unit_id == json.loads(bound.unit_ref_bytes)['unitId']
            assert uow.commands.get(f['seed_context'].key).state == 'pending'
        assert _protected_rows(f) == before
        assert tuple(f['env'].library._connection.execute(
            'SELECT * FROM work_step_log WHERE dispatch_key=? AND step_id=? AND attempt=1',
            (f['dispatch_key'], f['origin'].step_id)).fetchone()) == f['origin_sql']
        assert f['env'].library._connection.execute('SELECT COUNT(*) FROM eng_acceptance_receipts').fetchone()[0] == 0
        replay = asyncio.run(service.execute('engineering.work.invoke', f['v2'], ctx))
        assert replay.result_bytes == answer.result_bytes
        assert f['counters'] == {'reader': 1, 'bootstrap': 1}
        assert f['transport'].sends == 1 and len(f['review_source'].calls) == 1


@pytest.mark.parametrize('same_request', [False, True])
def test_public_v2_request_competition_claims_one_successor(tmp_path, monkeypatch, same_request):
    from threading import Barrier
    with _public_continuation_graph(tmp_path, monkeypatch) as f:
        before = _protected_rows(f)
        rendezvous = Barrier(2)
        original = f['service']._works.begin_continuation_claim
        def claim(ctx, candidate, digest):
            rendezvous.wait(timeout=10)
            return original(ctx, candidate, digest)
        monkeypatch.setattr(f['service']._works, 'begin_continuation_claim', claim)
        def invoke(request):
            try:
                return asyncio.run(f['service'].execute('engineering.work.invoke', f['v2'], graph_context(request)))
            except ApplicationError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(invoke, ('racing-a', 'racing-a' if same_request else 'racing-b')))
        assert sum(getattr(x, 'status', None) == 'completed' for x in outcomes) == 1
        assert 'CONTINUATION_ALREADY_CLAIMED' in outcomes
        assert f['counters']['bootstrap'] == 1 and f['transport'].sends == 1
        assert _protected_rows(f) == before


@pytest.mark.parametrize('case', ['entered', 'revoked', 'wrong-revision', 'changed-package', 'missing-review', 'root-debit', 'work-revision'])
def test_public_v2_refuses_before_bootstrap(tmp_path, monkeypatch, case):
    boundary = 'write_stdin' if case == 'entered' else 'effect_guard_acquire'
    with _public_continuation_graph(tmp_path, monkeypatch, boundary=boundary) as f:
        value = json.loads(canonical_bytes(f['v2']))
        if case == 'root-debit':
            # Explicit invalid seed through the lower repository: an ordinary
            # root with no matching debit must not inherit another root's debit.
            # Original consumption rows remain immutable; no trigger is disabled.
            unfunded = replace(f['origin'], attempt=2, execution_operation_ref='controlled-unfunded-root')
            raw = encode_dispatch_bytes(unfunded)
            from ordessa_engineering.application.contracts.failure_diagnostic import FAILURE_MEDIA_TYPE
            diagnostic = f['transport'].failure_diagnostic(unfunded, OSError('controlled invalid seed'), 'native_send')
            blob = f['env'].blobs.put_verified(diagnostic.encoded,
                Digest('sha256', hashlib.sha256(diagnostic.encoded).hexdigest()), FAILURE_MEDIA_TYPE)
            with f['factory'].begin(GRAPH_SCOPE) as uow:
                uow.work_dispatch.reserve(unfunded.run_id, unfunded.step_id, 2, GRAPH_SCOPE,
                    raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), unfunded.execution_operation_ref)
                uow.work_dispatch.transition(unfunded.run_id, unfunded.step_id, 2, GRAPH_SCOPE,
                    expected_version=0, fence=1, phase='possibly_written')
                uow.work_dispatch.transition(unfunded.run_id, unfunded.step_id, 2, GRAPH_SCOPE,
                    expected_version=1, fence=1, phase='unknown', result_blob_ref=blob)
                uow.commit()
            value['continuation_of'] = {'execution_operation_ref': unfunded.execution_operation_ref,
                'expected_dispatch_version': 2, 'expected_acp_revision': 2}
        before = _protected_rows(f)
        if case == 'work-revision':
            value['expected_revision'] = 99
        if case == 'revoked':
            from test_real_source_chain import NOW
            with f['factory'].begin(GRAPH_SCOPE) as uow:
                uow.authorization.revoke(f['grant_ref'], 0, NOW, 'controlled revoke', 'revoke-v2')
                uow.commit()
        elif case == 'wrong-revision':
            value['continuation_of']['expected_dispatch_version'] += 1
        elif case == 'changed-package':
            value['inputs']['package']['digest']['hex'] = '0' * 64
        elif case == 'missing-review':
            f['service']._implementation_results.review_run = None
        expected = {'entered': 'CONTINUATION_EVIDENCE_INVALID', 'revoked': 'APPROVAL_CONTROL_CHANGED',
            'wrong-revision': 'CONTINUATION_ORIGIN_MISMATCH', 'changed-package': 'CONTINUATION_ORIGIN_MISMATCH',
            'missing-review': 'WORK_ACTION_UNAVAILABLE', 'root-debit': 'DISPATCH_BUDGET_BINDING_MISMATCH',
            'work-revision': 'WORK_REVISION_STALE'}
        with pytest.raises(ApplicationError) as refusal:
            asyncio.run(f['service'].execute('engineering.work.invoke', value, graph_context('refuse-' + case)))
        assert refusal.value.code == expected[case]
        assert f['counters']['bootstrap'] == 0 and f['transport'].sends == 0
        assert _protected_rows(f) == before


def test_public_v2_uncertain_successor_keeps_causal_pending_and_replay_does_not_create(tmp_path, monkeypatch):
    with _public_continuation_graph(tmp_path, monkeypatch) as f:
        before = _protected_rows(f)
        def fail(_binding):
            raise OSError('controlled successor stayed before native write')
        f['transport'].before_write = fail
        ctx = graph_context('unknown-successor')
        with pytest.raises(ApplicationError, match='WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED'):
            asyncio.run(f['service'].execute('engineering.work.invoke', f['v2'], ctx))
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            assert uow.commands.get(ctx.key).state == 'pending'
            assert uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 2,
                                         GRAPH_SCOPE)['dispatch_phase'] == 'unknown'
        replay = asyncio.run(f['service'].execute('engineering.work.invoke', f['v2'], ctx))
        assert replay.status == 'pending' and replay.result_bytes is None
        assert f['counters']['bootstrap'] == 1 and f['transport'].sends == 0
        assert _protected_rows(f) == before
        # A later explicit request can continue this new affirmative UNKNOWN;
        # the old pending request itself never retries or creates another Unit.
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            second = uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 2, GRAPH_SCOPE)
        third = {**f['v2'], 'continuation_of': {
            'execution_operation_ref': second['execution_operation_ref'],
            'expected_dispatch_version': second['dispatch_version'], 'expected_acp_revision': 2}}
        f['transport'].before_write = None
        answer = asyncio.run(f['service'].execute('engineering.work.invoke', third,
            graph_context('explicit-next-technical-attempt')))
        assert answer.status == 'completed' and f['transport'].sends == 1
        assert f['counters']['bootstrap'] == 2
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            latest = uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 3, GRAPH_SCOPE)
            assert resolve_continuation_root(uow, decode_dispatch(latest['binding_bytes'])) == f['origin']
            assert uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 2, GRAPH_SCOPE) == second
        assert _protected_rows(f) == before


def test_read_only_root_projection_keeps_business_root_attempt_without_consumption_api():
    root, successor = _binding(attempt=2), _binding(attempt=3)
    ref = _origin(root)
    continuation = _continuation(ref, successor)
    rows = {(DISPATCH_KEY, STEP, 2): _row(root), (DISPATCH_KEY, STEP, 3): _row(successor, continuation)}
    causal = _entry()
    causal.operation_id = continuation_operation_id(SCOPE, ref)
    uow = _VerifyUow(rows, {causal.operation_id: causal})
    assert resolve_continuation_root(uow, successor) == root
    assert root.attempt == 2 and uow.authorization.calls == []
    assert verify_continuation_reservation(uow, successor) == root
    assert uow.authorization.calls[0]['target_digest'] == root.digest


def test_public_v2_uses_original_instance_admission_bootstrap_and_sdk_handoff(tmp_path, monkeypatch):
    """Real instance ACL/leases and SDK-thread handoff; controlled Unit/model only."""
    from datetime import datetime, timezone
    from threading import current_thread
    import time
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    from ordessa_agents.profiles import decode_revision_ref
    from ordessa_units.assembly import UnitRunPermission
    from test_declared_implementation_results import _assembly
    from test_real_source_chain import NOW, PRINCIPAL
    import ordessa_system_access_bindings.engineering as access_module

    class FixedClock:
        @staticmethod
        def now(tz=None):
            return datetime.fromisoformat(NOW.replace('Z', '+00:00')).astimezone(tz or timezone.utc)

    with _public_continuation_graph(tmp_path, monkeypatch, align_unit_scope=True) as f:
        monkeypatch.setattr(access_module, 'datetime', FixedClock)
        scope = WireScope(GRAPH_SCOPE.realm_id, GRAPH_SCOPE.project_id)
        capabilities = tuple(f['service']._commands) + ('engineering.executions.dispatch',
            'engineering.work.get', 'execution.units.prepare', 'execution.units.start',
            'execution.units.interaction', 'execution.units.stop', 'execution.units.release')
        authority = InstanceAccessAuthority(lambda: 'controlled-v2-bearer',
            principal_id=PRINCIPAL, legacy_principal=None, grants=(AccessGrant(scope, capabilities),))
        caller = authority.authenticate('Bearer controlled-v2-bearer')
        access = EngineeringCommandAccess(authority)
        reader, resolver = f['service']._continuation_evidence, f['service']._continuation_unit_resolver
        _assembly(f, f['records'], 'pass', access=access, expected_scope=scope)
        service = f['service']
        service._continuation_evidence, service._continuation_unit_resolver = reader, resolver
        def check(ctx):
            assert access.current_context() is ctx
            access.require(ctx, 'engineering.executions.dispatch')
        f['check_query_admission'] = check
        root = tmp_path / 'controlled-current-unit-permission'
        root.mkdir()
        permission = UnitRunPermission(access_authority=authority, principal=caller, scope=scope,
            agent_id='controlled-v2-agent', profile_revision=decode_revision_ref(f['v2']['inputs']['profile']),
            environment_identity='controlled-v2-environment', root_directory=str(root),
            actions=frozenset({'prepare', 'start', 'interaction', 'stop', 'release'}),
            expires_at=time.time() + 60)
        f['bootstrap_guard'] = lambda ctx: access.guard_unit_bootstrap(ctx, permission=permission)

        @contextmanager
        def handoff(ctx, binding, *, access, timeout):
            f['transport'].ctx = ctx
            with ThreadPoolExecutor(max_workers=1) as executor:
                target = executor.submit(current_thread).result()
                with access.handoff_effect_write(ctx, invocation_key=bytes.fromhex(binding.digest.hex),
                        action_instances=binding.action_instances, target_thread=target,
                        expires_at=time.monotonic() + min(timeout, 30)) as token:
                    f['effect_executor'] = executor
                    f['transport'].handoff = token
                    try:
                        yield
                    finally:
                        f.pop('effect_executor')
        monkeypatch.setattr(f['transport'], 'guard_effect_handoff', handoff)
        before = _protected_rows(f)
        with access.admit(caller, scope, 'engineering.work.invoke', request_id='real-admission-v2',
                          trace_id='controlled-schema17-graph') as ctx:
            answer = asyncio.run(service.execute('engineering.work.invoke', f['v2'], ctx))
            access.require(ctx, 'engineering.work.invoke')
        assert answer.status == 'completed'
        assert answer.result['method_result']['disposition'] == 'accepted'
        assert f['counters']['bootstrap'] == 1 and f['transport'].sends == 1
        assert _protected_rows(f) == before


def test_owner_termination_reference_accepts_immutable_mapping_and_refuses_missing_proof():
    from ordessa_engineering.application.api.service import _termination_ref
    record = MappingProxyType({'outcome': MappingProxyType({'terminationEvidenceRef': 'owner-proof'})})
    assert _termination_ref(record, 'stop_record') == 'owner-proof'
    for invalid in ({'outcome': {}}, {'outcome': {'terminationEvidenceRef': ''}},
                    {'outcome': {'terminationEvidenceRef': True}}, {'proof_ref': 'invented'}):
        with pytest.raises(ApplicationError, match='CONTINUATION_EVIDENCE_INVALID'):
            _termination_ref(invalid, 'stop_record')


@pytest.mark.parametrize('review', ['pass', 'fail'])
def test_case_consumer_preflight_and_formal_wire_share_real_continuation_records(
        tmp_path, monkeypatch, review):
    """Real Engineering/wire graph; native history, Unit and model are controlled.

    This supplements (does not replace) the original-owner composition tests.
    The case consumer and M2 are loaded unchanged; no fake Grant reader,
    _BoundFactory, invoke handler or execute_case is installed.
    """
    import importlib.util
    from pathlib import Path
    import sys
    import time
    from datetime import datetime, timezone
    from threading import current_thread
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant, InstanceAccessAuthority
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
    from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts, EngineeringWireBinding
    import ordessa_system_access_bindings.engineering as access_module
    from test_declared_implementation_results import _assembly
    from test_real_source_chain import NOW, PRINCIPAL

    root = Path(__file__).resolve().parents[4]
    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, root / relative)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    entry = load('combined_declared_entry_' + review,
                 'tooling/checks/server_product/run_declared_work_case.py')
    monkeypatch.setattr(entry, 'NIGHTLY', tmp_path)
    case_module = load('combined_instruction_case_' + review,
                      'tooling/checks/server_product/local_library_instruction_case.py')

    class FixedClock:
        @staticmethod
        def now(tz=None):
            return datetime.fromisoformat(NOW.replace('Z', '+00:00')).astimezone(tz or timezone.utc)
    monkeypatch.setattr(access_module, 'datetime', FixedClock)
    with _public_continuation_graph(tmp_path, monkeypatch, review, align_unit_scope=True) as f:
        scope = WireScope(GRAPH_SCOPE.realm_id, GRAPH_SCOPE.project_id)
        capabilities = tuple(f['service']._commands) + (
            'engineering.executions.dispatch', 'engineering.work.get', 'engineering.operations.get')
        authority = InstanceAccessAuthority(lambda: 'controlled-combined-bearer',
            principal_id=PRINCIPAL, legacy_principal=None, grants=(AccessGrant(scope, capabilities),))
        caller = authority.authenticate('Bearer controlled-combined-bearer')
        access = EngineeringCommandAccess(authority)
        reader, resolver = f['service']._continuation_evidence, f['service']._continuation_unit_resolver
        _assembly(f, f['records'], review, access=access, expected_scope=scope)
        service = f['service']
        service._continuation_evidence, service._continuation_unit_resolver = reader, resolver
        def check(ctx):
            assert access.current_context() is ctx
            access.require(ctx, 'engineering.executions.dispatch')
        f['check_query_admission'] = check

        # Use the original public wire methods; only host registry plumbing is
        # selected here. Product/LocalUnitOwner composition is a separate test.
        wire = object.__new__(EngineeringWireBinding)
        wire.scope, wire.factory, wire.access, wire.service = scope, f['factory'], access, service
        wire.execution_dispatch = service._execution_dispatch
        wire.dispatch_routes = None
        wire.declared_generation_dispatch, wire.ports = None, EngineeringApplicationPorts()
        methods = {descriptor.method_id: descriptor for descriptor in wire.methods()}
        graph = Path(f['factory'].library.path).parent
        product = graph / 'product'
        product.mkdir()
        runtime = SimpleNamespace(data_root=product,
            plugin_host=SimpleNamespace(methods=SimpleNamespace(lookup=methods.get)))
        cloned = entry.verify_clone_root(graph, {'engineering.sqlite': hashlib.sha256(
            Path(f['factory'].library.path).read_bytes()).hexdigest()})
        cloned.update(clone_manifest={}, clone_library=str(graph / 'engineering.sqlite'),
                      clone_product_root=str(product))
        cloned['graph_binding'] = entry._register_graph_binding(entry.CloneGraphBinding(
            runtime=runtime, factory=f['factory'], access=access,
            library_path=str(graph / 'engineering.sqlite'), library_id=f['factory'].library.library_id,
            clone_root=str(graph), product_root=str(product), token=object()))
        source = tmp_path / 'controlled-source.py'
        source.write_text('# controlled source pin\n')
        pins = tmp_path / 'sources.json'
        pins.write_text(json.dumps({str(source): hashlib.sha256(source.read_bytes()).hexdigest()}))
        auth = f['authorization']
        expected = dict(work_id=auth.work_id, action_id=auth.action_id, step_id=auth.step_id,
            work_revision=1, package_digest=auth.package_ref.digest.hex,
            intent_digest=f['intent'].digest.hex, actions=list(auth.actions), required_capabilities=[])
        selector = entry.continuation_selector(operation_ref=f['origin'].execution_operation_ref,
            attempt=f['origin'].attempt, dispatch_version=f['origin_row']['dispatch_version'], acp_revision=2)
        evidence = tmp_path / 'evidence.json'
        evidence.write_text(json.dumps({'grant': dict(expected, ref=asdict(f['grant_ref']),
            digest=f['intent'].digest.hex), 'budget': {'actions': {
                action: {'limit': 1, 'consumed': 1} for action in auth.actions}},
            'permission_capabilities': []}))
        case = dict(grant=entry.validate_evidence_reference(evidence, expected,
                mode='continuation', origin=selector), grant_ref=asdict(f['grant_ref']),
            expectations=expected, library_id=f['factory'].library.library_id,
            pins={'sources_path': str(pins), 'sources_sha256': hashlib.sha256(pins.read_bytes()).hexdigest()},
            clone=cloned)
        owner = entry.read_case_records(factory=f['factory'], scope=scope, grant_ref=case['grant_ref'],
            expectations=expected, mode='continuation', origin=selector)
        assert owner['origin'] == selector and owner['mode'] == 'continuation'
        for field, changed in (('attempt', 2), ('expected_dispatch_version', 3)):
            with pytest.raises(entry.PreparationRefusal) as refused:
                entry.read_case_records(factory=f['factory'], scope=scope, grant_ref=case['grant_ref'],
                    expectations=expected, mode='continuation', origin={**selector, field: changed})
            assert refused.value.code == entry.CONTINUATION_ORIGIN_MISMATCH
        assert f['counters']['bootstrap'] == 0

        policy = object.__new__(case_module.FrozenScope)
        policy.holder, policy.review_id = {'factory': f['factory'], 'scope': GRAPH_SCOPE}, None
        monkeypatch.setattr(case_module, 'WORK', auth.work_id)
        def current_grant(uow):
            return (uow.authorization.get_grant(f['grant_ref']), None,
                    uow.authorization.get_control(f['grant_ref']))
        monkeypatch.setattr(policy, 'grant', current_grant)
        callbacks = []
        @contextmanager
        def handoff(ctx, binding, *, access, timeout):
            f['transport'].ctx = ctx
            with ThreadPoolExecutor(max_workers=1) as executor:
                target = executor.submit(current_thread).result()
                with access.handoff_effect_write(ctx, invocation_key=bytes.fromhex(binding.digest.hex),
                        action_instances=binding.action_instances, target_thread=target,
                        expires_at=time.monotonic() + min(timeout, 30)) as token:
                    f['effect_executor'], f['transport'].handoff = executor, token
                    try:
                        yield
                    finally:
                        f.pop('effect_executor')
        monkeypatch.setattr(f['transport'], 'guard_effect_handoff', handoff)
        original_send = f['transport'].send
        def send_with_callback(binding, *, timeout):
            original_send(binding, timeout=timeout)
            # Native file callbacks happen after the stdin write cut closes,
            # while the persisted dispatch is still possibly_written.
            successor = json.loads(binding.unit_ref_bytes)
            with policy.callback(unit_ref=successor, session_id='controlled',
                    method='fs/write_text_file', params={}):
                callbacks.append(successor)
            from ordessa_units.api import UnitApiRefused
            with pytest.raises(UnitApiRefused):
                with policy.callback(unit_ref=json.loads(f['origin'].unit_ref_bytes),
                        session_id='controlled', method='fs/write_text_file', params={}):
                    raise AssertionError('predecessor must never gain successor callbacks')
        monkeypatch.setattr(f['transport'], 'send', send_with_callback)
        before = _protected_rows(f)
        run = dict(entry=entry, continuation=selector, work_id=auth.work_id, action_id=auth.action_id,
            expected_revision=1, inputs=f['v2']['inputs'], case=case,
            invoke_parameters=f['v2'], execute_case=lambda **kw: entry.execute_case(
                runtime=runtime, caller=caller, scope=scope, **kw), save=case_module.save,
            output=tmp_path, request_id='combined-consumer-' + review,
            receipt_path=tmp_path / 'combined-receipt.json')
        answer, parameters = case_module.run_continuation(**run)
        assert 'attempt' not in parameters['continuation_of']
        assert answer['read_back']['data']['state'] == 'completed'
        disposition = answer['result']['result']['method_result']['disposition']
        assert disposition == ('accepted' if review == 'pass' else 'rejected')
        assert _protected_rows(f) == before
        assert f['counters'] == {'reader': 1, 'bootstrap': 1}
        assert len(callbacks) == 1 and callbacks[0]['unitId'].startswith('controlled-successor-')
        assert len(f['review_source'].calls) == 1
        with f['factory'].begin(GRAPH_SCOPE, 'read') as uow:
            assert uow.work_dispatch.get(f['dispatch_key'], f['origin'].step_id, 1,
                                         GRAPH_SCOPE) == f['origin_row']
        replay = entry.invoke_formal_work_action(runtime, caller=caller, scope=scope,
            parameters=parameters, request_id=run['request_id'])
        assert replay == answer['result']
        assert f['counters'] == {'reader': 1, 'bootstrap': 1}
        assert _protected_rows(f) == before
