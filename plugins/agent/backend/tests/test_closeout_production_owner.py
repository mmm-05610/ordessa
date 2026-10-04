from types import SimpleNamespace
import pytest
from ordessa_agent.plugin import AgentDomainPlugin

def test_failed_atomic_observer_attachment_removes_callback_before_later_intent():
    from ordessa_agent.owners import ConfigOwner
    owner = ConfigOwner('trusted:S')
    received = []
    def broken(snapshot):
        received.append(snapshot.revision)
        raise RuntimeError('consumer cannot attach')
    with pytest.raises(RuntimeError, match='consumer cannot attach'):
        owner.attach_observer(broken)
    owner.submit_operation({'model':'M1'}, 'observer-regression')
    assert received == [0]
    assert owner.snapshot().revision == 1


def methods(plugin, root):
    return {m.method_id:m.handler for m in plugin.build(SimpleNamespace(data_root=root, ports={})).methods}


def test_production_owner_rejects_claimed_acceptance_without_native_submit_port(tmp_path):
    handlers=methods(AgentDomainPlugin(),tmp_path)
    draft=handlers['agent.session.resolve']({'location':{
        'kind':'draft','draftId':'unbound-draft','connectionId':'fixture','contextRevision':1,
    }})
    with pytest.raises(Exception, match='CAPABILITY_UNSUPPORTED|unsupported|unavailable'):
        handlers['agent.submitInput']({'target':draft['target'],'draftRevision':1,
                                       'capture':{'outcome':'accepted'}})


def test_production_targets_are_resolved_by_trusted_binding_not_frontend_claim(tmp_path):
    handlers=methods(AgentDomainPlugin(),tmp_path)
    with pytest.raises(Exception, match='AUTHORIZATION|unverified|binding'):
        handlers['agent.config.submitOperation']({'target':'session:forged','patch':{'model':'M1'}})


def test_two_transport_clients_share_backend_revision_and_omitted_fields(tmp_path):
    plugin=AgentDomainPlugin(target_resolver=lambda target: target if target=='trusted:S' else None)
    first=methods(plugin,tmp_path); second=methods(plugin,tmp_path)
    first['agent.config.submitOperation']({'target':'trusted:S','patch':{'model':'M1','prompt':'A'}})
    second['agent.config.submitOperation']({'target':'trusted:S','patch':{'model':'M2'}})
    snap=first['agent.config.read']({'target':'trusted:S'})
    assert snap['resolved']=={'model':'M2','prompt':'A'}
    second['agent.config.submitOperation']({'target':'trusted:S','patch':{'prompt':'B'}})
    assert first['agent.config.read']({'target':'trusted:S'})['resolved']=={'model':'M2','prompt':'B'}
    first['agent.config.submitOperation']({'target':'trusted:S','patch':{'model':'M1','prompt':'A'}})
    assert second['agent.config.read']({'target':'trusted:S'})['revision']==4


def test_restart_retains_config_operations_and_nested_input_cannot_mutate_owner(tmp_path):
    patch={'model':{'provider':'fixture','id':'M1'}}
    plugin=AgentDomainPlugin(target_resolver=lambda target:target)
    handlers=methods(plugin,tmp_path)
    handlers['agent.config.submitOperation']({'target':'trusted:S','patch':patch})
    patch['model']['id']='changed'
    assert handlers['agent.config.read']({'target':'trusted:S'})['resolved']['model']['id']=='M1'
    plugin.close()
    reopened=AgentDomainPlugin(target_resolver=lambda target:target)
    try:
        snap=methods(reopened,tmp_path)['agent.config.read']({'target':'trusted:S'})
        assert snap['revision']==1
        assert snap['resolved']['model']['id']=='M1'
    finally:reopened.close()


def test_production_draft_target_is_backend_minted_and_reopened_without_native_creation(tmp_path):
    plugin=AgentDomainPlugin()
    handlers=methods(plugin,tmp_path)
    location={'kind':'draft','draftId':'draft-one','connectionId':'fixture','contextRevision':1}
    result=handlers['agent.session.resolve']({'location':location})
    assert result['target'] != location['draftId']
    handlers['agent.config.submitOperation']({'target':result['target'],'patch':{'prompt':'A'}})
    plugin.close()
    reopened=AgentDomainPlugin()
    try:
        next_handlers=methods(reopened,tmp_path)
        restored=next_handlers['agent.session.resolve']({'location':location})
        assert restored['target']==result['target']
        assert next_handlers['agent.config.read']({'target':restored['target']})['revision']==1
        with pytest.raises(Exception, match='unavailable|unsupported'):
            next_handlers['agent.config.prepare']({'target':restored['target'],'revision':1})
    finally:reopened.close()
