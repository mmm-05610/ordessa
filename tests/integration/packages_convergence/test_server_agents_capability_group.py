"""The default Server product publishes the Agent instance and native parts.

One real product assembly over a temporary data root: the published operation
ids, the exact capability groups and the default grant set. No model is called
and no Agent is started.
"""
from __future__ import annotations

from pathlib import Path

from ordessa_interfaces.system_access.queries import list_operations
from ordessa_server_product.composition import create_composition
from ordessa_server_product.service_configuration import (
    AGENT_NATIVE_OPERATIONS,
    AGENT_OPERATIONS,
    default_service_configuration,
)

INSTANCE_OPERATIONS = frozenset({
    'agents.start', 'agents.get', 'agents.stop', 'agents.detach',
    'agents.reconcile', 'agents.prompt', 'agents.query', 'agents.cancel',
})
NATIVE_OPERATIONS = frozenset({
    'agents.native.freeze', 'agents.native.recorded', 'agents.native.query',
})


def test_the_default_product_publishes_the_instance_and_native_operations(tmp_path):
    composition = create_composition()
    runtime = composition.prepare_default_http_runtime()(tmp_path / 'root')
    try:
        published = {entry['id'] for entry in list_operations(runtime.host.registry)['operations']}
        assert INSTANCE_OPERATIONS <= published
        assert NATIVE_OPERATIONS <= published
        assert 'environments.providers' in published and 'decisions.run' in published
        groups = {descriptor.id for descriptor in runtime.host.registry.capabilities.values()}
        assert groups == {'agents', 'environments', 'decisions'}
    finally:
        runtime.close()


def test_the_default_grants_name_every_agent_operation():
    configuration = default_service_configuration(Path('/tmp/ordessa-grant-scope'),
                                                  harness_allowlist=())
    assert set(AGENT_OPERATIONS) <= set(configuration.access.grants)
    assert set(AGENT_NATIVE_OPERATIONS) <= set(AGENT_OPERATIONS)
    assert configuration.capabilities == ('agents', 'environments', 'decisions')
