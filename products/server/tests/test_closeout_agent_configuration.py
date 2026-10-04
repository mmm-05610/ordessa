"""Production assembly/wire controlled configuration authority regressions."""
import pytest
from ordessa_server_product.composition import create_composition
from test_native_model_turn_composition import runtime_at, controlled_native, bind_native


def test_default_product_two_wire_controls_share_backend_draft_without_native_creation(tmp_path):
    runtime=create_composition().default_runtime(tmp_path/'data')
    try:
        runtime.start()
        wire=runtime.wire
        target=wire.dispatch('agent.session.resolve', {'location':{'kind':'draft','draftId':'D','connectionId':'C'}})['target']
        for patch in [{'model':'M1','prompt':'A'}, {'model':'M2'}, {'prompt':'B'}, {'model':'M1','prompt':'A'}]:
            wire.dispatch('agent.config.submitOperation', {'target':target, 'patch':patch})
        snapshot=wire.dispatch('agent.config.read',{'target':target})
        assert snapshot['resolved']=={'model':'M1','prompt':'A'}
        assert snapshot['revision']==4
        assert snapshot['observedEvidence']=='unset'
    finally:runtime.stop()


@pytest.mark.parametrize('include_profile',[True,False])
def test_native_product_shared_agent_owner_uses_verified_native_binding(monkeypatch,tmp_path,include_profile):
    runtime=runtime_at(tmp_path,include_profile=include_profile)
    try:
        runtime.start()
        controlled=controlled_native(monkeypatch,runtime)
        binding=bind_native(controlled)
        result=runtime.wire.dispatch('agent.session.resolve',{'location':{
            'kind':'session','connectionId':'connection','sessionId':'s-1'}})
        target=result['target']
        assert target==binding.snapshot.target.session_id
        runtime.wire.dispatch('agent.config.submitOperation',{'target':target,'patch':{'model':'M1','prompt':'A'}})
        runtime.wire.dispatch('agent.config.submitOperation',{'target':target,'patch':{'model':'M2'}})
        assert runtime.wire.dispatch('agent.config.read',{'target':target})['resolved']=={'model':'M2','prompt':'A'}
        assert controlled.channel.operations==[] # selection does not apply/stop/output
    finally:runtime.stop()
