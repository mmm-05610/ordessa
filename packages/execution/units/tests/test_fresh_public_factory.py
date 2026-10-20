"""Public composition retains the original owners, start gate and borrowed Use."""
import pytest

from test_public_unit_api import public_units
from ordessa_units.assembly import build_fresh_acp_unit_factory
from ordessa_units.admission.owner_ports import AgentProviderView
from ordessa_units.admission.owner_selection import AgentOwnerUnavailable
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_units.definitions.admission_identity import AdmissionNamespace


def selected_factory(m, *, process_binding_factory=None):
    # The existing controlled composition already selects these concrete ports;
    # they are forwarded into the public owner builder without a new authority.
    plan = m.bindings.resolve_plan(m.spec, m.authorization('selected'))
    reference = m.original._factory(plan)
    return build_fresh_acp_unit_factory(agent_id=m.spec.agent_id,
        profile_revision=m.spec.profile_revision, descriptor=reference.descriptor,
        environment_instance=m.environments,
        environment_reference=m.spec.environment_reference, environment_sharing=True,
        preparation=reference.channel_factory.preparation,
        materializer=reference.channel_factory.materializer,
        evidence=m.records.native_evidence, lease_port=ConnectionLeasePort(), timeout=2,
        process_binding_factory=process_binding_factory)


def test_public_factory_builds_same_owner_units_and_process_binding_gates_original_start(public_units):
    m = public_units
    bindings = []
    class Binding:
        def __init__(self, instance, agent_id, sharing):
            assert instance is m.environments and agent_id == m.spec.agent_id and sharing
            self.capability = instance
            self.events = []
        def attach(self, unit):
            self.unit = unit
            self.events.append('attached')
        def fix_start(self, prepared, context):
            assert prepared is self.unit.prepared_unit
            assert context.facts['action'] == 'start'
            self.events.append('original-start')
        def close(self):
            self.events.append('closed')
    def binding_factory(*args):
        binding = Binding(*args); bindings.append(binding); return binding
    factory = selected_factory(m, process_binding_factory=binding_factory)
    assert m.events.count('spawn') == 0 and bindings == []
    def create(plan):
        unit = factory.create_instance(AdmissionNamespace('env'), plan,
                                      AgentProviderView(m.records, m.records.verifier))
        m.instances.append(unit)
        return unit
    m.original._factory = create
    a = m.manager.create(m.spec, m.authorization('factory-a'))
    b = m.manager.create(m.spec, m.authorization('factory-b'))
    assert a._instance.records is b._instance.records is m.records
    assert a._instance._verifier is b._instance._verifier is m.records.verifier
    assert bindings[0] is not bindings[1]
    assert [binding.events for binding in bindings] == [['attached', 'original-start']] * 2
    assert m.environments.instance.snapshot.active_uses == 2
    assert a.close(m.authorization('factory-a'))['state'] == 'confirmed'
    assert bindings[0].events[-1] == 'closed'
    assert bindings[1].events == ['attached', 'original-start']
    assert m.environments.instance.snapshot.active_uses == 1
    assert b.close(m.authorization('factory-b'))['state'] == 'confirmed'
    assert m.environments.instance.snapshot.active_uses == 0


def test_public_factory_refuses_substituted_original_view_before_environment_effects(public_units):
    m = public_units
    factory = selected_factory(m)
    plan = m.bindings.resolve_plan(m.spec, m.authorization('refused'))
    with pytest.raises(AgentOwnerUnavailable):
        factory.create_instance(AdmissionNamespace('env'), plan,
                                AgentProviderView(m.records, object()))
    with pytest.raises(AgentOwnerUnavailable):
        factory.create_instance(AdmissionNamespace('other'), plan,
                                AgentProviderView(m.records, m.records.verifier))
    assert m.events.count('spawn') == 0
    assert m.environments.instance.snapshot.active_uses == 0
