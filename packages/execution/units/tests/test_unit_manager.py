"""Two live Units, one original SQLite/evidence authority; no model or grant claim."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_unit_instance import Authority, Provider, Preparation
from ordessa_execution_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_execution_api.environment.operations import safe_json
from ordessa_execution_agents.preparation import ConfigurationResources
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref, canonical_content, content_digest
from ordessa_units.management import UnitManager, UnitInstance, UnitManagementRefused
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.records.unit_records import CanonicalConfigurationScopeRef
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.admission.connection import ConnectionLeasePort


class DistinctScopes:
    def issue_scope(self, provider, node, roots):
        return CanonicalConfigurationScopeRef('env', hashlib.sha256(safe_json(roots).encode()).hexdigest(), '1')
    def verify_scope(self, scope, roots):
        return scope == self.issue_scope(None, None, roots)


@pytest.fixture
def managed(tmp_path):
    events=[]; root=tmp_path/'environment'
    descriptor=RuntimeProviderDescriptor('controlled',RUNTIME_PROVIDER_VERSION,
        {'environmentNamespace':'env','definitionId':'controlled','revision':'1'},'sha256:'+'a'*64,
        ('plan_preparation','prepare','start','connect','describe_access','stop','release'))
    provider={'environmentNamespace':'env','providerId':'controlled','generation':1,
        'contractVersion':RUNTIME_PROVIDER_VERSION,'implementationDigest':descriptor.implementation_digest}
    authority=Authority(provider,None)
    evidence=AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'],
        start_authority=authority.continuation,configuration_authority=authority.continuation)
    records=UnitRecords(OperationJournal(tmp_path/'original.sqlite'),scope_authority=DistinctScopes(),
        native_evidence=evidence,verifier=authority,epoch_port=SimpleNamespace(current_epoch=lambda node:0),
        termination_evidence=evidence,configuration_evidence=evidence)
    evidence.attach_owner(records)
    environments=Provider(root,events); units=[]; calls=[]; fail=[False]
    manifest={'schemaVersion':'1','harnessDefinitionRef':dict(descriptor.definition_ref),'declarations':[],
        'metadata':{'marker':'original-profile'}}
    revision=ProfileRevisionRef('env','profile',1,content_digest(canonical_content(manifest,'env')))
    def materialize(agent,env,facts,snapshot):
        if fail[0]: raise RuntimeError('controlled materialization failure')
        directory=env.files.ensure(str(Path(agent.harness.resources.location).relative_to(root)))
        Path(directory,'settings.json').write_text(json.dumps(dict(snapshot['manifest']['metadata'])))
        return ConfigurationResources('profile-dir',directory,True)
    def factory(plan):
        calls.append(plan)
        unit=UnitInstance(descriptor=descriptor,agent_id='agent',profile_revision=revision,
            environment_instance=environments,environment_sharing=True,
            environment_reference={'environmentId':environments.identity},preparation=Preparation(events),
            materializer=materialize,records=records,projection=evidence,verifier=authority,
            lease_port=ConnectionLeasePort(),termination_evidence=evidence,timeout=2)
        units.append(unit); return unit
    manager=UnitManager(create_instance=factory,records=records,verifier=authority)
    def plan(name):
        return {'profileSnapshot':{'ref':encode_revision_ref(revision),'manifest':manifest},
            'context':{'nodeRef':{'environmentNamespace':'env','nodeId':name,'generation':1},
                'privateRootFacts':{k:str(root/name/k) for k in ('home','cwd','profile')}}}
    def issue(name,action):
        authority.node=plan(name)['context']['nodeRef']
        context=authority.issue(action)
        context.facts['request']['requestId']=name+'.'+action
        context.facts['operationRef']=name+'.original-operation'
        return context
    yield SimpleNamespace(manager=manager,plan=plan,issue=issue,records=records,evidence=evidence,
        environments=environments,calls=calls,units=units,fail=fail,events=events,authority=authority)
    for unit in units:
        record=unit.channel_factory.owned_record; use=unit.channel_factory.environment
        if use is not None and use.identity not in environments.release_receipts:
            if record is not None:
                if record.process.observe().state!='exited':
                    if record.channel is not None:
                        record.entry.run_process_operation(record.channel.close_async(timeout=2),timeout=10)
                    else:
                        async def cleanup():
                            await record.process.cancel(force=True)
                            await record.process.wait_exit(timeout=5)
                        asyncio.run(cleanup())
                record.process.release()
            use.release()
        if record is not None and hasattr(record.entry,'detach'): record.entry.detach()


def test_two_units_share_original_owners_and_release_only_their_use(managed):
    m=managed
    a=m.manager.create(m.plan('a'),m.issue('a','prepare'))
    b=m.manager.create(m.plan('b'),m.issue('b','prepare'))
    ar=a.prepared_unit['unitRef'];br=b.prepared_unit['unitRef']
    assert a.records is b.records is m.records and a.projection is b.projection is m.evidence
    assert m.manager.list()==(a,b) and m.manager.find(ar) is a and m.manager.find(br) is b
    assert m.environments.instance.snapshot.active_uses==2 and m.events.count('spawn')==0
    with pytest.raises(TypeError): a.prepared_unit['unitRef']['unitId']='forged'
    for name,unit in [('a',a),('b',b)]:
        unit.start(unit.prepared_unit,m.issue(name,'start'))
        grant=unit.lease_port.grant(unit.prepared_unit['unitRef'])
        assert unit.prompt(unit.prepared_unit['unitRef'],grant,prompt=[],timeout=2)['observedConfiguration']=={'marker':'original-profile'}
    assert m.events.count('spawn')==2
    with pytest.raises(UnitLifecycleRefused,match='stop before release'):
        m.manager.release(ar,m.issue('a','release'))
    assert m.manager.find(ar) is a
    with pytest.raises(UnitLifecycleRefused,match='Foreign Unit channel'):
        m.evidence.bind_unit_channel(ar['unitId'],b.channel_factory.owned_record)
    a.stop(ar,m.issue('a','stop'))
    assert m.manager.release(ar,m.issue('a','release'))['state']=='confirmed'
    assert m.manager.list()==(b,) and m.environments.instance.snapshot.active_uses==1
    assert b.channel_factory.owned_record.process.observe().state=='running'
    b.stop(br,m.issue('b','stop'))
    assert m.manager.release(br,m.issue('b','release'))['state']=='confirmed'
    assert m.manager.list()==() and m.environments.instance.snapshot.active_uses==0
    use=m.environments.instance.acquire('same-resource-after-units',sharing=True)
    assert use.environment_id==m.environments.identity
    assert use.release()['resourcePreserved'] is True


def test_duplicate_creation_and_foreign_references_do_not_replay(managed):
    m=managed;context=m.issue('a','prepare');a=m.manager.create(m.plan('a'),context)
    with pytest.raises(UnitManagementRefused,match='never replay'):
        m.manager.create(m.plan('a'),context)
    assert len(m.calls)==1 and m.environments.opens==1
    ref=dict(a.prepared_unit['unitRef']);ref['unitId']='foreign'
    with pytest.raises(UnitManagementRefused):m.manager.find(ref)
    ref=dict(a.prepared_unit['unitRef']);ref['sourceRevision']='forged'
    with pytest.raises(UnitManagementRefused):m.manager.find(ref)
    other=UnitManager(create_instance=lambda plan:a,records=m.records,verifier=m.authority)
    with pytest.raises(UnitManagementRefused):other.find(a.prepared_unit['unitRef'])
    with pytest.raises(UnitManagementRefused,match='fresh fixed Unit'):
        other.create(m.plan('b'),m.issue('b','prepare'))


def test_partial_prepare_retains_original_handle_and_original_failure(managed):
    m=managed;m.fail[0]=True;context=m.issue('a','prepare')
    with pytest.raises(RuntimeError,match='controlled materialization failure'):
        m.manager.create(m.plan('a'),context)
    assert m.manager.list()==tuple(m.units) and m.environments.opens==1
    with pytest.raises(UnitManagementRefused,match='never replay'):
        m.manager.create(m.plan('a'),context)
    assert len(m.calls)==1 and m.events.count('spawn')==0
    a=m.units[0]
    assert a.stop(a.prepared_unit['unitRef'],m.issue('a','stop'))['state']=='confirmed'
    assert m.manager.release(a.prepared_unit['unitRef'],m.issue('a','release'))['state']=='confirmed'
    assert m.manager.list()==()


def test_evidence_rejects_foreign_factory_roots_and_rebinding(managed):
    m=managed;a=m.manager.create(m.plan('a'),m.issue('a','prepare'))
    b=m.manager.create(m.plan('b'),m.issue('b','prepare'))
    ar=a.prepared_unit['unitRef']['unitId']; roots=m.plan('a')['context']['privateRootFacts']
    with pytest.raises(UnitLifecycleRefused,match='Foreign Unit channel factory'):
        m.evidence.bind_preparation(ar,object(),roots)
    with pytest.raises(UnitLifecycleRefused,match='roots differ'):
        m.evidence.bind_preparation(ar,a.channel_factory,m.plan('b')['context']['privateRootFacts'])
    with pytest.raises(UnitLifecycleRefused,match='Cannot replace'):
        m.evidence.bind_preparation(ar,b.channel_factory,roots)
