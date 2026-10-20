"""Real SQLite + LocalEnvironment process/ACP; controlled authority and peer.

No production human grant, model, user configuration or side-effect approval
claim. The same UnitRecords tickets and managed writer enforce the boundaries.
"""
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
import sys
from uuid import uuid4

import pytest

from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
import asyncio
from ordessa_execution_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_execution_agents.preparation import PreparedHarness, SessionBootstrap, ConfigurationResources
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref, canonical_content, content_digest
from ordessa_execution_agents.harness.transport import LaunchSpec, ProcessChannel
from ordessa_units.management import UnitInstance
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.records.unit_records import CanonicalConfigurationScopeRef, UnitRecordsRefused
from ordessa_units.admission.connection import ConnectionLeasePort, ConnectionLeaseRefused
from ordessa_units.sessions.evidence import AcpUnitEvidence


PEER = r'''
import json, os, sys
options=[{'id':'thinkingLevel','type':'select','name':'Thinking','currentValue':'low','options':[{'value':'low','name':'Low'},{'value':'high','name':'High'}]}]
behavior='normal'
for line in sys.stdin:
    q=json.loads(line); method=q['method']; p=q.get('params',{})
    if method=='initialize': r={'protocolVersion':1,'agentCapabilities':{'loadSession':True}}
    elif method=='session/new': r={'sessionId':'controlled-native-session','configOptions':options}
    elif method=='session/load': r={}
    elif method=='controlled/option-behavior': behavior=p['behavior'];r={}
    elif method=='_ordessa/session/configuration': r={'sessionId':'controlled-native-session','configOptions':options}
    elif method=='session/set_config_option':
        with open(os.environ['FIXTURE_CONFIG']+'.option-writes','a') as log:log.write('set\n')
        if behavior!='ackOnly':options[0]['currentValue']=p['value']
        if behavior=='dropReceipt':continue
        r={'configOptions':options}
    elif method=='session/cancel': continue
    elif method=='session/prompt':
        callbacks=[]
        for callback in p.get('controlledCallbacks',[]):
            print(json.dumps({'jsonrpc':'2.0',**callback}),flush=True)
            callbacks.append(json.loads(sys.stdin.readline()))
        r={'stopReason':'end_turn','observedConfiguration':json.load(open(os.environ['FIXTURE_CONFIG'])),'callbacks':callbacks,'runtimeOptions':options}
    elif method=='controlled/lost': sys.exit(0)
    else: r={}
    print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':r}),flush=True)
'''


@dataclass(eq=False)
class Invocation:
    facts: dict


class Authority:
    def __init__(self, provider, node):
        self.provider,self.node=provider,node
        self.issued=set();self.spent=set();self.allowed=True

    def issue(self, action):
        context=Invocation({'query':False,'action':action,'providerRef':self.provider,
            'targetRef':self.node,'inputDigest':action+'-fixed-input','managementEpoch':0,
            'request':{'environmentNamespace':'env','principalScope':'controlled','requestId':action},
            'operationRef':'original-operation','stepId':action})
        self.issued.add(context)
        return context

    def _verify(self, context, action, provider, node, digest):
        assert self.allowed and context in self.issued
        facts=context.facts
        assert (action,provider,node,digest)==(facts['action'],facts['providerRef'],facts['targetRef'],facts['inputDigest'])
        return facts

    def verify_admission(self, context, action, provider, node, digest):
        # The lifecycle preflight checks the same ticket without consuming it.
        return self._verify(context, action, provider, node, digest)

    def verify_and_consume(self, context, action, provider, node, digest):
        facts = self._verify(context, action, provider, node, digest)
        self.issued.remove(context);self.spent.add(context)
        return facts

    def continuation(self, unit, context):
        if not self.allowed or context not in self.spent:
            raise UnitLifecycleRefused('controlled start authority revoked')
        return context.facts


class Scope:
    def issue_scope(self, provider, node, roots):
        return CanonicalConfigurationScopeRef('env','configuration','1')
    def verify_scope(self, scope, roots): return scope.environment_namespace=='env'


