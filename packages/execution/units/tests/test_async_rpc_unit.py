"""Official gRPC/ACP controlled peers; no real sandbox or model claim."""
import importlib.util
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest
from openshell._proto import openshell_pb2 as pb, openshell_pb2_grpc as services
from openshell.sandbox import SandboxClient
from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore, EnvironmentRefused
from ordessa_environments_openshell import OpenShellConfiguration, OpenShellEnvironmentProvider
from ordessa_execution_agents.preparation import PreparedHarness, SessionBootstrap, ConfigurationResources
from ordessa_execution_agents.harness.transport import LaunchSpec, LostReceipt, RequestTimeout
from ordessa_units.management import UnitInstance
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_units.admission.connection import ConnectionLeasePort, ConnectionLeaseRefused
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref, canonical_content, content_digest
from ordessa_execution_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from types import SimpleNamespace
from test_unit_instance import Authority, Scope

_path = Path(__file__).resolve().parents[4]/'plugins/environments/openshell/tests/test_rpc.py'
_spec = importlib.util.spec_from_file_location('controlled_environment_rpc_peer', _path)
_peer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_peer)


class AcpPeer(_peer.Peer):
    def ExecSandboxInteractive(self, requests, context):
        start = next(requests).start
        assert not start.tty and start.no_login_shell
        assert start.request_id not in self.request_ids
        self.request_ids.add(start.request_id)
        self.starts.append(start)
        session = 'session-'+start.request_id
        buffer = b''
        yield pb.ExecSandboxEvent(stderr=pb.ExecSandboxStderr(data=b'controlled-stderr'))
        for item in requests:
            buffer += item.stdin
            while b'\n' in buffer:
                frame, buffer = buffer.split(b'\n', 1)
                q = json.loads(frame)
                method = q['method']
                if method == 'controlled/eof':
                    return  # Transport EOF deliberately carries no exit receipt.
                if method == 'controlled/silent' or method == 'session/cancel':
                    continue
                if method == 'initialize':
                    result = {'protocolVersion':1, 'agentCapabilities':{'loadSession':True}}
                elif method == 'session/new':
                    result = {'sessionId':session, 'configOptions':[]}
                elif method == 'session/prompt':
                    assert q['params']['sessionId'] == session
                    result = {'stopReason':'end_turn', 'originalSession':session}
                else:
                    result = {}
                response = {'jsonrpc':'2.0', 'id':q['id'], 'result':result}
                yield pb.ExecSandboxEvent(stdout=pb.ExecSandboxStdout(data=(json.dumps(response)+'\n').encode()))
        yield pb.ExecSandboxEvent(exit=pb.ExecSandboxExit(exit_code=0))


@pytest.fixture
def remote(tmp_path):
    peer = AcpPeer()
    server = grpc.server(ThreadPoolExecutor(max_workers=12))
    services.add_OpenShellServicer_to_server(peer, server)
    port = server.add_insecure_port('127.0.0.1:0')
    assert port > 0
    server.start()
    client = SandboxClient('127.0.0.1:'+str(port), timeout=2)
    channel = grpc.insecure_channel('127.0.0.1:'+str(port))
    config = OpenShellConfiguration('workspace-test', '/workspace', 'controlled-gateway', file_helper='python3', timeout_seconds=2)
    provider = OpenShellEnvironmentProvider(config, client=client, rpc=services.OpenShellStub(channel))
    manager = EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path/'env.sqlite'), providers={'openshell':provider})
    instance = manager.create('openshell', _peer.REFERENCE)
    flows = []
    def build(name):
        root = '/workspace/'+name
        roots = {k:root+'/'+k for k in ('home','cwd','profile')}
        descriptor = RuntimeProviderDescriptor('controlled', RUNTIME_PROVIDER_VERSION,
            {'environmentNamespace':'env','definitionId':'controlled','revision':'1'}, 'sha256:'+'a'*64,
            ('plan_preparation','prepare','start','connect','describe_access','stop','release'))
        provider_ref = {'environmentNamespace':'env','providerId':'controlled','generation':1,
            'contractVersion':RUNTIME_PROVIDER_VERSION,'implementationDigest':descriptor.implementation_digest}
        node = {'environmentNamespace':'env','nodeId':name,'generation':1}
        authority = Authority(provider_ref, node)
        evidence = AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'], start_authority=authority.continuation)
        records = UnitRecords(OperationJournal(tmp_path/(name+'.sqlite')), scope_authority=Scope(), native_evidence=evidence,
            verifier=authority, epoch_port=SimpleNamespace(current_epoch=lambda node:0), termination_evidence=evidence)
        evidence.attach_owner(records)
        manifest = {'schemaVersion':'1','harnessDefinitionRef':dict(descriptor.definition_ref),'declarations':[], 'metadata':{'unit':name}}
        revision = ProfileRevisionRef('env',name,1,content_digest(canonical_content(manifest,'env')))
        class Preparation:
            harness_id = 'controlled-acp'
            def prepare(self, roots):
                return PreparedHarness(self.harness_id, LaunchSpec.build(['controlled-acp'], home=roots['home'], cwd=roots['cwd']),
                    SessionBootstrap('fresh',roots['cwd']), ConfigurationResources('profile-dir',roots['profile'],False),
                    {'identity':self.harness_id,'version':'controlled-1','protocol':'acp/v1'})
        def materialize(agent, use, facts, snapshot):
            directory = use.files.ensure(name+'/profile')
            use.files.write_text(name+'/profile/settings.json', json.dumps(dict(snapshot['manifest']['metadata'])))
            return ConfigurationResources('profile-dir',directory,True)
        unit = UnitInstance(descriptor=descriptor, agent_id=name, profile_revision=revision,
            environment_instance=instance, environment_sharing=True, environment_reference={'environmentId':instance.identity},
            preparation=Preparation(), materializer=materialize, records=records, projection=evidence,
            verifier=authority, lease_port=ConnectionLeasePort(), termination_evidence=evidence, timeout=.3)
        plan = {'profileSnapshot':{'ref':encode_revision_ref(revision),'manifest':manifest},'context':{'nodeRef':node,'privateRootFacts':roots}}
        prepared = unit.prepare(plan, authority.issue('prepare'))
        unit.start(prepared, authority.issue('start'))
        result = SimpleNamespace(unit=unit, authority=authority, ref=prepared['unitRef'], records=records,
            record=unit.channel_factory.owned_record, use=unit.channel_factory.environment)
        flows.append(result)
        return result
    yield SimpleNamespace(peer=peer, instance=instance, build=build)
    for flow in flows:
        # Normal exits permit explicit release; unknown is deliberately held.
        if flow.record.entry._thread.is_alive():
            if flow.record.process.observe().state == 'running':
                flow.record.entry.run_process_operation(flow.record.channel.close_async(timeout=.3), timeout=3)
            flow.record.process.release()
            flow.record.entry.detach()
    client.close()
    channel.close()
    server.stop(0).wait(3)


