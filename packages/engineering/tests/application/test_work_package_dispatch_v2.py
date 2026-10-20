"""Real schema17 SQLite and released 2.7.2, controlled transport/selection.

No Unit, model, server or real history store is started. Native transport and
permission handoff are explicit test doubles; the original Engineering effect
cut, approval, Work, blob, debit and dispatch repositories are exercised.
"""
import asyncio
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from test_work_package_approval_flow_v2 import build_work_package_approval, _evidence
from test_real_source_chain import NOW, SCOPE, context


ENVIRONMENT = EnvironmentRef('test-native-environment', 'test-native-profile', Digest('sha256', 'c' * 64))
UNIT = {'environmentNamespace': ENVIRONMENT.environment_id, 'unitId': 'test-native-unit',
        'ownerProviderRef': {'provider': 'controlled-test-only'}, 'sourceRevision': '1'}


class ControlledSelection:
    work_scope_ready = True
    def __init__(self, *, deny=False):
        self.calls = 0
        self.deny = deny

    def describe_work_profile(self, context, package, authorization):
        return {'environmentNamespace': ENVIRONMENT.environment_id,
            'profileId': ENVIRONMENT.profile_id, 'manifestRevision': 1,
            'contentDigest': 'sha256:' + ENVIRONMENT.profile_digest.hex}

    @contextmanager
    def guard_work_selection(self, ctx, package, unit_ref, authorization, params):
        self.calls += 1
        if self.deny or unit_ref != UNIT or params.get('sessionId') != 'controlled-test-session':
            raise ApplicationError('DISPATCH_SELECTION_BINDING_INVALID')
        yield ENVIRONMENT

    @contextmanager
    def guard_work_scope(self, ctx, package, unit_ref, authorization, actions):
        # Controlled external effect owner: exact fixture repository and path
        # bounds, not a production Workspace permission producer.
        for action in actions:
            scope = dict(authorization.scope_by_action)[action]
            if any(repo.repository_id != 'test-repository' for repo in scope.repository_scopes):
                raise ApplicationError('ACTION_SCOPE_NOT_AUTHORIZED')
        yield


class ControlledTransport:
    def __init__(self, blobs):
        self.blobs = blobs
        self.records = object()
        self.query_factory = lambda binding: None
        self.sends = 0
        self.freezes = 0
        self.fail_send = False
        self.before_write = None
        self.binding = None
        self.dispatch = None
        self.ctx = None
        self.handoff = object()

    def freeze_input(self, unit, params):
        self.freezes += 1
        raw = canonical_bytes({**params, 'sessionId': 'controlled-test-session'})
        return raw, Digest('sha256', hashlib.sha256(raw).hexdigest())

    def query_digest(self, unit, operation, digest):
        return 'sha256:' + hashlib.sha256(canonical_bytes([unit, operation, asdict(digest)])).hexdigest()

    @contextmanager
    def guard_effect_handoff(self, ctx, binding, *, access, timeout):
        self.ctx = ctx
        yield

    def send(self, binding, *, timeout):
        self.binding = binding
        if self.before_write:
            self.before_write(binding)
        async def write():
            identity = {'unitRef': UNIT, 'operationRef': binding.execution_operation_ref,
                'inputDigest': 'sha256:' + binding.prompt_input_digest.hex,
                'requestId': 'controlled-native-frame', 'frameDigest': 'sha256:' + 'e' * 64}
            loop = asyncio.get_running_loop()
            async with self.dispatch.acquire_effect_write(self.ctx, binding, identity,
                    loop.time() + 2, handoff=self.handoff):
                self.sends += 1
                if self.fail_send:
                    raise OSError('controlled uncertain native response')
        with ThreadPoolExecutor(max_workers=1) as sdk_thread:
            sdk_thread.submit(lambda: asyncio.run(write())).result()

    def capture(self, binding):
        raw = canonical_bytes({'controlled_native': 'completed',
                               'operation': binding.execution_operation_ref})
        blob = self.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json')
        return SimpleNamespace(operation_ref=binding.execution_operation_ref,
            expected_prompt_digest='sha256:' + binding.prompt_input_digest.hex,
            query_digest=binding.expected_query_digest, state='completed', blob_ref=blob)