class Provider:
    def __init__(self, root, events):
        self.events=events;self.opens=0;self.release_receipts={}
        provider=LocalEnvironmentResourceProvider(default_root=str(root))
        manager=EnvironmentManager(store=SQLiteEnvironmentStore(root.parent/'environment.sqlite'), providers={'local':provider})
        self.instance=manager.create('local',{'root':str(root)})
        self.identity=self.instance.identity
    def acquire(self, owner_id, *, sharing):
        self.events.append('acquire');self.opens+=1
        handle=self.instance.acquire(owner_id,sharing=sharing)
        release=handle.release
        identity=handle.identity
        def release_use():
            receipt=release()
            assert receipt["useIdentity"]==identity and receipt["environmentIdentity"]==self.identity
            self.release_receipts[identity]=receipt
            return receipt
        handle.release=release_use
        original=handle.execution.start
        def start(request):
            self.events.append('spawn');return original(request)
        handle.execution.start=start
        return handle


class Preparation:
    harness_id='controlled-acp'
    def __init__(self, events): self.events=events
    def prepare(self, roots):
        self.events.append('prepare')
        return PreparedHarness(self.harness_id,
            LaunchSpec.build([sys.executable,'-u','-c',PEER],home=roots['home'],cwd=roots['cwd'],
                extra_env={'FIXTURE_CONFIG':str(Path(roots['profile'])/'settings.json')}),
            SessionBootstrap('fresh',roots['cwd']),ConfigurationResources('profile-dir',roots['profile'],False),
            {'identity':self.harness_id,'version':'controlled-1','protocol':'acp/v1','configurationReadMethod':'_ordessa/session/configuration'})


@pytest.fixture
def flow(tmp_path, monkeypatch):
    events=[];root=tmp_path/'environment'
    roots={k:str(root/k) for k in ('home','cwd','profile')}
    descriptor=RuntimeProviderDescriptor('controlled',RUNTIME_PROVIDER_VERSION,
        {'environmentNamespace':'env','definitionId':'controlled','revision':'1'},'sha256:'+'a'*64,
        ('plan_preparation','prepare','start','connect','describe_access','stop','release'))
    provider={'environmentNamespace':'env','providerId':'controlled','generation':1,
        'contractVersion':RUNTIME_PROVIDER_VERSION,'implementationDigest':descriptor.implementation_digest}
    node={'environmentNamespace':'env','nodeId':'unit','generation':1}
    authority=Authority(provider,node)
    evidence=AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'],
        start_authority=authority.continuation,configuration_authority=authority.continuation)
    journal_path = tmp_path / 'original.sqlite'
    journal_path.touch(exist_ok=False)  # Explicit pristine test-owned schema opt-in.
    journal=OperationJournal(journal_path, acp_turn_opt_in=True)
    records=UnitRecords(journal,scope_authority=Scope(),native_evidence=evidence,
        verifier=authority,epoch_port=SimpleNamespace(current_epoch=lambda node:0),termination_evidence=evidence,configuration_evidence=evidence,
        acp_turn_opt_in=True)
    evidence.attach_owner(records)
    environments=Provider(root,events);leases=ConnectionLeasePort()
    manifest={'schemaVersion':'1','harnessDefinitionRef':dict(descriptor.definition_ref),'declarations':[],
        'metadata':{'marker':'actual-materialized-revision-1'}}
    revision=ProfileRevisionRef('env','profile',1,content_digest(canonical_content(manifest,'env')))
    def materialize(agent,env,facts,snapshot):
        assert facts['action']=='prepare' and agent.profile_revision
        events.append('materialize')
        directory=env.files.ensure('profile')
        import json
        Path(directory,'settings.json').write_text(json.dumps(dict(snapshot['manifest']['metadata'])))
        return ConfigurationResources(agent.harness.resources.kind,directory,True)
    instance=UnitInstance(descriptor=descriptor,agent_id='agent',profile_revision=revision,
        environment_instance=environments,environment_sharing=True,environment_reference={'environmentId':environments.identity},
        preparation=Preparation(events),materializer=materialize,records=records,projection=evidence,
        verifier=authority,lease_port=leases,termination_evidence=evidence,timeout=2)
    plan={'profileSnapshot':{'ref':encode_revision_ref(revision),'manifest':manifest},'context':{'nodeRef':node,'privateRootFacts':roots}}
    def forbidden(*args,**kwargs):raise AssertionError('ACP must not launch')
    monkeypatch.setattr(ProcessChannel,'launch',forbidden)
    result=SimpleNamespace(instance=instance,authority=authority,plan=plan,records=records,
        events=events,environments=environments,leases=leases,evidence=evidence)
    yield result
    record=instance.channel_factory.owned_record
    environment=instance.channel_factory.environment
    released=environment is not None and environment.identity in environments.release_receipts
    if released:
        receipt=environments.release_receipts[environment.identity]
        assert receipt['useIdentity']==environment.identity
        assert receipt['environmentIdentity']==environment.environment_id
        assert receipt['resourcePreserved'] is True
    if record is not None:
        if not released:
            observation=record.process.observe()
            if observation.state != 'exited':
                if record.channel is not None:
                    record.entry.run_process_operation(record.channel.close_async(timeout=2),timeout=10)
                else:
                    async def cleanup():
                        await record.process.cancel(force=True)
                        await record.process.wait_exit(timeout=5)
                    asyncio.run(cleanup())
            assert record.process.observe().state=='exited'
            record.process.release()
        if hasattr(record.entry,'detach'):record.entry.detach()
    if environment is not None:
        environment.release()


