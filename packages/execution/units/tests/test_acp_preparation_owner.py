"""Former Pi factory guarantees at the sole Unit channel owner; no child spawn."""
from pathlib import Path
import pytest
from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.preparation import PreparedHarness,ConfigurationResources,SessionBootstrap
from ordessa_units.sessions.acp_factory import AcpChannelFactory
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_environments import EnvironmentRefused
from test_unit_instance import Provider


def factory(tmp_path,protocol='acp/v1'):
    root=tmp_path/'private';events=[];environment=Provider(root,events);requests=[]
    acquire=environment.acquire
    def record_acquire(*a,**k):
        use=acquire(*a,**k)
        def capture(request):requests.append(request);raise EnvironmentRefused('recording owner never spawns')
        use.execution.start=capture
        return use
    environment.acquire=record_acquire
    spec=LaunchSpec.build(['/marker/pinned','--marker','雪'],cwd=str(root/'cwd'),home=str(root/'home'),
        extra_env={'MARKER_KEY':'unchanged-value','PATH':'/marker/path'})
    prepared=PreparedHarness('pi',spec,SessionBootstrap('fresh',spec.cwd),
        ConfigurationResources('pi-agent-dir',str(root/'piHome'),True),{'protocol':protocol})
    class Preparation:
        harness_id='pi'
        def prepare(self,roots):return prepared
    owner=AcpChannelFactory(environment_instance=environment,environment_sharing=True,
        environment_reference={'environmentId':environment.identity},preparation=Preparation(),
        materializer=None,agent_id='fixed-agent',profile_revision={'original':'revision'},session_id=None,timeout=2)
    return owner,environment,requests,prepared


def test_only_unit_owner_dispatches_the_exact_finished_argv_cwd_and_environment(tmp_path):
    owner,environment,requests,prepared=factory(tmp_path)
    try:
        assert owner.prepare({'marker':'roots'},{'action':'prepare','query':False},{}) .harness is prepared
        with pytest.raises(EnvironmentRefused,match='never spawns'):
            owner.open({'marker':'roots'},{'action':'start','query':False})
        assert len(requests)==1
        request=requests[0]
        assert request.argv==prepared.launch_spec.argv
        assert request.cwd==prepared.launch_spec.cwd
        assert dict(request.env)==dict(prepared.launch_spec.env)
        assert request.env['MARKER_KEY']=='unchanged-value' and request.env['PATH']=='/marker/path'
        assert environment.opens==1 and owner.owned_record is None
    finally:
        if owner.environment is not None:owner.environment.release()


def test_native_rpc_plan_cannot_reach_unit_spawn(tmp_path):
    owner,environment,requests,prepared=factory(tmp_path,protocol='pi-rpc/1')
    try:
        with pytest.raises(UnitLifecycleRefused,match='declared ACP'):
            owner.prepare({}, {'action':'prepare','query':False},{})
        assert requests==[] and owner.owned_record is None
    finally:
        if owner.environment is not None:owner.environment.release()


def test_missing_preparation_port_refuses_at_construction():
    with pytest.raises(UnitLifecycleRefused,match='preparation port'):
        AcpChannelFactory(environment_instance=None,environment_sharing=True,
            environment_reference={},preparation=object(),materializer=None,agent_id='fixed-agent',
            profile_revision={},session_id=None,timeout=2)
