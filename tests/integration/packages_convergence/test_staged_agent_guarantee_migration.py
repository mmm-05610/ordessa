"""Original staged-A safeguards on current Agent + real local resource owners.

C's admitted-consumer/material-read trust is NOT claimed: the prepared file here
is explicitly authorized by the existing controlled external caller, materialized
through its real files capability, and pinned by its exported endpoint. Original
staged/BCA tests remain unchanged. No Unit runtime or fabricated binding is used.
"""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_agent_guarded_bootstrap import setup, PEER
from ordessa_execution_agents.public import ManagerRefused, Records
from ordessa_execution_agents.sdk.prepare import (
    BoundPath, ConfigurationArtifact, PreparedConfigurationRef, MaterialRef,
    SessionBootstrap, canonical_digest,
)
from ordessa_execution_agents.sdk.interactions import InteractionService
from ordessa_environments.definitions.errors import EnvironmentRefused


async def _prepared_case(tmp_path):
    case = await setup(tmp_path)
    body = '{"fixture":"original-prepared-input"}\n'
    digest = 'sha256:' + hashlib.sha256(body.encode()).hexdigest()
    location = BoundPath('work', 'approved.json')
    artifact = ConfigurationArtifact(location, 'application/json', body, digest)
    result = await case.endpoint.files.materialize(artifact, 'original-config-write', case.fixture.invocation)
    assert result['status'] == 'completed'
    ref = PreparedConfigurationRef('controlled-external-config-owner', 'approved-config', '1',
                                   digest, 'application/json', len(body.encode()), location)
    fixture = case.fixture
    exported = fixture._endpoints.export(fixture._use_id, fixture._scope,
        capabilities=case.endpoint.members(), request_id='prepared-export', invocation=fixture.invocation,
        roots={'work':'.','config':'config','home':'home','tmp':'tmp'},
        prepared_configurations=(ref.projection(),))
    case.endpoint = await fixture.resolver.resolve(exported['endpointRef'], fixture.invocation)
    peer_source_revision = case.prepared.source_revision
    case.prepared = replace(case.prepared,
        context=replace(case.prepared.context, prepared_configuration_refs=(ref,)),
        source_revision=canonical_digest({'peer':case.prepared.source_revision, 'configuration':ref.projection()}))
    case.request = replace(case.request, endpoint_ref=case.endpoint.ref, prepared_configuration_refs=(ref,))
    case.authority.request = case.request
    case.authority.prepared = case.prepared
    provider = case.manager.harness_resolver.resolve(case.authority.pin)
    def resolve(actual, bound, invocation):
        case.authority.check_start(invocation, actual, provider.descriptor)
        assert bound.ref == case.endpoint.ref
        fixture._endpoints.verify(bound.ref.projection(), fixture._scope, ref.projection(), invocation=invocation)
        work = Path(case.prepared.native_working_directory)
        assert 'sha256:' + hashlib.sha256((work/'peer.py').read_bytes()).hexdigest() == peer_source_revision
        directory_digest = canonical_digest({name:{'path':str(work if name=='work' else work/name),
            'inode':(work if name=='work' else work/name).stat().st_ino} for name in case.prepared.context.private_dirs})
        assert directory_digest == case.prepared.directory_binding_digest
        assert case.prepared.source_revision == canonical_digest({'peer':peer_source_revision, 'configuration':ref.projection()})
        return case.prepared
    case.manager.preparation_resolver = SimpleNamespace(resolve=resolve)
    case.config_ref = ref
    return case


def _agent_rows(case, operation):
    return case.records._db.execute('SELECT status,payload FROM operations WHERE operation=? ORDER BY request_id',
                                    (operation,)).fetchall()


def _resource_rows(case):
    with case.fixture._manager.store.transaction() as db:
        return tuple(tuple(row) for row in db.execute(
            'SELECT operation_id,action,target,input_digest,state,result FROM environment_use_requests ORDER BY operation_id'))


async def _close(case):
    case.records.close()
    case.owner.close()
    await case.fixture.cleanup()