def prepare_and_start(flow):
    prepared=flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    started=flow.instance.start(prepared,flow.authority.issue('start'))
    return prepared,started


def prompt_result(instance, unit_ref, lease, **params):
    receipt = instance.prompt(unit_ref, lease, operation_ref='unit-test/' + uuid4().hex, **params)
    return receipt['response']['result']


def test_complete_unit_uses_original_records_fixed_profile_environment_process_and_session(flow):
    prepared,started=prepare_and_start(flow)
    assert flow.events==['acquire','prepare','materialize','spawn']
    assert flow.instance.prepared_agent.harness.resources.applied
    from acp.connection import Connection
    from ordessa_units.sessions.sdk_client import SdkAcpClient
    assert type(flow.instance.channel_factory.owned_record.entry) is SdkAcpClient
    assert type(flow.instance.channel_factory.owned_record.entry.sdk_connection) is Connection
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state=='confirmed'
    assert started['nativeBinding']['nativeRealm']==flow.instance.environment_identity
    record=flow.instance.channel_factory.owned_record
    assert flow.environments.instance.snapshot.active_uses==1
    assert record.environment_use_identity == flow.instance.channel_factory.environment.identity
    assert record.environment_identity == flow.environments.identity
    grant=flow.leases.grant(prepared['unitRef'])
    connection=flow.instance.connect(prepared['unitRef'],grant)
    for _ in range(2):
        result=prompt_result(flow.instance,prepared['unitRef'],grant,prompt=[{'type':'text','text':'controlled'}],timeout=2)
        assert result['observedConfiguration']=={'marker':'actual-materialized-revision-1'}
    assert flow.instance.stop(prepared['unitRef'],flow.authority.issue('stop'))['state']=='confirmed'
    assert record.process.observe().state=='exited'
    assert flow.instance.release(prepared['unitRef'],flow.authority.issue('release'))['state']=='confirmed'
    assert Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json').is_file()
    use=flow.instance.channel_factory.environment
    assert flow.environments.release_receipts[use.identity]['useIdentity']==use.identity
    from ordessa_environments import EnvironmentRefused
    with pytest.raises(EnvironmentRefused):record.process.observe()
    assert flow.environments.instance.snapshot.active_uses==0
    with pytest.raises(ConnectionLeaseRefused):
        connection.prompt(prompt=[],timeout=2)


def test_profile_drift_refuses_before_acquire_or_record_reservation(flow):
    flow.plan['profileSnapshot']['ref']['revision']=2
    with pytest.raises(UnitLifecycleRefused,match='fixed complete Profile'):
        flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    assert flow.environments.opens==0


def test_profile_content_tampering_is_rejected_before_effects(flow):
    flow.plan['profileSnapshot']['manifest']['metadata']['marker']='forged'
    from ordessa_execution_agents.profiles import ProfileValidationError
    with pytest.raises(ProfileValidationError,match='digest does not match'):
        flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    assert flow.environments.opens==0


