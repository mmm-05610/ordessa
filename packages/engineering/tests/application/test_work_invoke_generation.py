"""Formal entry: `engineering.work.invoke` -> prepare-packages -> the new port.

The chain, library, codec, stores and UoW are the real ones (the library is
brought to schema 17, where the declared-Work dispatch relation lives). The Unit
transport is a labelled double; its captured output is a *real* prepared-package
projection, and the blob that carries it is written to the real blob store.
"""
import asyncio
import hashlib
import pathlib
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from work_step_access_fixture import enable_controlled_work_steps


@pytest.fixture(autouse=True)
def controlled_work_step_admission(monkeypatch):
    enable_controlled_work_steps(monkeypatch)

from test_itemized_source_chain import build_itemized_chain
from test_declarative_work import start_params
from test_review_usecases import _create_source
from test_real_source_chain import (NOW, AUTHOR, SCOPE, Proposal, SourceChange,
                                   associate_and_freeze, close_chain, context,
                                   create_proposal,
                                   decode_json, decode_review_ref, encode_proposal,
                                   request_and_run_review, run_full_chain)
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.migrations import migrate_schema16
from contextlib import contextmanager
from dataclasses import replace as _replace

from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.domain.approvals.consent import (
    AuthorizationIntent, ConsentPolicyRef, ConversationEvidence, ConversationNotice,
    ConversationSource)
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.reviews.refs import ReviewRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.application.usecases.packages.authorization import (
    resolve_implementation_intent)
from ordessa_engineering.application.usecases.packages.implementation import (
    ImplementationUseCases)
from ordessa_engineering.application.usecases.proposal_closure import resolve_record
from ordessa_engineering.domain.approvals.implementation import (
    ActionBudgetSlot, ImplementationAuthorizationIntent)
from ordessa_engineering.domain.approvals.scope import (
    ActionScope, EffectLimit, EnvironmentRef, PathRule, RepositoryScope)
from ordessa_engineering.domain.changes.intent import ImplementationIntentSpec
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.repository_baseline import (
    RepositoryFile, seal_repository_baseline)

WORK_ID = 'declarative-work-1'
GENERATION_INTENT_ID = 'intent-generation-1'
ROOT = pathlib.Path(__file__).resolve().parents[4]


class _Transport:
    """Labelled Unit-transport double: counts sends, never opens a network."""

    def __init__(self, blob_ref, *, blobs=None):
        self.sends = 0
        self.blob_ref = blob_ref
        self.blobs = blobs

    def freeze_input(self, unit_ref, params):
        raw = canonical_bytes({'frozen': {'unit_ref': unit_ref, 'params': params}})
        return raw, Digest('sha256', hashlib.sha256(raw).hexdigest())

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return 'q' * 64

    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        from contextlib import contextmanager

        @contextmanager
        def _handoff():
            yield
        return _handoff()

    def send(self, binding, *, timeout=60):
        self.sends += 1

    def capture(self, binding):
        if self.blob_ref is None or self.blobs is None:
            return SimpleNamespace(blob_ref=self.blob_ref, state='completed')
        output = self.blobs.read_verified(self.blob_ref).decode('utf-8')
        receipt = {'contractVersion': 'unit-acp-turn/1',
                   'unitRef': decode_json(binding.unit_ref_bytes),
                   'operationRef': binding.execution_operation_ref,
                   'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
                   'state': 'completed', 'revision': 3, 'events': [],
                   'summary': {'text': output, 'successfulRpcResponse': True,
                               'modelQualityVerified': False, 'eventCount': 0}}
        raw = canonical_bytes(receipt)
        blob = self.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                      'application/json')
        return SimpleNamespace(blob_ref=blob, state='completed')


