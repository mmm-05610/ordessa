"""Report admission boundary fixtures; these do not represent native dispatch."""
from dataclasses import replace
from pathlib import Path
import runpy

import pytest

from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.submissions import SubmissionUseCases
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import MethodContent
from ordessa_engineering.domain.common.models.values import Digest

TESTS=Path(__file__).parents[1]


def _report_record():
    value=runpy.run_path(str(TESTS/'domain/test_submission.py'))['record']()
    proposal,=value.change_set.proposal_refs
    # Explicit fixture Method binding only; it does not assert a real Method.
    method=MethodRef('fixture-method','fixture-release',1,Digest('sha256','a'*64))
    schema=ExactMethodResourceRef(method,'report.schema.json',Digest('sha256','b'*64),'report-schema')
    return replace(value,method_content=MethodContent.from_value(schema,{'summary':'fixture report'}),
        resulting_snapshots=(),file_changes=(),commit_refs=(),output_refs=(),
        test_evidence=(),effect_observations=())


def test_missing_trusted_report_source_refuses_without_query_or_submission(tmp_path):
    value=_report_record()
    context=CommandContext(value.scope,'fixture-principal',value.created_by,'report-1',value.created_at,'trace-report')
    class Access:
        def require(self,ctx,operation):
            assert ctx==context and operation=='engineering.submissions.record_report'
    class Never:
        def __getattr__(self,name):
            raise AssertionError('report admission must refuse before reading execution')
    usecases=SubmissionUseCases(object(),Access(),report_source=None)
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_SOURCE_UNAVAILABLE'):
        usecases.record_report(value,context,records=Never(),blobs=Never(),query_invocation=None)


def test_report_admission_must_bind_all_outputs_and_captured_execution():
    from types import SimpleNamespace
    value=_report_record()
    execution=value.execution_ref
    captured=SimpleNamespace(query_digest='query-digest',blob_ref=execution.captured_observation_ref)
    admission=SimpleNamespace(method_ref=value.method_content.schema_ref.method_ref,
        report_schema_ref=value.method_content.schema_ref,output_refs=(),
        report_content_digest=Digest('sha256',__import__('hashlib').sha256(value.method_content.value_bytes).hexdigest()),
        execution_operation_ref=execution.operation_ref,prompt_input_digest=execution.prompt_input_digest,
        query_digest='wrong-query',captured_observation_ref=execution.captured_observation_ref)
    with pytest.raises(ApplicationError,match='SUBMISSION_REPORT_BINDING_MISMATCH'):
        SubmissionUseCases._validate_report_admission(value,SimpleNamespace(payload=SimpleNamespace(method_ref=admission.method_ref)),captured,admission)