def test_verified_inputs_publish_only_after_original_launch_and_bootstrap(tmp_path):
    """A seal/input scope + complete root evidence -> one real publication."""
    async def scenario():
        case = await _prepared_case(tmp_path)
        try:
            assert _agent_rows(case, 'instance-binding') == []
            assert _agent_rows(case, 'instance-control') == []
            publications = []
            original = case.records.publish_started_instance
            def publish(start, provenance, session, protocol, receipt, *, binding_material):
                phases = _agent_rows(case, 'bootstrap-frame')
                assert len(phases) == 2 and all(row[0] == 'completed' for row in phases)
                assert provenance.profile_ref == case.request.profile_revision_ref
                assert provenance.source_revision == case.prepared.source_revision
                assert provenance.directory_binding_digest == case.prepared.directory_binding_digest
                assert tuple(binding_material.configuration_refs) == (case.config_ref,)
                assert any(row[1] == 'launch' and row[4] == 'completed' for row in _resource_rows(case))
                assert _agent_rows(case, 'instance-binding') == []
                publications.append(binding_material)
                return original(start, provenance, session, protocol, receipt, binding_material=binding_material)
            case.records.publish_started_instance = publish
            first = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert first.state == 'running' and first.instance_ref and first.session_id
            assert len(publications) == 1 and publications[0].digest == first.instance_ref.binding_digest
            assert len(_agent_rows(case, 'instance-binding')) == len(_agent_rows(case, 'instance-control')) == 1
            source = InteractionService(case.records, case.authority, case.fixture.resolver)
            provenance = source.read_binding(first.instance_ref, invocation=case.fixture.invocation)
            assert provenance.configuration_refs == (case.config_ref,)
            before = _resource_rows(case)
            case.authority.send = False
            assert await case.manager.start(case.request, case.endpoint, case.fixture.invocation) == first
            assert case.manager.get(case.request.request_id, case.fixture.invocation) == first
            assert _resource_rows(case) == before and len(publications) == 1
            assert case.fixture.retained_use_count == 1
            with pytest.raises(ManagerRefused, match='REQUEST_CONFLICT'):
                await case.manager.start(replace(case.request, session_mode='none'), case.endpoint, case.fixture.invocation)
            assert _resource_rows(case) == before
        finally:
            await _close(case)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['configuration', 'material', 'session'])
def test_valid_but_substituted_provider_plan_never_launches_or_publishes(tmp_path, change):
    """A known plan-vs-fixed-source mismatch refuses with no resource effect."""
    async def scenario():
        case = await _prepared_case(tmp_path)
        try:
            provider = case.manager.harness_resolver.resolve(case.authority.pin)
            def prepare(content, context):
                plan = provider.prepare(content, context)
                if change == 'configuration':
                    return replace(plan, prepared_configuration_refs=(replace(case.config_ref, revision='foreign'),), plan_digest='')
                if change == 'material':
                    return replace(plan, material_refs=(MaterialRef('foreign', 'unverified', '1',
                        'sha256:'+'e'*64, 'application/json', 1),), plan_digest='')
                return replace(plan, session_bootstrap=SessionBootstrap('fresh', 'foreign-source'), plan_digest='')
            hostile = SimpleNamespace(descriptor=provider.descriptor, validate_profile=provider.validate_profile,
                                      prepare=prepare, open_session=provider.open_session)
            case.manager.harness_resolver = SimpleNamespace(resolve=lambda _pin:hostile)
            before = _resource_rows(case)
            first = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert first.state == 'failed' and first.instance_ref is None
            assert first.error.code == 'PREPARATION_REFUSED'
            assert _resource_rows(case) == before
            assert _agent_rows(case, 'bootstrap-frame') == []
            assert _agent_rows(case, 'instance-binding') == _agent_rows(case, 'instance-control') == []
            assert case.fixture.retained_use_count == 1
            assert await case.manager.start(case.request, case.endpoint, case.fixture.invocation) == first
            assert _resource_rows(case) == before
        finally:
            await _close(case)
    asyncio.run(scenario())