def test_definition_and_prepared_profile_are_immutable(flow):
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):flow.instance.definition.agent_id='replacement'
    with pytest.raises(AttributeError):flow.instance.profile_revision=None
    with pytest.raises(AttributeError):flow.instance.definition=object()
    prepared,_=prepare_and_start(flow)
    original=flow.instance.prepared_agent
    flow.plan['profileSnapshot']['manifest']['metadata']['marker']='profile-edited-after-start'
    assert flow.instance.prepared_agent is original
    grant=flow.leases.grant(prepared['unitRef'])
    assert prompt_result(flow.instance,prepared['unitRef'],grant,prompt=[],timeout=2)['observedConfiguration']['marker']=='actual-materialized-revision-1'


def test_foreign_session_and_forged_grant_cannot_prompt(flow):
    prepared,_=prepare_and_start(flow)
    with pytest.raises(UnitLifecycleRefused,match='different fixed Run'):
        flow.instance.prompt(prepared['unitRef'],object(),operation_ref='unit-test/foreign-session',sessionId='foreign',prompt=[])
    with pytest.raises(ConnectionLeaseRefused):
        flow.instance.prompt(prepared['unitRef'],object(),operation_ref='unit-test/forged-lease',prompt=[])


def test_revoked_connection_cuts_existing_view_before_further_write(flow):
    prepared,_=prepare_and_start(flow)
    grant=flow.leases.grant(prepared['unitRef'])
    connection=flow.instance.connect(prepared['unitRef'],grant)
    flow.leases.revoke(prepared['unitRef'])
    with pytest.raises(ConnectionLeaseRefused):connection.prompt(prompt=[])
    assert flow.instance.channel_factory.owned_record.process.observe().state=='running'


def test_release_of_live_unit_does_not_kill_or_consume_release_claim(flow):
    prepared,_=prepare_and_start(flow)
    context=flow.authority.issue('release')
    with pytest.raises(UnitLifecycleRefused,match='requires stop'):
        flow.instance.release(prepared['unitRef'],context)
    assert context in flow.authority.issued
    assert flow.instance.channel_factory.owned_record.process.observe().state=='running'


def test_attach_failure_keeps_unknown_original_attempt_and_owned_process_for_stop(flow,monkeypatch):
    prepared=flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    def fail(*args,**kwargs):raise RuntimeError('controlled attachment failure')
    monkeypatch.setattr(ProcessChannel,'attach',fail)
    with pytest.raises(UnitLifecycleRefused,match='creation unknown'):
        flow.instance.start(prepared,flow.authority.issue('start'))
    binding=flow.records.owner_read_session(prepared['unitRef']['unitId'])
    assert binding.state=='unknown'
    record=flow.instance.channel_factory.owned_record
    assert record.process.observe().state=='running'
    with pytest.raises(Exception):flow.instance.start(prepared,flow.authority.issue('start'))
    assert flow.events.count('spawn')==1
    assert flow.instance.stop(prepared['unitRef'],flow.authority.issue('stop'))['state']=='confirmed'
    assert record.process.observe().state=='exited'


def test_stop_during_attach_waits_pending_then_cleans_exact_unknown_process(flow,monkeypatch):
    prepared=flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    start_context=flow.authority.issue('start')
    stop_context=flow.authority.issue('stop')
    entered, resume=Event(), Event()
    start_errors=[]

    def held_attach_failure(*args,**kwargs):
        entered.set()
        if not resume.wait(5):
            raise TimeoutError('controlled attach was not released')
        raise RuntimeError('controlled attachment failure')

    monkeypatch.setattr(ProcessChannel,'attach',held_attach_failure)

    def start_original():
        try:
            flow.instance.start(prepared,start_context)
        except BaseException as error:
            start_errors.append(error)

    worker=Thread(target=start_original)
    worker.start()
    assert entered.wait(5)
    record=flow.instance.channel_factory.owned_record
    assert record is not None and record.channel is None
    assert record.process.observe().state=='running'

    pending=flow.instance.stop(prepared['unitRef'],stop_context)
    assert pending=={'unitRef':prepared['unitRef'],'action':'stop',
        'state':'pending','unresolved':True}
    assert flow.records.owner_read_termination(prepared['unitRef']['unitId'],'stop') is None
    assert flow.instance.channel_factory.owned_record is record
    assert record.process.observe().state=='running'

    resume.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(start_errors)==1
    assert isinstance(start_errors[0],UnitLifecycleRefused)
    assert 'creation unknown' in str(start_errors[0])
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state=='unknown'
    assert flow.events.count('spawn')==1

    stopped=flow.instance.stop(prepared['unitRef'],stop_context)
    assert stopped['state']=='confirmed'
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state=='unknown'
    assert record.process.observe().state=='exited'
    assert flow.records.owner_read_termination(prepared['unitRef']['unitId'],'stop')['state']=='confirmed'