def _create_spec_proposal(env, spec):
    """The chain's draft, carrying the implementation spec in its v2 field."""
    proposal = Proposal(SCOPE, 'caller-draft', NOW, AUTHOR, 'unspecified-change',
        'Record the explicitly edited local DID', 'Same document v1 and v2; no document custody',
        (), (), (), (), env.method, (), spec, (), 2,
        SourceChange(env.baseline, env.candidate, env.resources))
    value = decode_json(encode_proposal(proposal))
    draft = {key: value[key] for key in ('intent','rationale','mutations','basis_sources',
        'claim_refs','evidence_links','method_ref','review_requirement_templates',
        'implementation_intent','supersedes_refs','source_change')}
    result = asyncio.run(env.service.execute('engineering.proposals.create',
        {'change_id': None, 'expected_version': 0, 'draft': draft}, context('create-spec-change')))
    from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
    return decode_proposal_ref(result.result['proposal_ref'])


def _prepared_output(_env=None, _review_ref=None, _change_ref=None,
                     package_id='generated-package-1'):
    """Versioned document-only envelope; host owns all package provenance."""
    contents = {'spec': '# Spec\nA bounded generated specification.\n',
                'plan': '# Plan\nApply the approved source change.\n',
                'tasks': '# Tasks\n- [ ] Verify the change.\n'}
    return canonical_bytes({
        'contract_version': 'ordessa.generated-package-documents/v1',
        'package_id': package_id,
        'document_contents': contents,
    })


def _command_status(result):
    """The command result carries its status either as an attribute or a key."""
    value = getattr(result, 'status', None)
    if value is not None:
        return value
    if isinstance(result, dict):
        return result.get('status', result.get('state'))
    return None


def _command_payload(result):
    value = getattr(result, 'result', None)
    if value is not None:
        return value
    if isinstance(result, dict):
        # A reserved/replayed command returns its own decoded payload.
        return result.get('result', result)
    return None


def _invoke_generation(env, chain, transport, service=None):
    """start the Work on the reviewed change, then invoke the declared action."""
    service = service or env.service
    started = asyncio.run(service.execute(
        'engineering.work.start',
        start_params(env, work_id=WORK_ID,
                     associations=(('proposal', chain.successor),)),
        context('invoke-generation-work')))
    assert _command_status(started) == 'completed', _command_payload(started)
    return asyncio.run(service.execute('engineering.work.invoke', {
        'work_id': WORK_ID, 'action_id': 'incremental.prepare-packages',
        'inputs': {'baseline': asdict(env.baseline), 'candidate': asdict(env.candidate),
                   'scope': {'realm_id': SCOPE.realm_id, 'project_id': SCOPE.project_id},
                   'review': asdict(chain.review_ref), 'method': asdict(env.method),
                   'profile': {'test_double': 'fixed-profile-revision'}}},
        context('invoke-generation')))


