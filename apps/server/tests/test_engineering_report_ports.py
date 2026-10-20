"""Original owner ports reach the public service builder unchanged."""
from types import SimpleNamespace

import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings import engineering_wire as wire


def test_report_ports_are_forwarded_without_interpreting_method(monkeypatch):
    seen={}
    def build(factory, ports):
        seen.update(vars(ports))
        return SimpleNamespace()
    monkeypatch.setattr(wire,'build_engineering_service',build)
    source,records=object(),object()
    query=lambda binding: binding
    review,consent=object(),object()
    ports=wire.EngineeringApplicationPorts(submission_report_source=source,execution_records=records,
        execution_query_factory=query,review_admission=review,conversation_admission=consent)
    bound=wire.EngineeringWireBinding(object(),object(),scope=Scope('r','p'),application_ports_factory=lambda *args:ports)
    assert seen['submission_report_source'] is source
    assert seen['execution_records'] is records and seen['execution_query_factory'] is query
    assert seen['review_admission'] is review and seen['conversation_admission'] is consent
    assert bound.ports is ports


def test_partial_report_ports_are_explicitly_unavailable():
    ports=wire.EngineeringApplicationPorts(submission_report_source=object())
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_SOURCE_UNAVAILABLE'):
        wire.EngineeringWireBinding(object(),object(),scope=Scope('r','p'),application_ports_factory=lambda *args:ports)


def test_unconfigured_report_does_not_change_existing_ports(monkeypatch):
    seen={}
    monkeypatch.setattr(wire,'build_engineering_service',lambda factory,ports: seen.update(vars(ports)))
    wire.EngineeringWireBinding(object(),object(),scope=Scope('r','p'))
    assert seen['submission_report_source'] is None
    assert seen['execution_records'] is None