@contextmanager
def dispatch_fixture(tmp_path, monkeypatch, *, issue_grant=True, environment=True):
    with build_work_package_approval(tmp_path, issue_grant=issue_grant,
            environment_ref=ENVIRONMENT if environment else None) as fixture:
        service, env = fixture['service'], fixture['env']
        transport = ControlledTransport(env.blobs)
        selection = ControlledSelection()
        access = service._access

        @contextmanager
        def consume(handoff, ctx, *, invocation_key, action_instances):
            assert handoff is transport.handoff
            access.require(ctx, 'engineering.executions.dispatch')
            assert invocation_key and action_instances
            yield

        monkeypatch.setattr(access, 'consume_effect_write', consume, raising=False)
        monkeypatch.setattr('ordessa_engineering.application.usecases.support.clock.utc_now', lambda: NOW)
        dispatch = ImplementationDispatch(fixture['factory'], access,
            approval_usecases=service._packages.approvals, execution=transport,
            selection=selection, blobs=env.blobs, method_guard=env.controls,
            source_materials=env.materials)
        transport.dispatch = dispatch
        owner = EngineeringOwnerOperations(fixture['factory'], packages=service._packages,
            dispatch=dispatch, submissions=service._submission_reports,
            records=transport.records, blobs=env.blobs, access=access,
            unit_ref_resolver=lambda *_: UNIT)
        service._execution_dispatch = owner
        fixture.update(dispatch=dispatch, transport=transport, selection=selection)
        yield fixture


def request(fixture, *, attempt=1, params=None):
    auth = fixture['authorization']
    return {'dispatch': {'work_id': auth.work_id, 'action_id': auth.action_id,
        'step_id': auth.step_id, 'attempt': attempt, 'unit_ref': UNIT,
        'params': params or {}, 'actions': list(auth.actions), 'timeout': 10}}


def call(fixture, value=None):
    # Exercise the Service's private enclosing-Work assembly seam. The complete
    # Work.invoke action is still unsupported until report/review are bound.
    auth = fixture['authorization']
    with fixture['factory'].begin(SCOPE, 'read') as uow:
        ref = uow.workflow.head_ref(WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX + auth.work_id)
        work = decode_work_binding(uow.workflow.read(ref))
    return asyncio.run(fixture['service']._execute_declared_dispatch(
        value or request(fixture), context('work-native-implementation'),
        work=work, action_id=auth.action_id, step_id=auth.step_id))


def row(fixture):
    auth = fixture['authorization']
    key = work_dispatch_key(auth.work_id, auth.action_id, auth.step_id)
    with fixture['factory'].begin(SCOPE, 'read') as uow:
        return uow.work_dispatch.get(key, auth.step_id, 1, SCOPE)


