"""Actual Server/CoreRegistry + three independent providers; no native IO/model."""
import importlib
from types import SimpleNamespace

import pytest
from ordessa_environment_api import GuaranteeUnavailableError
from pacthold.agents.public import agent_services
from test_agent_deployment import deployment_module, fingerprint

FAMILIES = [('codex', 'ordessa_harness_codex', 'Codex'),
            ('pi', 'ordessa_harness_pi', 'Pi'),
            ('claude-code', 'ordessa_harness_claude_code', 'ClaudeCode')]


def plugin(family, module, prefix, calls, *, foreign=False):
    runtime_class = getattr(importlib.import_module(module + '.provider'), prefix + 'RuntimeProvider')
    plugin_class = getattr(importlib.import_module(module + '.server_plugin'), prefix + 'ServerPlugin')
    def factory(environment, owner_view=None):
        calls.append(environment.value)
        return runtime_class(definition_ref={'environmentNamespace': 'foreign' if foreign else environment.value,
            'definitionId': family, 'revision': '1'}, implementation_digest='sha256:' + 'b' * 64)
    return plugin_class(factory)


def test_three_independent_server_owners_share_registry_and_restart_identity(tmp_path, monkeypatch):
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('no native process'))
    deployment = deployment_module()
    calls = []
    selected = tuple(plugin(*family, calls) for family in FAMILIES)
    config = deployment.AgentServiceConfiguration(tmp_path / 'server', agent_contract_version='agent-assembly/2')
    runtime = deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
        agent_contract_version='agent-assembly/2', provider_plugins=selected).build_runtime(config)
    identities = []
    refs = []
    try:
        for _ in range(2):
            runtime.start()
            env = runtime.core_binding.environment
            identities.append(env.environment_id)
            assert set(runtime.plugin_host.active_ids()) == {'codex', 'pi', 'claude-code'}
            assert set(env.registry_snapshot.agent_runtime_provider_ids) == {'codex', 'pi', 'claude'}
            assert env.registry_snapshot.execution_provider_ids == ()
            views = agent_services(env).providers.list()
            refs.append({row['providerRef']['providerId']: row['providerRef'] for row in views})
            assert len(views) == 3
            assert all('start' not in row['descriptor']['supportedMethods'] for row in views)
            result = runtime.wire.dispatch('agents.providers.list', {})
            assert result == {'providers': list(views)}
            caps = runtime.wire.dispatch('agents.capabilities', {})
            assert caps['supports']['nodePreparation'] is False
            assert caps['supports']['configurationManagement'] is False
            runtime.stop()
            assert env.closed if hasattr(env, 'closed') else env._closed
            assert runtime.plugin_host.active_ids() == ()
        assert identities[0] == identities[1]
        assert calls == [identities[0]] * 6
        assert all(refs[1][family]['generation'] > refs[0][family]['generation'] for family in refs[0])
    finally:
        runtime.stop()


@pytest.mark.parametrize('family,module,prefix', FAMILIES)
def test_missing_binding_refuses_before_factory(family, module, prefix):
    calls = []
    selected = plugin(family, module, prefix, calls)
    with pytest.raises(GuaranteeUnavailableError):
        selected.build(SimpleNamespace(ports={}))
    assert calls == []


@pytest.mark.parametrize('family,module,prefix', FAMILIES)
def test_foreign_provider_rolls_back_host_enablement_and_closes_root(tmp_path, family, module, prefix):
    deployment = deployment_module()
    calls = []
    selected = (plugin(family, module, prefix, calls, foreign=True),)
    config = deployment.AgentServiceConfiguration(tmp_path / 'server', agent_contract_version='agent-assembly/2')
    with pytest.raises(GuaranteeUnavailableError):
        deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
            agent_contract_version='agent-assembly/2', provider_plugins=selected).build_runtime(config)
    assert len(calls) == 1
    # A failure must release the same owned root, not leak a competing store.
    replacement = deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
        agent_contract_version='agent-assembly/2').build_runtime(config)
    try:
        replacement.start()
        assert replacement.core_binding.environment.registry_snapshot.agent_runtime_provider_ids == ()
    finally: replacement.stop()


@pytest.mark.parametrize('family,module,prefix', FAMILIES)
def test_wrapper_rejects_another_family_before_contributing(family, module, prefix):
    from ordessa_environment_api import EnvironmentId
    wrong_module, wrong_prefix = ('ordessa_harness_pi', 'Pi') if family != 'pi' else ('ordessa_harness_codex', 'Codex')
    wrong = getattr(importlib.import_module(wrong_module + '.provider'), wrong_prefix + 'RuntimeProvider')
    wrapper = getattr(importlib.import_module(module + '.server_plugin'), prefix + 'ServerPlugin')
    selected = wrapper(lambda env, owner_view=None: wrong(definition_ref={'environmentNamespace': env.value,
        'definitionId': 'wrong', 'revision': '1'}, implementation_digest='sha256:' + 'b' * 64))
    with pytest.raises(GuaranteeUnavailableError):
        selected.build(SimpleNamespace(ports={'core.binding': SimpleNamespace(
            environment=SimpleNamespace(environment_id='test'))}))


