"""Receiving identity only; real assignment/authority qualification is owner-side."""
from types import SimpleNamespace

from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings import engineering_wire as wire


def test_original_assignment_instance_reaches_same_service_builder(monkeypatch):
    factory, authority, access, assignments = object(), object(), object(), object()
    observed = []
    service = SimpleNamespace()

    def build(actual_factory, ports):
        observed.append((actual_factory, ports))
        return service

    monkeypatch.setattr(wire, "EngineeringCommandAccess", lambda selected: access
                        if selected is authority else None)
    monkeypatch.setattr(wire, "build_engineering_service", build)
    ports = wire.EngineeringApplicationPorts(reviewer_assignments=assignments)
    binding = wire.EngineeringWireBinding(factory, authority,
        scope=Scope("realm", "project"), application_ports_factory=lambda *_: ports)

    assert binding.service is service
    assert binding.ports is ports
    assert len(observed) == 1
    assert observed[0][0] is factory
    assert observed[0][1].access is access
    assert observed[0][1].reviewer_assignments is assignments


def test_absent_assignment_port_does_not_create_one(monkeypatch):
    observed = []
    monkeypatch.setattr(wire, "build_engineering_service", lambda factory, ports:
                        observed.append(ports) or SimpleNamespace())
    wire.EngineeringWireBinding(object(), object(), scope=Scope("realm", "project"))
    assert observed[0].reviewer_assignments is None