def test_start_authority_revocation_does_not_spawn_or_auto_release_unknown(flow):
    prepared=flow.instance.prepare(flow.plan,flow.authority.issue('prepare'))
    context=flow.authority.issue('start')
    original=flow.evidence.start_authority
    flow.evidence.start_authority=lambda unit,context:(_ for _ in ()).throw(UnitLifecycleRefused('revoked'))
    with pytest.raises(UnitLifecycleRefused,match='creation unknown'):flow.instance.start(prepared,context)
    assert flow.records.owner_read_session(prepared['unitRef']['unitId']).state=='unknown'
    assert flow.events.count('spawn')==0


class CallbackOwner:
    def __init__(self):self.calls=[];self.allowed=True
    def authorize(self, **facts):
        self.calls.append(facts)
        assert facts['session_id']=='controlled-native-session'
        assert facts['environment_identity'].startswith('environment/')
        return self.allowed


def test_actual_reverse_file_callback_bound_environment_permission_and_duplicate_fence(flow,monkeypatch):
    owner=CallbackOwner();flow.instance.callbacks.approval=owner
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    files=flow.instance.channel_factory.environment.files
    target=str(Path(files.root())/'callback.txt')
    calls=[];original=files.write_text
    def write(path,content):calls.append((path,content));return original(path,content)
    monkeypatch.setattr(files,'write_text',write)
    callback={'id':'original-reverse-1','method':'fs/write_text_file',
              'params':{'sessionId':'controlled-native-session','path':target,'content':'actual callback write'}}
    response=prompt_result(flow.instance,unit,grant,prompt=[],controlledCallbacks=[callback,callback],timeout=2)
    assert [r['result'] for r in response['callbacks']]==[{},{}]
    assert files.read_text('callback.txt')=='actual callback write'
    assert len(calls)==len(owner.calls)==1
    read={'id':'reverse-read','method':'fs/read_text_file','params':{'sessionId':'controlled-native-session','path':target}}
    assert prompt_result(flow.instance,unit,grant,prompt=[],controlledCallbacks=[read],timeout=2)['callbacks'][0]['result']['content']=='actual callback write'
    owner.allowed=False
    refused={**callback,'id':'reverse-denied','params':{**callback['params'],'content':'not approved'}}
    assert 'error' in prompt_result(flow.instance,unit,grant,prompt=[],controlledCallbacks=[refused],timeout=2)['callbacks'][0]
    assert files.read_text('callback.txt')=='actual callback write'


def test_callbacks_refuse_foreign_session_escape_missing_approval_and_terminal(flow):
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    root=flow.instance.channel_factory.environment.files.root()
    for identifier,method,path,session in [('missing','fs/write_text_file',str(Path(root)/'no.txt'),'controlled-native-session'),
        ('foreign','fs/write_text_file',str(Path(root)/'no.txt'),'other-session'),
        ('terminal','terminal/create',root,'controlled-native-session')]:
        callback={'id':identifier,'method':method,'params':{'sessionId':session,'path':path,'content':'denied','command':'false'}}
        assert 'error' in prompt_result(flow.instance,unit,grant,prompt=[],controlledCallbacks=[callback],timeout=2)['callbacks'][0]
    assert not Path(root,'no.txt').exists()
    flow.instance.callbacks.approval=CallbackOwner()
    callback={'id':'escape','method':'fs/write_text_file','params':{'sessionId':'controlled-native-session','path':str(Path(root).parent/'escaped.txt'),'content':'denied'}}
    assert 'error' in prompt_result(flow.instance,unit,grant,prompt=[],controlledCallbacks=[callback],timeout=2)['callbacks'][0]
    assert not Path(root).parent.joinpath('escaped.txt').exists()
    assert flow.events.count('spawn')==1
    with pytest.raises(UnitLifecycleRefused,match='original environment/approval owner'):
        flow.instance.prompt(unit,grant,operation_ref='unit-test/forbidden-callback',prompt=[],on_request=lambda request:None)