def test_provider_selection_requires_v2_and_explicit_tuple(tmp_path):
    deployment = deployment_module()
    calls = []
    selected = plugin(*FAMILIES[0], calls)
    with pytest.raises(GuaranteeUnavailableError):
        deployment.AgentToolsDeployment(fingerprint_port=fingerprint(), provider_plugins=(selected,))
    with pytest.raises(TypeError):
        deployment.AgentToolsDeployment(fingerprint_port=fingerprint(), agent_contract_version='agent-assembly/2',
            provider_plugins=[selected])
    assert calls == [] and list(tmp_path.iterdir()) == []


def test_duplicate_core_provider_rolls_back_all_selected_owners(tmp_path):
    from server_plugin_api import ServerPluginDescriptor
    from pacthold.core.errors import RegistrationConflictError
    deployment = deployment_module()
    calls = []
    first = plugin(*FAMILIES[0], calls)
    class OtherOwner(type(first)):
        def descriptor(self):
            return ServerPluginDescriptor('controlled-other', 'Counterexample duplicate provider', '0.1.0a1')
    second = OtherOwner(first._factory)
    config = deployment.AgentServiceConfiguration(tmp_path / 'server', agent_contract_version='agent-assembly/2')
    with pytest.raises(RegistrationConflictError):
        deployment.AgentToolsDeployment(fingerprint_port=fingerprint(), agent_contract_version='agent-assembly/2',
            provider_plugins=(first, second)).build_runtime(config)
    assert len(calls) == 2 and calls[0] == calls[1]
    clean = deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
        agent_contract_version='agent-assembly/2').build_runtime(config)
    try:
        clean.start()
        assert clean.core_binding.environment.registry_snapshot.agent_runtime_provider_ids == ()
    finally: clean.stop()


def test_first_round_has_three_owners_and_no_native_authority(tmp_path, monkeypatch):
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('no native process'))
    deployment = deployment_module()
    calls = []
    selected = tuple(plugin(*family, calls) for family in FAMILIES)
    config = deployment.AgentServiceConfiguration(tmp_path / 'server', agent_contract_version='agent-assembly/2')
    runtime = deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
        agent_contract_version='agent-assembly/2', provider_plugins=selected).build_runtime(config)
    try:
        runtime.start()
        env = runtime.core_binding.environment
        views = runtime.wire.dispatch('agents.providers.list', {})['providers']
        assert len(views) == 3 and set(runtime.plugin_host.active_ids()) == {'codex', 'pi', 'claude-code'}
        assert calls == [env.environment_id] * 3
        assert env.registry_snapshot.execution_provider_ids == ()
        assert all('start' not in row['descriptor']['supportedMethods'] for row in views)
        for row in views:
            assert row['providerRef']['ownerActivationRef']['pluginId'] in {'codex', 'pi', 'claude-code'}
        runtime.plugin_host.deactivate('codex')
        assert {row['providerRef']['providerId'] for row in agent_services(env).providers.list()} == {'pi', 'claude'}
    finally: runtime.stop()


def test_existing_root_refuses_provider_reactivation_before_factory(tmp_path):
    deployment = deployment_module()
    config = deployment.AgentServiceConfiguration(tmp_path / 'server', agent_contract_version='agent-assembly/2')
    empty = deployment.AgentToolsDeployment(fingerprint_port=fingerprint(),
        agent_contract_version='agent-assembly/2').build_runtime(config)
    empty.start(); empty.stop()
    # Simulate a historical root created before durable generation evidence
    # existed. The refusal target is the missing trusted basis, not root age:
    # roots born with the basis may reactivate providers across restarts.
    import sqlite3 as _sqlite3
    from pacthold.core.activation_generation import (
        ACTIVATION_SEED_NAMESPACE as _NS, ACTIVATION_SEED_RECORD as _RID)
    core = tmp_path / 'server' / 'state' / 'core.sqlite'
    with _sqlite3.connect(core) as db:
        db.execute("DELETE FROM env_domain_records WHERE environment IS NOT NULL "
                   "AND namespace=? AND record_id=?", (_NS, _RID))
        db.commit()
    calls = []
    with pytest.raises(GuaranteeUnavailableError, match='generation unavailable'):
        deployment.AgentToolsDeployment(fingerprint_port=fingerprint(), agent_contract_version='agent-assembly/2',
            provider_plugins=(plugin(*FAMILIES[0], calls),)).build_runtime(config)
    assert calls == []
