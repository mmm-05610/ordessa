"""Negative Node admission on original SQLite; no fake Manager effect receipt.

This group does not qualify a native stop or complete Manager assembly.
"""
from types import SimpleNamespace
import pytest
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_units.management.manager import UnitManager
from test_manager_node_joint import joint, managed_lifecycle


@pytest.fixture
def lifecycle(managed_lifecycle):
    # Genuine published Node and original Unit; deliberately unbind the
    # optional Manager to exercise refusal before any lifecycle reserve.
    managed_lifecycle[0]._unit_manager = None
    return managed_lifecycle


def test_missing_manager_never_dispatches_legacy_runtime_or_reserves(lifecycle):
    coordinator, _, provider, node_ref, _, _, store, request, _, _ = lifecycle
    assert coordinator.capabilities() == {
        'nodeLifecycle': False, 'supportedLifecycleActions': []}
    with pytest.raises(UnitGuaranteeUnavailable, match='Unit Manager'):
        coordinator.stop(request, node_ref, {})
    assert store.read_operation(request) is None
    assert provider.lifecycle_calls == []


@pytest.mark.parametrize('action', ['release', 'recover'])
def test_unqualified_actions_refuse_without_legacy_dispatch(lifecycle, action):
    coordinator, _, provider, node_ref, _, _, store, request, _, _ = lifecycle
    expected = 'Unit Manager' if action == 'release' else 'not admitted'
    with pytest.raises(UnitGuaranteeUnavailable, match=expected):
        getattr(coordinator, action)(request, node_ref, {})
    assert store.read_operation(request) is None
    assert provider.lifecycle_calls == []


class BoundIssuer:
    def __init__(self, store): self._store = store
    def verify(self, *args): raise AssertionError('binding must never issue/consume')


def bound_bundle():
    store = object()
    issuer = BoundIssuer(store)
    verifier = SimpleNamespace(_verify=issuer.verify)
    records = SimpleNamespace(verifier=verifier)
    manager = UnitManager(create_instance=lambda _: (_ for _ in ()).throw(
        AssertionError('binding must never create')), records=records, verifier=verifier)
    bundle = AgentOwnerPorts(issuer, AgentProviderView(records, verifier), unit_manager=manager)
    return SimpleNamespace(_store=store), bundle, manager


def test_bundle_accepts_same_manager_records_verifier_without_creating_unit():
    environment, bundle, manager = bound_bundle()
    bundle.validate_for(environment)
    assert manager.list() == ()


@pytest.mark.parametrize('field', ['records', 'verifier'])
def test_bundle_refuses_foreign_manager_owner(field):
    environment, bundle, manager = bound_bundle()
    setattr(manager, field, object())
    with pytest.raises(ValueError, match='Unit Manager'):
        bundle.validate_for(environment)


def test_bundle_refuses_callable_impostor_manager():
    environment, bundle, manager = bound_bundle()
    impostor = SimpleNamespace(records=manager.records, verifier=manager.verifier)
    other = AgentOwnerPorts(bundle.issuer, bundle.provider_view, unit_manager=impostor)
    with pytest.raises(ValueError, match='Unit Manager'):
        other.validate_for(environment)
