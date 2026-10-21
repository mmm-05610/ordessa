"""Fixed Profile adapter through the real current Agent lifecycle and local peer.

Real Profile/catalog/Manager/SQLite/endpoint/bootstrap are used. Preparation and
admission are the existing controlled external fixture, not production grants.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'tests/integration/packages_convergence'))
sys.path.insert(0, str(ROOT / 'packages/engineering/tests/application'))
from test_agent_guarded_bootstrap import PEER, setup
from test_method_profile_policy_phase2 import frozen_policy
from test_method_control_admission import context

from ordessa_engineering.adapters.execution_profiles import NativeProfileAgentCreator
from ordessa_engineering.adapters.profile_method import build_method_agent_execution_selection
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_agents.profiles import ProfileAccessRefused, ProfileRevisionRef, encode_content
from ordessa_agents.public import ManagerRefused
from ordessa_agents.sdk.instances import EndpointRef


def _creator_bindings(case, authorization):
    calls = []
    def request_factory(profile_ref, endpoint_ref, actual):
        assert actual is authorization
        calls.append(('request', profile_ref, endpoint_ref, actual))
        return replace(case.request, profile_revision_ref=profile_ref, endpoint_ref=endpoint_ref)
    def invocation_resolver(actual):
        assert actual is authorization
        calls.append(('invocation', actual))
        return case.fixture.invocation
    return request_factory, invocation_resolver, calls


@pytest.mark.parametrize('unknown', [False, True])
def test_method_agent_start_uses_exact_old_revision_and_original_ledger_replay(
        frozen_policy, tmp_path, unknown):
    _, method_ref, methods, _ = frozen_policy
    async def scenario():
        peer = PEER.replace("result={'protocolVersion':1,", "result={'protocolVersion':True,") if unknown else PEER
        case = await setup(tmp_path / 'native', peer)
        try:
            exact = case.request.profile_revision_ref
            original_content = encode_content(case.owner.service.get_revision(exact).content)
            revised = {**original_content, 'metadata': {'revision': 'later'}}
            current = case.owner.service.revise(exact.profile_id, content=revised,
                expected_version=1, base_revision=exact, request=case.owner.service.request_key('later'))
            assert current.current_revision != exact
            authorization = object()  # Opaque host input; no grant is inferred.
            factory, resolver, calls = _creator_bindings(case, authorization)
            selection = build_method_agent_execution_selection(methods, case.owner.service,
                method_ref=method_ref, allowed_revisions=(exact,), agent_manager=case.manager,
                endpoint=case.endpoint, request_factory=factory, invocation_resolver=resolver)
            first = await selection.create_agent(context('profile-agent-start'), exact, authorization)
            assert first.state == ('unknown' if unknown else 'running')
            assert calls[0][1] is exact and calls[0][2] is case.endpoint.ref
            assert calls[0][3] is calls[1][1] is authorization
            # Original read admission permits replay after send rights are lost.
            case.authority.send = False
            replay = await selection.create_agent(context('profile-agent-replay'), exact, authorization)
            assert replay == first
            assert case.manager.get('start', case.fixture.invocation) == first
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='agent-start'").fetchone()[0] == 1
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='bootstrap-frame'").fetchone()[0] == (1 if unknown else 2)
            assert case.fixture.retained_use_count == 1
            if unknown:
                assert first.instance_ref is None and first.session_id is None
            else:
                assert first.instance_ref.namespace == exact.environment_namespace
                assert first.session_id and first.instance_ref
            case.authority.read = False
            with pytest.raises(ManagerRefused, match='READ_NOT_AUTHORIZED'):
                await selection.create_agent(context('profile-agent-read-revoked'), exact, authorization)
        finally:
            case.records.close(); case.owner.close(); await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('mismatch', ['profile', 'endpoint', 'request-type', 'invocation'])
def test_original_manager_refuses_mixed_start_bindings_before_effect(tmp_path, mismatch):
    async def scenario():
        case = await setup(tmp_path)
        try:
            authorization = object()
            factory, resolver, _ = _creator_bindings(case, authorization)
            def invalid_factory(profile_ref, endpoint_ref, actual):
                request = factory(profile_ref, endpoint_ref, actual)
                if mismatch == 'profile':
                    foreign = ProfileRevisionRef(profile_ref.environment_namespace, profile_ref.profile_id,
                                                 profile_ref.revision, 'sha256:' + 'f' * 64)
                    return replace(request, profile_revision_ref=foreign)
                if mismatch == 'endpoint':
                    foreign = EndpointRef(endpoint_ref.issuer, endpoint_ref.endpoint_id, endpoint_ref.revision,
                                          'sha256:' + 'f' * 64)
                    return replace(request, endpoint_ref=foreign)
                if mismatch == 'request-type':
                    return request.projection()
                return request
            creator = NativeProfileAgentCreator(case.manager, endpoint=case.endpoint,
                request_factory=invalid_factory,
                invocation_resolver=(lambda actual: object()) if mismatch == 'invocation' else resolver)
            error = ManagerRefused if mismatch == 'invocation' else EngineeringError
            with pytest.raises(error):
                await creator.create(case.request.profile_revision_ref, authorization)
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='agent-start'").fetchone()[0] == 0
            assert case.fixture._manager._owned_process_handles == {}
        finally:
            case.records.close(); case.owner.close(); await case.fixture.cleanup()
    asyncio.run(scenario())


@pytest.mark.parametrize('refusal', ['method-disabled', 'archived', 'acl', 'not-allowed'])
def test_method_and_profile_preflight_refuse_before_request_or_native_start(
        frozen_policy, tmp_path, refusal):
    _, method_ref, methods, management = frozen_policy
    async def scenario():
        case = await setup(tmp_path / 'native')
        try:
            exact = case.request.profile_revision_ref
            authorization = object()
            factory, resolver, calls = _creator_bindings(case, authorization)
            selection = build_method_agent_execution_selection(methods, case.owner.service,
                method_ref=method_ref, allowed_revisions=(exact,), agent_manager=case.manager,
                endpoint=case.endpoint, request_factory=factory, invocation_resolver=resolver)
            selected = exact
            if refusal == 'method-disabled':
                management.control(method_ref, context('disable-agent-method'), expected_version=0,
                                   enabled=False, reason='Controlled method stop')
            elif refusal == 'archived':
                case.owner.service.archive(exact.profile_id, expected_version=1,
                                           request=case.owner.service.request_key('archive'))
            elif refusal == 'acl':
                case.owner.service._admission.policy.admit_object_access = lambda *_: False
            else:
                selected = ProfileRevisionRef(exact.environment_namespace, 'foreign', exact.revision, exact.digest)
            with pytest.raises((ApplicationError, EngineeringError, ProfileAccessRefused)):
                await selection.create_agent(context('preflight-refusal'), selected, authorization)
            assert calls == []
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='agent-start'").fetchone()[0] == 0
            assert case.fixture._manager._owned_process_handles == {}
        finally:
            case.records.close(); case.owner.close(); await case.fixture.cleanup()
    asyncio.run(scenario())


def test_creator_requires_original_manager_and_explicit_endpoint_bindings():
    with pytest.raises(EngineeringError, match='original_public_agent_manager_required'):
        NativeProfileAgentCreator(object(), endpoint=object(), request_factory=lambda *_: None,
                                  invocation_resolver=lambda *_: None)