def test_cold_restart_never_relaunches_or_replaces_original_native_binding(flow):
    prepared,_=prepare_and_start(flow)
    evidence=AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'],start_authority=flow.authority.continuation)
    records=UnitRecords(OperationJournal(flow.records.journal.path),scope_authority=Scope(),native_evidence=evidence,
        verifier=flow.authority,epoch_port=SimpleNamespace(current_epoch=lambda n:0),termination_evidence=evidence)
    evidence.attach_owner(records)
    old=flow.instance
    cold=UnitInstance(descriptor=old.descriptor,agent_id=old.agent_id,profile_revision=old.profile_revision,
        environment_instance=flow.environments,environment_sharing=True,environment_reference=old.definition.environment_reference,
        preparation=Preparation(flow.events),materializer=lambda *args:None,records=records,projection=evidence,
        verifier=flow.authority,lease_port=ConnectionLeasePort(),termination_evidence=evidence,timeout=2)
    with pytest.raises(UnitLifecycleRefused,match='same-channel session receipt'):
        cold.start(prepared,flow.authority.issue('start'))
    assert flow.environments.opens==flow.events.count('spawn')==1
    with records.journal._connect() as db:
        rows=db.execute('SELECT state FROM harness_unit_sessions').fetchall()
    assert len(rows)==1 and rows[0]['state']=='confirmed'
    with pytest.raises(UnitLifecycleRefused,match='Cold native reconciliation'):
        evidence.query_creation('original',{'query':True})


def configuration_invocation(flow,unit,*,query=False,name='configuration-once'):
    target=flow.records.owner_read_unit(unit['unitId']).configuration_target_ref
    facts={'query':query,'action':'query' if query else 'applyConfiguration','providerRef':flow.authority.provider,
        'targetRef':dict(target),'inputDigest':'same-fixed-configuration-input','managementEpoch':0,
        'request':{'environmentNamespace':'env','principalScope':'controlled','requestId':name},
        'operationRef':name,'stepId':name}
    context=Invocation(facts);flow.authority.issued.add(context);return context


def test_acp_option_temporary_override_confirmed_in_original_journal_without_profile_change(flow):
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    before=flow.instance.configuration_snapshot(unit,grant)
    revision=flow.instance.profile_revision
    context=configuration_invocation(flow,unit)
    result=flow.instance.set_config_option(unit,grant,config_id='thinkingLevel',value='high',
        expected_revision=before['sourceRevision'],invocation_context=context)
    assert result['state']=='confirmed' and result['temporary'] is True
    assert flow.instance.profile_revision==revision
    assert flow.instance.prepared_agent.profile_revision==result['profileRevision']
    observed=prompt_result(flow.instance,unit,grant,prompt=[],timeout=2)
    assert observed['runtimeOptions'][0]['currentValue']=='high'
    assert observed['observedConfiguration']=={'marker':'actual-materialized-revision-1'}
    with pytest.raises(UnitRecordsRefused,match='existing configuration attempt'):
        flow.instance.set_config_option(unit,grant,config_id='thinkingLevel',value='high',
            expected_revision=result['snapshot']['sourceRevision'],invocation_context=configuration_invocation(flow,unit))
    query=flow.instance.query_config_change(unit,configuration_invocation(flow,unit,query=True))
    assert query.state=='confirmed' and query.native_request_id is not None
    with flow.records.journal._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_configuration_attempts').fetchone()[0]==1
    assert Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json.option-writes').read_text()=='set\n'


