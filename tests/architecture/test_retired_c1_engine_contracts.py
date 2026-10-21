"""Unused Kernel execution-plan/runtime model contracts cannot reappear."""
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOVED = ('dtos', 'plan', 'protocols', 'store_port', 'descriptors', 'enums')


def absent(module):
    try:
        return find_spec(module) is None
    except ModuleNotFoundError as error:
        if error.name and (module == error.name or module.startswith(error.name + '.')):
            return True
        raise


def test_entire_legacy_distribution_and_source_are_absent():
    from importlib.metadata import distribution, PackageNotFoundError
    import pytest
    assert not (ROOT / 'packages/interfaces/execution/c1-api').exists()
    assert absent('ordessa_execution_api')
    with pytest.raises(PackageNotFoundError):
        distribution('ordessa-execution-api')


def test_unused_engine_contract_files_and_installed_entries_are_retired():
    for name in REMOVED:
        assert not (ROOT / 'packages/interfaces/execution/c1-api/src/ordessa_execution_api/c1' / f'{name}.py').exists()
        assert absent(f'ordessa_execution_api.c1.{name}')


def test_old_execution_state_machine_exports_are_absent():
    for name in ('ContractWiringPending', 'RuntimeClosedError', 'OwnerBusyError'):
        assert absent('ordessa_execution_api.c1.errors')
    from ordessa_units.definitions.materials import ReconcileSupport
    assert ReconcileSupport.SUPPORTED.value == 'supported'
    assert ReconcileSupport.UNSUPPORTED.value == 'unsupported'
    assert ReconcileSupport.__module__ == 'ordessa_units.definitions.materials'


def test_adopted_provider_definitions_have_one_real_owner():
    assert not (ROOT / 'packages/interfaces/execution/c1-api/src/ordessa_execution_api/agents').exists()
    assert absent('ordessa_execution_api.agents')
    from ordessa_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor
    from ordessa_agents.harness.definitions.configuration_providers import ConfigurationRoute
    assert RuntimeProviderDescriptor.__module__ == 'ordessa_agents.harness.definitions.runtime_providers'
    assert ConfigurationRoute.__module__ == 'ordessa_agents.harness.definitions.configuration_providers'


def test_harness_declarations_and_native_evidence_have_one_real_owner():
    assert not (ROOT / 'packages/interfaces/execution/c1-api/src/ordessa_execution_api/harness').exists()
    assert absent('ordessa_execution_api.harness')
    from ordessa_agents.harness.definitions import LaunchRequest, NativeEvidence
    assert LaunchRequest.__module__ == 'ordessa_agents.harness.definitions.contracts'
    assert NativeEvidence.__module__ == 'ordessa_agents.harness.definitions.native_evidence'
    assert (ROOT / 'packages/execution/agents/src/ordessa_agents/harness/definitions/ACP.md').is_file()