def test_scoped_service_step_dispatches_frozen_work_package_once_and_replays_after_revoke(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        auth = f['authorization']
        owner = f['service']._execution_dispatch
        with f['factory'].begin(SCOPE, 'read') as uow:
            work = decode_work_binding(uow.workflow.read(f['head']))
        inputs = {'package': asdict(f['package_ref']), 'profile': {'test_only': 'selected-original-profile'}}
        envelope = owner.assemble_declared_work_dispatch(work, auth.action_id, auth.step_id,
                                                        inputs, context('assemble-work-step'))
        assert envelope['dispatch']['work_id'] == work.work_id
        assert envelope['dispatch']['actions'] == list(auth.actions)
        assert envelope['dispatch']['attempt'] == 1
        result = call(f, envelope)
        assert result.outcome == 'completed' and result.accepted is False
        assert result.value['params_assembly'] == 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT'
        business = f['service']._work_dispatch_business(result)
        assert decode_json(canonical_bytes(business))['binding']['binding_version'] == 2
        assert business['accepted'] is business['engineering_completed'] is False
        original = row(f)
        binding = decode_dispatch(original['binding_bytes'])
        assert binding.binding_version == 2 and binding.package_ref == f['package_ref']
        assert binding.work['work_id'] == f['authorization'].work_id
        with f['factory'].begin(SCOPE) as uow:
            assert uow.authorization.action_budget(binding.approval_ref)['actions'] == [
                {'action': 'edit_repository', 'limit': 1, 'consumed': 1},
                {'action': 'run_checks', 'limit': 1, 'consumed': 1}]
            uow.authorization.revoke(binding.approval_ref, 0, NOW, 'controlled revoke', 'test-revoke')
            uow.commit()
        freezes, selected = f['transport'].freezes, f['selection'].calls
        def no_reselection(*args):
            raise AssertionError('An existing attempt must not select another Unit or Grant')
        owner.unit_ref_resolver = no_reselection
        replay_envelope = owner.assemble_declared_work_dispatch(work, auth.action_id, auth.step_id,
                                                               inputs, context('replay-work-step'))
        replay = call(f, replay_envelope)
        assert replay.outcome == 'completed'
        assert f['transport'].sends == 1 and f['transport'].freezes == freezes
        assert f['selection'].calls == selected
        assert row(f)['binding_bytes'] == original['binding_bytes']
        assert f['env'].library._connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0


def test_public_dispatch_cannot_bypass_the_enclosing_work_invocation(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        with pytest.raises(ApplicationError, match='WORK_ACTION_DISPATCH_CONTEXT_REQUIRED'):
            asyncio.run(f['service'].execute('engineering.executions.dispatch',
                request(f), context('standalone-dispatch-denied')))
        assert f['transport'].freezes == f['transport'].sends == 0
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            row(f)


def test_dispatch_envelope_cannot_substitute_the_enclosing_work(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch, issue_grant=False) as f:
        substituted = request(f)
        substituted['dispatch']['work_id'] = 'caller-substituted-work'
        with pytest.raises(ApplicationError, match='WORK_ACTION_DISPATCH_BINDING_MISMATCH'):
            call(f, substituted)
        assert f['transport'].freezes == f['transport'].sends == 0


def test_unknown_transport_is_never_resent(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        f['transport'].fail_send = True
        assert call(f).outcome == 'unknown'
        original = row(f)
        assert original['dispatch_phase'] == 'unknown'
        assert call(f).outcome == 'unknown'
        assert f['transport'].sends == 1 and row(f)['binding_bytes'] == original['binding_bytes']


@pytest.mark.parametrize('case', ['no_grant', 'scope', 'selection', 'params', 'missing_scope_authority'])
def test_missing_real_authority_or_substituted_input_writes_no_attempt(tmp_path, monkeypatch, case):
    with dispatch_fixture(tmp_path, monkeypatch, issue_grant=case != 'no_grant',
            environment=case != 'scope') as f:
        f['selection'].deny = case == 'selection'
        if case == 'missing_scope_authority':
            f['selection'].guard_work_scope = None
        value = request(f, params={'prompt': [{'type': 'text', 'text': 'caller substitution'}]}) if case == 'params' else None
        expected = {'no_grant': 'DISPATCH_DECLARED_WORK_GRANT_UNAVAILABLE',
            'scope': 'ACTION_SCOPE_NOT_AUTHORIZED', 'selection': 'DISPATCH_SELECTION_BINDING_INVALID',
            'params': 'DISPATCH_WORK_INPUT_CHANGED',
            'missing_scope_authority': 'DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE'}[case]
        with pytest.raises(ApplicationError, match=expected):
            call(f, value)
        assert f['transport'].sends == 0
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            row(f)


def test_budget_exhaustion_rolls_back_the_new_attempt(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        assert call(f).outcome == 'completed'
        with pytest.raises(ApplicationError, match='ACTION_BUDGET_EXHAUSTED'):
            call(f, request(f, attempt=2))
        auth = f['authorization']
        with f['factory'].begin(SCOPE, 'read') as uow:
            key = work_dispatch_key(auth.work_id, auth.action_id, auth.step_id)
            with pytest.raises(ApplicationError, match='NOT_FOUND'):
                uow.work_dispatch.get(key, auth.step_id, 2, SCOPE)
            bound = decode_dispatch(uow.work_dispatch.get(key, auth.step_id, 1, SCOPE)['binding_bytes'])
            assert all(a['consumed'] == 1 for a in uow.authorization.action_budget(bound.approval_ref)['actions'])
        assert f['transport'].sends == 1


def test_two_actual_grants_for_the_same_subject_are_ambiguous(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        auth = f['authorization']
        second_auth = replace(auth, intent_id='second-exact-subject-intent',
            scope_by_action=tuple((a, replace(scope, implementation_intent_id='second-exact-subject-intent'))
                                  for a, scope in auth.scope_by_action))
        second_source = replace(f['source'], locator='controlled-test/second-transcript')
        notice = replace(f['notice'], notice_id='second-exact-subject-notice',
                         authorization=second_auth, source=second_source)
        intent = type(f['intent'])(second_auth, notice.ref, f['policy'])
        second = {**f, 'authorization': second_auth, 'notice': notice, 'intent': intent,
                  'source': second_source}
        def approve(operation, payload, request_id):
            return asyncio.run(f['service'].execute(operation, payload, context(request_id)))
        approve('engineering.notices.publish', {'notice': asdict(notice)}, 'second-notice')
        approve('engineering.approvals.prepare_intent', {'intent': asdict(intent)}, 'second-intent')
        challenge = approve('engineering.approvals.request',
            {'intent_id': intent.intent_id, 'intent_digest': asdict(intent.digest)}, 'second-challenge')
        result = approve('engineering.approvals.record_conversation', {
            'challenge_id': challenge.result['challenge']['challenge_id'], 'nonce': challenge.result['nonce'],
            'expected_version': 0, 'evidence': asdict(_evidence(second, evidence_id='second-confirmation'))},
            'second-answer')
        assert result.result['state'] == 'granted'
        with pytest.raises(ApplicationError, match='DISPATCH_DECLARED_WORK_GRANT_AMBIGUOUS'):
            call(f)
        assert f['transport'].sends == f['transport'].freezes == 0
        with pytest.raises(ApplicationError, match='NOT_FOUND'):
            row(f)


def test_implementation_reads_registered_document_bytes_without_live_source_fallback(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        with f['factory'].begin(SCOPE, 'read') as uow:
            package = uow.implementation.resolve_package(f['package_ref'])
        original_read = f['env'].materials.read
        document_sources = {d.source_ref for d in package.payload.documents}
        def deny_document_file_read(ctx, source):
            if source in document_sources:
                raise AssertionError('implementation must use registered immutable document bytes')
            return original_read(ctx, source)
        monkeypatch.setattr(f['env'].materials, 'read', deny_document_file_read)
        assert call(f).outcome == 'completed'
        assert f['transport'].sends == 1


def test_revocation_between_reserve_and_native_write_refuses_the_frame(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as f:
        def revoke(binding):
            with f['factory'].begin(SCOPE) as uow:
                uow.authorization.revoke(binding.approval_ref, 0, NOW, 'controlled race', 'race-revoke')
                uow.commit()
        f['transport'].before_write = revoke
        assert call(f).outcome == 'unknown'
        assert f['transport'].sends == 0
        assert row(f)['dispatch_phase'] == 'unknown'
        call(f)
        assert f['transport'].sends == 0
