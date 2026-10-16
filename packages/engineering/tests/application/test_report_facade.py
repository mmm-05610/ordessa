"""Finite report wire/refusal contract; no production source or Grant is fabricated."""
import asyncio
import pytest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.api.service import EngineeringService, SUPPORTED_COMMANDS
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.contracts.errors import ApplicationError
from test_review_usecases import SyntheticAccess, _scope, _context


def test_public_report_contract_has_distinct_identity_and_pending_completion():
    operation='engineering.submissions.record_report'
    assert operation in SUPPORTED_COMMANDS
    schema=EngineeringService.input_schema(operation)
    assert schema['required']==['record'] and schema['additionalProperties'] is False
    descriptor=next(d for d in command_capabilities().capabilities if d.capability_id==operation)
    assert descriptor.interface_version=='1'
    assert descriptor.contract['workflow_outcomes']==['completed','rejected']
    assert descriptor.contract['completion']=='immutable_asserted_report_submitted_pending_review_not_accepted'


@pytest.mark.parametrize('access,error',[(None,'ACCESS_AUTHORITY_UNAVAILABLE'),
                                        (SyntheticAccess(),'SUBMISSION_REPORT_SOURCE_UNAVAILABLE')])
def test_default_report_wire_refuses_without_writing_or_dispatch(tmp_path,access,error):
    lib=EngineeringLibrary.create((tmp_path/'reports.sqlite').resolve(),library_id='report-wire-fixture',schema_version=14)
    try:
        facade=EngineeringService(SQLiteUoWFactory(lib),access)
        with pytest.raises(ApplicationError,match=error):
            asyncio.run(facade.execute('engineering.submissions.record_report',{'record':{}},_context(_scope(),'report-wire')))
        assert lib._connection.execute('SELECT count(*) FROM eng_submissions').fetchone()==(0,)
        assert lib._connection.execute('SELECT count(*) FROM eng_commands').fetchone()==(0,)
    finally: lib.close()