def _generation_env(tmp_path, captured):
    """The real chain, migrated to 17, with the declared generation handles."""
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
    chain = run_full_chain(env)
    blob = env.blobs.put_verified(captured,
                                  Digest('sha256', hashlib.sha256(captured).hexdigest()),
                                  'application/json')
    transport = _Transport(blob, blobs=env.blobs)
    env.service.attach_declared_generation_handles(
        blobs=env.blobs, execution=transport,
        unit_ref_resolver=lambda context, binding, profile_ref: {
            'environmentNamespace': 'env', 'unitId': 'unit-1',
            'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
    return env, chain, transport


def test_work_invoke_reaches_the_generation_port(tmp_path):
    """The declared action reaches its step and produces this run's package."""
    captured = None
    env = build_itemized_chain(tmp_path)
    try:
        migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
        chain = run_full_chain(env)
        captured = _prepared_output()
        blob = env.blobs.put_verified(
            captured, Digest('sha256', hashlib.sha256(captured).hexdigest()),
            'application/json')
        transport = _Transport(blob, blobs=env.blobs)
        env.service.attach_declared_generation_handles(
            blobs=env.blobs, execution=transport,
            unit_ref_resolver=lambda context, binding, profile_ref: {
                'environmentNamespace': 'env', 'unitId': 'unit-1',
                'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
        result = _invoke_generation(env, chain, transport)
        payload = _command_payload(result)
        assert _command_status(result) == 'completed', payload
        steps = (payload or {}).get('steps') or []
        generation = [step for step in steps
                      if step.get('business', {}).get('package_ref')]
        assert generation, payload
        produced = generation[0]['business']
        # this run's own package, never the fixture's caller-prepared one
        assert produced['package_ref']['package_id'] == 'generated-package-1'
        assert produced['run_association']['dispatch_key'].startswith('w1:')
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_a_run_without_output_produces_no_package(tmp_path):
    """No captured output: the step refuses, nothing is stood in for it."""
    env = build_itemized_chain(tmp_path)
    try:
        migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
        chain = run_full_chain(env)
        transport = _Transport(None, blobs=env.blobs)
        transport.capture = lambda binding: SimpleNamespace(blob_ref=None)
        env.service.attach_declared_generation_handles(
            blobs=env.blobs, execution=transport,
            unit_ref_resolver=lambda context, binding, profile_ref: {
                'environmentNamespace': 'env', 'unitId': 'unit-1',
                'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
        with pytest.raises(ApplicationError) as exc:
            _invoke_generation(env, chain, transport)
        assert exc.value.code == 'WORK_ACTION_GENERATION_RESULT_UNCONFIRMED'
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_arbitrary_text_cannot_become_a_package_ref(tmp_path):
    """Captured bytes that are not this codec's payload are refused."""
    env = build_itemized_chain(tmp_path)
    try:
        migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
        chain = run_full_chain(env)
        captured = b'not a package payload'
        blob = env.blobs.put_verified(
            captured, Digest('sha256', hashlib.sha256(captured).hexdigest()),
            'application/json')
        transport = _Transport(blob, blobs=env.blobs)
        env.service.attach_declared_generation_handles(
            blobs=env.blobs, execution=transport,
            unit_ref_resolver=lambda context, binding, profile_ref: {
                'environmentNamespace': 'env', 'unitId': 'unit-1',
                'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
        with pytest.raises(ApplicationError) as exc:
            _invoke_generation(env, chain, transport)
        assert exc.value.code == 'WORK_ACTION_GENERATION_OUTPUT_INVALID'
        assert transport.sends == 1
        # Nothing was registered: read the real store, not the return value.
        import sqlite3
        conn = sqlite3.connect(env.library.path)
        try:
            registered = conn.execute(
                'SELECT COUNT(*) FROM eng_packages WHERE package_id=?',
                ('generated-package-1',)).fetchone()[0]
        finally:
            conn.close()
        assert registered == 0
    finally:
        close_chain(env)


# --- the adapter's own dispatch behaviour, on the chain's real store --------
ACTION = 'incremental.prepare-packages'
STEP = 'draft'


def _unit_ref():
    return {'environmentNamespace': 'env', 'unitId': 'unit-1',
            'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'}


class _FailingTransport(_Transport):
    """A send that raises: the effect stays unknown, never recorded as done."""

    def send(self, binding, *, timeout=60):
        self.sends += 1
        raise RuntimeError('unit transport unavailable')


def _chain_adapter(env, transport, *, factory=None, access=None, blobs=None,
                   review_admission=None, method_guard=None):
    from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
        DeclaredGenerationDispatch)
    return DeclaredGenerationDispatch(factory or env.factory, access or env.service._access,
                                      blobs=blobs or env.blobs, execution=transport,
                                      review_admission=review_admission or env.service._review_admission,
                                      method_guard=method_guard or env.service._method_guard)


def _chain_ready(tmp_path):
    """The real chain, migrated to schema 17, plus this run's captured output."""
    env = build_itemized_chain(tmp_path)
    migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
    chain = run_full_chain(env)
    # The declared Work itself: the dispatch relation refuses an unknown Work.
    started = asyncio.run(env.service.execute(
        'engineering.work.start',
        start_params(env, work_id=WORK_ID,
                     associations=(('proposal', chain.successor),)),
        context('adapter-work-start')))
    assert started.status == 'completed', started.result
    captured = _prepared_output()
    blob = env.blobs.put_verified(captured,
                                  Digest('sha256', hashlib.sha256(captured).hexdigest()),
                                  'application/json')
    return env, chain, blob


def _generation_kwargs(chain, env, **overrides):
    kwargs = dict(change_ref=chain.successor, review_ref=chain.review_ref,
                  method_ref=env.method)
    kwargs.update(overrides)
    return kwargs


def test_the_adapter_dispatches_on_the_real_change_and_a_reopen_sends_once(tmp_path):
    """Success, then re-entry after reopening the library: one send, not two."""
    env, chain, blob = _chain_ready(tmp_path)
    path = env.library.path
    try:
        transport = _Transport(blob, blobs=env.blobs)
        first = _chain_adapter(env, transport).dispatch_generation(
            WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1}, context('adapter-dispatch-1'),
            **_generation_kwargs(chain, env))
        assert first['phase'] == 'completed' and transport.sends == 1
        env.library.close()
        from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
        from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
            EngineeringLibrary)
        from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
        from test_real_source_chain import ControlledLocalAccess
        reopened = EngineeringLibrary.open(path, library_id='local-source-chain')
        from test_real_source_chain import (
            DeclaredSourceReviewBindings, DecisionReviewerSource, EngineeringReviewAdmission,
            SQLiteMethodControl, SQLiteSnapshotStore, ProjectSourceMaterials,
            PRINCIPAL, REVIEWER)
        factory = SQLiteUoWFactory(reopened)
        blobs = SQLiteBlobStore(reopened)
        controls = SQLiteMethodControl(factory, SQLiteSnapshotStore(reopened))
        materials = ProjectSourceMaterials(factory, scope=SCOPE, root=env.project,
                                           source_mappings=tuple(env.mappings))
        bindings = DeclaredSourceReviewBindings(factory, controls, scope=SCOPE,
            method_ref=env.method, baseline=env.baseline, candidate=env.candidate,
            action_id='incremental.review-change', binding_resource_id='source-review-binding',
            criteria_resource_id='change-review-criteria', prompt_resource_id='change-review-prompt',
            result_schema_resource_id='review-result-schema', reviewer_roles=('reviewer',),
            caller_materials_ref=env.mappings[-1][0],
            caller_input_schema_resource_id='caller-review-input-schema')
        reviewer = DecisionReviewerSource(factory, blobs, controls, materials, bindings,
            scope=SCOPE, principal_id=PRINCIPAL, reviewer=REVIEWER, roles=('reviewer',),
            services=env.services)
        admission = EngineeringReviewAdmission(factory, controls, None, reviewer,
            source_materials=materials, method_guard=controls, source_review_bindings=bindings)
        try:
            again = _chain_adapter(env, transport, factory=factory,
                                   access=ControlledLocalAccess(),
                                   blobs=blobs, review_admission=admission,
                                   method_guard=controls).dispatch_generation(
                WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1}, context('adapter-dispatch-1'),
                **_generation_kwargs(chain, env))
            assert again['already_dispatched'] is True and transport.sends == 1
            assert again['phase'] == 'completed'
        finally:
            reviewer.close()
            materials.close()
            reopened.close()
    finally:
        close_chain(env)


def test_retry_after_an_unknown_send_does_not_send_again(tmp_path):
    env, chain, blob = _chain_ready(tmp_path)
    try:
        transport = _FailingTransport(blob, blobs=env.blobs)
        adapter = _chain_adapter(env, transport)
        with pytest.raises(RuntimeError):
            adapter.dispatch_generation(WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1},
                                        context('adapter-unknown-1'),
                                        **_generation_kwargs(chain, env))
        assert transport.sends == 1
        replayed = adapter.dispatch_generation(WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1},
                                               context('adapter-unknown-1'),
                                               **_generation_kwargs(chain, env))
        assert replayed['already_dispatched'] is True and replayed['phase'] == 'unknown'
        assert transport.sends == 1
        view = asyncio.run(env.service.query('engineering.work.get',
            {'work_id': WORK_ID}, context('read-unknown-generation')))
        assert view['generation_dispatch']['phase'] == 'unknown'
        assert view['generation_dispatch']['unknown_requires_reconciliation'] is True
        assert view['generation_dispatch']['retry_allowed'] is False
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_an_inapplicable_subject_or_input_is_refused_without_sending(tmp_path):
    """Wrong method, change or review, and a mismatched input: zero sends."""
    env, chain, blob = _chain_ready(tmp_path)
    try:
        transport = _Transport(blob, blobs=env.blobs)
        adapter = _chain_adapter(env, transport)
        other_method = MethodRef('incremental-engineering', '2.7.2', 1, Digest('sha256', 'f' * 64))
        other_change = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-other',
                                   'proposal-other', Digest('sha256', 'e' * 64))
        other_review = ReviewRef(SCOPE.realm_id, SCOPE.project_id, 'review-other',
                                 Digest('sha256', 'd' * 64))
        for overrides, code in (
                # The Work's own immutable pins refuse changed subjects before
                # any arbitrary proposal/review lookup or Unit side effect.
                ({'method_ref': other_method}, 'WORK_ACTION_GENERATION_CHANGE_MISMATCH'),
                ({'change_ref': other_change}, 'WORK_ACTION_GENERATION_CHANGE_MISMATCH'),
                ({'review_ref': other_review}, 'WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED'),
                ({'input_snapshot': Digest('sha256', '0' * 64)},
                 'WORK_ACTION_GENERATION_INPUT_MISMATCH')):
            with pytest.raises(ApplicationError) as exc:
                adapter.dispatch_generation(WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1},
                                            context('adapter-refusal-1'),
                                            **_generation_kwargs(chain, env, **overrides))
            assert exc.value.code == code
        assert transport.sends == 0
    finally:
        close_chain(env)


