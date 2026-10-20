"""Wire projection only: owner action lists stay out of boolean supports."""
from types import SimpleNamespace
import pytest
from ordessa_system_access_bindings import agents
from ordessa_system_access_client import WireClient
from server_plugin_api import WireError


def registry(monkeypatch, actions):
    services = SimpleNamespace(
        profiles=SimpleNamespace(environment_namespace='controlled-projection',
            capabilities=lambda: {'profileCatalog':False,'nodes':False,'managedInput':False}),
        configuration=SimpleNamespace(capabilities=lambda:{'configurationManagement':False}),
        assembly=SimpleNamespace(capabilities=lambda:{'nodePreparation':False}),
        lifecycle=SimpleNamespace(capabilities=lambda:{'nodeLifecycle':True,
            'supportedLifecycleActions':actions}))
    monkeypatch.setattr(agents,'unit_services',lambda _:services)
    return {d.method_id:d.handler for d in agents.agent_core_methods(lambda:object(),
        contract_version='agent-assembly/3')}


def test_stop_release_projection_negotiates_without_advertising_recover(monkeypatch):
    methods=registry(monkeypatch,['stop','release'])
    result=methods['agents.capabilities']({})
    assert all(type(v) is bool for v in result['supports'].values())
    assert 'supportedLifecycleActions' not in result['supports']
    assert {'agents.nodes.stop','agents.nodes.release'} <= set(result['supportedMethods'])
    assert 'agents.nodes.recover' not in result['supportedMethods']
    # Exercise the actual strict client parser without transport/network.
    client=WireClient.__new__(WireClient)
    client.service=SimpleNamespace(token='controlled-projection-private-token')
    client.core_call=lambda *args:result
    negotiated=client.negotiate('projection-only')
    assert negotiated['supports']['nodeLifecycle'] is True
    assert 'agents.nodes.recover' not in client.supported_methods


def test_unadvertised_recover_refuses_before_owner_dispatch(monkeypatch):
    methods=registry(monkeypatch,['stop','release'])
    with pytest.raises(WireError) as raised:
        methods['agents.nodes.recover']({'nodeRef':{'environmentNamespace':'controlled-projection',
            'instanceId':'node','generation':1},'requestId':'controlled-refusal','preconditions':{}})
    assert raised.value.family=='CAPABILITY_UNSUPPORTED'


@pytest.mark.parametrize('actions',[['stop','stop'],['relaunch'],'stop'])
def test_invalid_owner_actions_fail_closed(monkeypatch,actions):
    methods=registry(monkeypatch,actions)
    with pytest.raises(WireError) as raised:
        methods['agents.capabilities']({})
    assert raised.value.family=='CAPABILITY_UNSUPPORTED'