def prompt(flow):
    if not hasattr(flow,"grant"):
        flow.grant=flow.unit.lease_port.grant(flow.ref)
    return flow.unit.prompt(flow.ref, flow.grant, prompt=[], timeout=2)


def test_two_units_independent_uses_session_material_and_release(remote):
    a, b = remote.build('a'), remote.build('b')
    assert a.use.identity != b.use.identity
    assert a.record.environment_identity == b.record.environment_identity == remote.instance.identity
    assert a.record.process.identity != b.record.process.identity
    assert a.record.entry.session_id != b.record.entry.session_id
    assert json.loads(a.use.files.read_text('a/profile/settings.json')) == {'unit':'a'}
    assert prompt(a)['originalSession'] == a.record.entry.session_id
    assert prompt(b)['originalSession'] == b.record.entry.session_id
    assert a.unit.stop(a.ref,a.authority.issue('stop'))['state'] == 'confirmed'
    assert a.record.process.observe().state == 'exited'
    assert a.unit.release(a.ref,a.authority.issue('release'))['state'] == 'confirmed'
    with pytest.raises(EnvironmentRefused):a.record.process.observe()
    assert remote.instance.snapshot.active_uses == 1
    assert prompt(b)['originalSession'] == b.record.entry.session_id
    assert not remote.peer.deleted and len(remote.peer.starts) == 2
    assert b.unit.stop(b.ref,b.authority.issue('stop'))['state'] == 'confirmed'
    assert b.unit.release(b.ref,b.authority.issue('release'))['state'] == 'confirmed'
    assert remote.instance.snapshot.active_uses == 0


@pytest.mark.parametrize('edge',['eof','timeout','cancel'])
def test_unknown_edges_hold_original_unit_without_affecting_second_use(remote, edge):
    a, b = remote.build('a'), remote.build('b')
    if edge == 'cancel':
        force = a.record.entry.run_process_operation(a.record.process.cancel(force=True),timeout=2)
        assert force.outcome == 'unsupported'
        soft = a.record.entry.run_process_operation(a.record.process.cancel(),timeout=2)
        assert soft.outcome == 'unknown'
    else:
        with pytest.raises((LostReceipt,RequestTimeout)):
            a.record.entry.command('controlled/eof' if edge=='eof' else 'controlled/silent',timeout=.1)
    if edge != 'timeout':
        assert a.record.process.observe().state == 'unknown'
        with pytest.raises(UnitLifecycleRefused,match='unknown'):
            a.unit.stop(a.ref,a.authority.issue('stop'))
        unit_record=a.records.owner_read_unit(a.ref['unitId'])
        assert a.records.owner_read_termination(unit_record.unit_ref,'stop')['state']=='unknown'
        with pytest.raises((UnitRecordsRefused,UnitLifecycleRefused)):
            a.unit.stop(a.ref,a.authority.issue('stop'))
        assert a.records.owner_read_termination(unit_record.unit_ref,'stop')['state']=='unknown'
        with pytest.raises(EnvironmentRefused):a.use.release()
    else:
        assert a.record.channel._unresolved
        assert len(a.record.channel._prepared_inflight)==1
        with pytest.raises(ConnectionLeaseRefused):prompt(a)
    assert prompt(b)['originalSession'] == b.record.entry.session_id
    assert len(remote.peer.starts) == 2 and not remote.peer.deleted
    assert b.unit.stop(b.ref,b.authority.issue('stop'))['state'] == 'confirmed'
    assert b.unit.release(b.ref,b.authority.issue('release'))['state'] == 'confirmed'
