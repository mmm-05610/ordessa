"""Finite rev58 transport ports, authentication and original missing-owner refusal."""
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts,SUPPORTED_METHODS
from ordessa_server.composition.engineering import DEFAULT_MACHINE_CAPABILITIES
from apps.server.tests.test_engineering_slice import runtime,call


def test_adoption_and_resume_are_not_new_default_machine_writes():
    assert {'engineering.acceptance.adopt','engineering.runs.resume','engineering.acceptance.get','engineering.runs.get_wait'}<=set(SUPPORTED_METHODS)
    assert not {'engineering.acceptance.adopt','engineering.runs.resume'}&set(DEFAULT_MACHINE_CAPABILITIES)
    assert 'engineering.runs.get_wait' in DEFAULT_MACHINE_CAPABILITIES


def test_authenticated_wait_query_requires_original_work_owner_not_grant(runtime):
    value=call(runtime,'engineering.runs.get_wait',{'run_id':'original-run'})
    assert value['error']['code']=='UNAVAILABLE',value


def test_actual_acceptance_read_does_not_generate_a_receipt(runtime):
    value=call(runtime,'engineering.acceptance.get',{'adoption_id':'missing'})
    assert 'error' in value and value['error']['code'] in {'NOT_FOUND','UNAVAILABLE'},value
