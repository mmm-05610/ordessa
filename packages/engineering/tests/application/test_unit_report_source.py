"""Real loader/snapshot/control/blob with explicit nonproduction Unit/binding fixtures."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import runpy
import pytest
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.application.usecases.changes.report_source import MethodUnitReportSource, DeclaredUnitReportBinding
from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.common.models.values import Digest
from test_method_control_admission import TestManagement
from test_review_usecases import SyntheticAccess
from test_execution_capture import ExplicitRecordsFixture, UNIT, PROMPT, _invocation


@pytest.fixture
def env(tmp_path):
    helpers=runpy.run_path(str(Path(__file__).parents[1]/'persistence/test_method_content.py'))
    lib=EngineeringLibrary.create((tmp_path/'reports.sqlite').resolve(),library_id='report-source-test',schema_version=14)
    try:
        method,snapshot=helpers['_publish_document_method'](lib,tmp_path/'method')
        factory=SQLiteUoWFactory(lib);blobs=SQLiteBlobStore(lib)
        context=CommandContext(helpers['SCOPE'],'fixture-principal',helpers['ACTOR'],'report','2026-10-12T12:00:00.000000Z','report-trace')
        controls=SQLiteMethodControl(factory,SQLiteSnapshotStore(lib))
        MethodUseCases(factory,SyntheticAccess(),SQLiteSnapshotStore(lib),TestManagement()).adopt(method,context,expected_version=0)
        resource=next(r for r in snapshot.resources if r.resource_id=='document.output')
        schema=ExactMethodResourceRef(method,resource.logical_path,Digest('sha256',resource.digest),resource.resource_id)
        content=MethodContent.from_value(schema,{'answer':'executor asserted result'})
        execution=object();outputs=()
        record=SimpleNamespace(method_content=content,execution_ref=SimpleNamespace(operation_ref='op-1',prompt_input_digest=Digest('sha256',PROMPT[7:])),output_refs=outputs)
        class Binding:
            @contextmanager
            def guard_report_binding(self,*args):
                yield DeclaredUnitReportBinding('output',record.execution_ref,outputs)
        binding=Binding();binding.factory=factory
        source=MethodUnitReportSource(factory,controls,blobs,binding)
        def capture(text,state='completed'):
            reader=ExplicitRecordsFixture(state)
            reader.receipt['summary']={'text':text,'successfulRpcResponse':state=='completed','modelQualityVerified':False}
            return capture_execution_observation(reader,blobs,authority_id=factory.authority_id,unit_ref=UNIT,operation_ref='op-1',expected_prompt_digest=PROMPT,query_invocation=_invocation(reader))
        yield context,method,record,source,capture
    finally:
        lib.close()


def test_exact_method_schema_and_actual_report_text_are_admitted_as_asserted(env):
    ctx,method,record,source,capture=env
    captured=capture(record.method_content.value_bytes.decode())
    package=SimpleNamespace(payload=SimpleNamespace(method_ref=method))
    with source.guard_report(ctx,package,record,captured) as admitted:
        assert admitted.report_schema_ref==record.method_content.schema_ref
        assert admitted.captured_observation_ref==captured.blob_ref
        assert admitted.execution_operation_ref=='op-1'
        assert not hasattr(admitted,'accepted')


@pytest.mark.parametrize('text,state,error',[
    ('{"answer":"changed"}','completed','SUBMISSION_REPORT_OUTPUT_MISMATCH'),
    ('not JSON','completed','SUBMISSION_REPORT_OUTPUT_INVALID'),
    ('{"answer":"executor asserted result"}','unknown','SUBMISSION_REPORT_OUTPUT_UNAVAILABLE'),
])
def test_wrong_actual_output_or_unknown_never_admitted(env,text,state,error):
    ctx,method,record,source,capture=env
    with pytest.raises(ApplicationError,match=error):
        with source.guard_report(ctx,SimpleNamespace(payload=SimpleNamespace(method_ref=method)),record,capture(text,state)): pass


def test_schema_value_is_checked_not_just_digest(env):
    ctx,method,record,source,capture=env
    record.method_content=MethodContent.from_value(record.method_content.schema_ref,{'answer':3})
    with pytest.raises(ApplicationError):
        with source.guard_report(ctx,SimpleNamespace(payload=SimpleNamespace(method_ref=method)),record,capture('{"answer":3}')): pass