def test_changed_real_prepared_bytes_refuse_before_start_reservation(tmp_path):
    async def scenario():
        case = await _prepared_case(tmp_path)
        try:
            (tmp_path/'environment/work/approved.json').write_text('changed-after-approval')
            before = _resource_rows(case)
            with pytest.raises(EnvironmentRefused, match='bytes differ'):
                await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert _agent_rows(case, 'agent-start') == []
            assert _agent_rows(case, 'instance-binding') == []
            assert _resource_rows(case) == before
            assert case.fixture.retained_use_count == 1
        finally:
            await _close(case)
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['copied-task', 'revoked'])
def test_original_physical_guard_refuses_copy_or_revocation_without_publish(tmp_path, failure):
    async def scenario():
        case = await setup(tmp_path)
        try:
            original_resolve = case.fixture.resolver.resolve
            async def resolve(ref, invocation):
                bound = await original_resolve(ref, invocation)
                if bound.communicate is None:
                    return bound
                native = bound.communicate
                class AdversarialTransport:
                    async def send_guarded(self, frame, request_id, deadline, caller, *, binding, write_guard):
                        if failure == 'copied-task':
                            return await asyncio.create_task(native.send_guarded(frame, request_id, deadline, caller,
                                binding=binding, write_guard=write_guard))
                        # Revocation happens after the original phase reservation
                        # and initial external check, at the physical child call.
                        case.authority.send = False
                        return await native.send_guarded(frame, request_id, deadline, caller,
                            binding=binding, write_guard=write_guard)
                    async def receive(self, *args, **kwargs):
                        return await native.receive(*args, **kwargs)
                return replace(bound, communicate=AdversarialTransport())
            case.manager.resolver = SimpleNamespace(resolve=resolve)
            first = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert first.state == 'unknown' and first.instance_ref is None
            assert _agent_rows(case, 'instance-binding') == _agent_rows(case, 'instance-control') == []
            sends = [row for row in _resource_rows(case) if row[1] == 'send-frame']
            assert len(sends) == 1
            child = json.loads(sends[0][5])
            assert child['delivery'] == 'not_sent' and child['bytesObserved'] == 0
            assert case.fixture.retained_use_count == 1
            before = _resource_rows(case)
            case.authority.send = True
            assert await case.manager.start(case.request, case.endpoint, case.fixture.invocation) == first
            assert _resource_rows(case) == before
        finally:
            await _close(case)
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['native-response', 'publication-ledger'])
def test_uncertain_native_or_publication_commit_keeps_owner_and_cold_replay_never_resends(tmp_path, failure):
    async def scenario():
        peer = PEER.replace("result={'protocolVersion':1,", "result={'protocolVersion':True,") if failure == 'native-response' else PEER
        case = await setup(tmp_path, peer)
        try:
            if failure == 'publication-ledger':
                case.records._db.execute("CREATE TRIGGER deny_original_publication BEFORE INSERT ON operations "
                    "WHEN NEW.operation='instance-binding' BEGIN SELECT RAISE(ABORT,'controlled publication commit fault'); END")
            first = await case.manager.start(case.request, case.endpoint, case.fixture.invocation)
            assert first.state == 'unknown' and first.instance_ref is None
            assert _agent_rows(case, 'instance-binding') == _agent_rows(case, 'instance-control') == []
            phases = _agent_rows(case, 'bootstrap-frame')
            assert len(phases) == (1 if failure == 'native-response' else 2)
            if failure == 'publication-ledger':
                assert all(row[0] == 'completed' for row in phases)
                case.records._db.execute('DROP TRIGGER deny_original_publication')
            before = _resource_rows(case)
            assert len([row for row in before if row[1] == 'launch']) == 1
            assert len([row for row in before if row[1] == 'send-frame']) == len(phases)
            case.records.close()
            case.records = Records(tmp_path/'agent.sqlite')
            case.manager.records = case.records
            assert case.manager.get(case.request.request_id, case.fixture.invocation) == first
            assert await case.manager.start(case.request, case.endpoint, case.fixture.invocation) == first
            assert _resource_rows(case) == before
            assert _agent_rows(case, 'instance-binding') == _agent_rows(case, 'instance-control') == []
            assert case.fixture.retained_use_count == 1
        finally:
            await _close(case)
    asyncio.run(scenario())