def test_a_reentry_with_other_inputs_is_not_reused(tmp_path):
    env, chain, blob = _chain_ready(tmp_path)
    try:
        transport = _Transport(blob, blobs=env.blobs)
        adapter = _chain_adapter(env, transport)
        adapter.dispatch_generation(WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1},
                                    context('adapter-inputs-1'),
                                    **_generation_kwargs(chain, env))
        assert transport.sends == 1
        with pytest.raises(ApplicationError) as exc:
            adapter.dispatch_generation(WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 2},
                                        context('adapter-inputs-1'),
                                        **_generation_kwargs(chain, env))
        assert exc.value.code == 'DISPATCH_ATTEMPT_INPUT_MISMATCH'
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_a_package_about_another_change_is_refused(tmp_path):
    """The Unit cannot override the Work's host-pinned change subject."""
    env = build_itemized_chain(tmp_path)
    try:
        migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
        chain = run_full_chain(env)
        other = ProposalRef(SCOPE.realm_id, SCOPE.project_id, 'change-other',
                            'proposal-other', Digest('sha256', 'e' * 64))
        captured = decode_json(_prepared_output().decode('utf-8'))
        # The former model-authored payload could claim another change. The
        # versioned document-only contract refuses that obsolete subject field.
        captured['payload'] = {'change_ref': asdict(other)}
        captured = canonical_bytes(captured)
        blob = env.blobs.put_verified(
            captured, Digest('sha256', hashlib.sha256(captured).hexdigest()),
            'application/json')
        transport = _Transport(blob, blobs=env.blobs)
        env.service.attach_declared_generation_handles(
            blobs=env.blobs, execution=transport,
            unit_ref_resolver=lambda context, binding, profile_ref: {
                'environmentNamespace': 'env', 'unitId': 'unit-1',
                'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
        with pytest.raises(ApplicationError) as exc:
            _invoke_generation(env, chain, transport)
        assert exc.value.code == 'WORK_ACTION_GENERATION_OUTPUT_INVALID'
        assert transport.sends == 1
    finally:
        close_chain(env)


def test_a_review_that_did_not_pass_refuses_before_any_send(tmp_path):
    """A failed review fails the declared admission: nothing is dispatched."""
    from test_itemized_source_chain import ItemizedControlledProvider
    env = build_itemized_chain(tmp_path,
                               provider=ItemizedControlledProvider(
                                   {'evidence-support': 'not_passed'}))
    try:
        migrate_schema16(env.library, backup_path=(tmp_path / 'schema16.backup.sqlite').resolve())
        proposal_ref = create_proposal(env)
        _, recorded, _receipt = request_and_run_review(env)
        assert recorded.result['verdict'] != 'pass'
        review_ref = decode_review_ref(recorded.result['review_ref'])
        transport = _Transport(None, blobs=env.blobs)
        env.service.attach_declared_generation_handles(
            blobs=env.blobs, execution=transport,
            unit_ref_resolver=lambda context, binding, profile_ref: {
                'environmentNamespace': 'env', 'unitId': 'unit-1',
                'ownerProviderRef': {'provider': 'local'}, 'sourceRevision': 'rev-1'})
        started = asyncio.run(env.service.execute(
            'engineering.work.start',
            start_params(env, work_id=WORK_ID, associations=(('proposal', proposal_ref),)),
            context('invoke-failed-review-work')))
        assert _command_status(started) == 'completed', _command_payload(started)
        with pytest.raises(ApplicationError) as exc:
            asyncio.run(env.service.execute('engineering.work.invoke', {
                'work_id': WORK_ID, 'action_id': 'incremental.prepare-packages',
                'inputs': {'baseline': asdict(env.baseline),
                           'candidate': asdict(env.candidate),
                           'scope': {'realm_id': SCOPE.realm_id,
                                     'project_id': SCOPE.project_id},
                           'review': asdict(review_ref), 'method': asdict(env.method),
                           'profile': {'test_double': 'fixed-profile-revision'}}},
                context('invoke-failed-review')))
        assert 'REVIEW_PASSED' in exc.value.code or 'ADMISSION' in exc.value.code, exc.value.code
        assert transport.sends == 0
    finally:
        close_chain(env)


def test_without_the_dispatch_permission_nothing_is_sent(tmp_path):
    """No host execution permission: the step refuses before any send.

    The permission is enforced by the transport adapter's own `access.require`,
    so the denial is exercised there: swapping the Service's access instead would
    break the composition's authority-identity checks (a real constraint).
    """
    env, chain, blob = _chain_ready(tmp_path)
    try:
        transport = _Transport(blob, blobs=env.blobs)

        class _DeniedAccess:
            """A labelled access double that grants nothing at all."""

            scope = SCOPE
            authority_id = 'denied-access'

            def require(self, context, operation):
                raise ApplicationError('CAPABILITY_NOT_BOUND')

            def check_active(self):
                return None

        with pytest.raises(ApplicationError) as exc:
            _chain_adapter(env, transport, access=_DeniedAccess()).dispatch_generation(
                WORK_ID, ACTION, STEP, 1, _unit_ref(), {'p': 1}, context('denied-dispatch'),
                **_generation_kwargs(chain, env))
        assert exc.value.code == 'CAPABILITY_NOT_BOUND', exc.value.code
        assert transport.sends == 0
    finally:
        close_chain(env)


def test_pending_invoke_is_queryable_and_never_restarts_generation(tmp_path):
    """Interruption after parent reservation is an observation, never a retry."""
    env = build_itemized_chain(tmp_path)
    try:
        parameters = {'work_id': WORK_ID, 'action_id': ACTION, 'inputs': {}}
        admitted = context('pending-generation-parent')
        _, digest, replay = env.service._works.invoke_replay(parameters, admitted)
        assert replay is None
        operation_id, _ = env.service._works.begin_invoke(admitted, digest)
        replayed = asyncio.run(env.service.execute('engineering.work.invoke', parameters, admitted))
        assert replayed.operation_id == operation_id
        assert replayed.status == 'pending' and replayed.result_bytes is None
        view = asyncio.run(env.service.query('engineering.operations.get',
            {'request_id': admitted.request_id}, context('pending-generation-query')))
        assert view['operation_id'] == operation_id
        assert view['state'] == 'unknown' and view['retry_allowed'] is False
    finally:
        close_chain(env)