@pytest.mark.parametrize('behavior',['dropReceipt','ackOnly'])
def test_configuration_lost_receipt_or_mismatched_readback_retains_unknown_and_never_retries(flow,behavior):
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    before=flow.instance.configuration_snapshot(unit,grant)
    flow.instance.channel_factory.timeout=.05
    flow.instance.channel_factory.owned_record.entry.command('controlled/option-behavior',behavior=behavior)
    result=flow.instance.set_config_option(unit,grant,config_id='thinkingLevel',value='high',
        expected_revision=before['sourceRevision'],invocation_context=configuration_invocation(flow,unit))
    assert result['state']=='unknown'
    query=flow.instance.query_config_change(unit,configuration_invocation(flow,unit,query=True))
    assert query.state=='unknown'
    with pytest.raises(ConnectionLeaseRefused):flow.instance.prompt(unit,grant,operation_ref='unit-test/revoked-lease',prompt=[])
    writes=Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json.option-writes')
    assert writes.read_text()=='set\n'
    query_again=flow.instance.query_config_change(unit,configuration_invocation(flow,unit,query=True))
    assert query_again.native_request_id==query.native_request_id
    assert writes.read_text()=='set\n'


@pytest.mark.parametrize('config_id,value,revision',[('not-supported','high',None),('thinkingLevel','not-negotiated',None),('thinkingLevel','high','stale')])
def test_unsupported_or_stale_options_refused_before_journal_claim_and_native_write(flow,config_id,value,revision):
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    before=flow.instance.configuration_snapshot(unit,grant)
    with pytest.raises(UnitLifecycleRefused):
        flow.instance.set_config_option(unit,grant,config_id=config_id,value=value,
            expected_revision=revision or before['sourceRevision'],invocation_context=configuration_invocation(flow,unit))
    with flow.records.journal._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_configuration_attempts').fetchone()[0]==0
    assert not Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json.option-writes').exists()


@pytest.mark.parametrize('edge',['revoked','mutated-facts'])
def test_configuration_original_authority_cut_prevents_bytes_at_admitted_write(flow,edge):
    prepared,_=prepare_and_start(flow);unit=prepared['unitRef'];grant=flow.leases.grant(unit)
    before=flow.instance.configuration_snapshot(unit,grant)
    original=flow.evidence.configuration_authority
    calls=[]
    def revalidate(unit_record,context):
        calls.append(True)
        if edge=='revoked' and len(calls)==2:flow.authority.allowed=False
        if edge=='mutated-facts':context.facts['inputDigest']='replacement-input'
        return original(unit_record,context)
    flow.evidence.configuration_authority=revalidate
    result=flow.instance.set_config_option(unit,grant,config_id='thinkingLevel',value='high',
        expected_revision=before['sourceRevision'],invocation_context=configuration_invocation(flow,unit))
    assert result['state']=='unknown'
    assert not Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json.option-writes').exists()
    assert len(calls)==(2 if edge=='revoked' else 1)
    with flow.records.journal._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM harness_unit_configuration_attempts WHERE state="unknown"').fetchone()[0]==1


def test_remote_prompt_failure_preserves_sdk_error_and_releases_original_use(flow, monkeypatch):
    from ordessa_execution_agents.harness.protocols.acp import AcpRemoteError
    failing_peer = PEER.replace("elif method=='session/prompt':", """elif method=='session/prompt':
        print(json.dumps({'jsonrpc':'2.0','id':q['id'],'error':{'code':-32603,'message':'backend prompt failed','data':{'source':'backend','error':'controlled Connection error'}}}),flush=True)
        continue
    elif method=='unused/prompt':""")
    monkeypatch.setitem(globals(), 'PEER', failing_peer)
    prepared, started = prepare_and_start(flow)
    grant = flow.leases.grant(prepared['unitRef'])
    record = flow.instance.channel_factory.owned_record
    with pytest.raises(AcpRemoteError) as caught:
        prompt_result(flow.instance, prepared['unitRef'], grant, prompt=[{'type':'text','text':'controlled'}], timeout=2)
    error = caught.value
    assert error.method == 'session/prompt' and error.raw_error['code'] == -32603
    assert error.remote_data == {'source':'backend','error':'controlled Connection error'}
    assert error.remote_code == -32603
    receipt = record.entry._last_response
    assert receipt['id'] == error.request_id and receipt['error'] == error.raw_error
    assert 'result' not in receipt
    assert flow.events.count('spawn') == 1
    assert flow.instance.stop(prepared['unitRef'], flow.authority.issue('stop'))['state'] == 'confirmed'
    assert flow.instance.release(prepared['unitRef'], flow.authority.issue('release'))['state'] == 'confirmed'
    assert flow.environments.instance.snapshot.active_uses == 0
    assert Path(flow.plan['context']['privateRootFacts']['profile'],'settings.json').is_file()
