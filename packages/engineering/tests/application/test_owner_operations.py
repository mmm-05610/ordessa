"""Boundary checks for the typed current owner-operation adapters.

These tests use explicit doubles and do not claim real grants, dispatch, or
submission integration.
"""
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.usecases.owner_operations import EngineeringOwnerOperations


class _Factory:
    authority_id = 'fixture-engineering-authority'


class _Blobs:
    authority_id = 'fixture-engineering-authority'


class _Owner:
    def __init__(self, factory, blobs=None, execution=None):
        self.factory = factory
        self.blobs = blobs
        self.execution = execution
        self.called = False

    def freeze_package(self, *args):
        self.called = True

    def dispatch(self, *args, **kwargs):
        self.called = True

    def record(self, *args, **kwargs):
        self.called = True


def _ops():
    factory, blobs = _Factory(), _Blobs()
    records = object()
    execution = type('Execution', (), {'records': records,
        'query_factory': staticmethod(lambda binding: object())})()
    return EngineeringOwnerOperations(factory, packages=_Owner(factory),
        dispatch=_Owner(factory, blobs, execution), submissions=_Owner(factory), records=records,
        blobs=blobs)


def test_closed_operation_inputs_reject_before_calling_owner():
    operations = _ops()
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.freeze_package({'record': {}, 'context': object()}, object())
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.dispatch_execution({'dispatch': {'run_id':'r'}}, object())
    # A run-shaped request is never an active writer any more, whatever else it carries.
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.dispatch_execution({'dispatch': {'run_id':'r','step_id':'s','attempt':1,
            'unit_ref':{},'params':{},'actions':['edit_repository'],'timeout':1}}, object())
    # A Work-shaped request missing the declared identity is refused too.
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.dispatch_execution({'dispatch': {'work_id':'w','step_id':'s','attempt':1,
            'unit_ref':{},'params':{},'actions':['edit_repository'],'timeout':1}}, object())
    from test_review_usecases import _context, _scope
    context=_context(_scope(),'legacy-submission-route')
    assert not hasattr(operations,'record_submission')
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_UNKNOWN'):
        operations.execute('engineering.submissions.record', {'record': {}}, context)
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.execute('engineering.submissions.record_report',
                           {'record': {}, 'records': object()}, context)
    assert not operations.packages.called
    assert not operations.dispatch.called
    assert not operations.submissions.called


def test_capabilities_are_detached_and_declare_conservative_outcomes():
    # Look capabilities up by identity: the list may carry more owners than it
    # once did, so an index assumption is not a contract.
    by_id = {item.capability_id: item for item in owner_capabilities()}
    assert by_id['engineering.packages.freeze'].contract['workflow_outcomes'] == ['completed', 'unknown']
    assert by_id['engineering.executions.dispatch'].contract['workflow_outcomes'] == [
        'completed', 'failed', 'unknown']
    assert by_id['engineering.proposals.associate_review'].contract['workflow_outcomes'] == [
        'completed', 'rejected', 'unknown']
    # The set of advertised owners is a contract; their order is not.
    assert set(by_id) == {
        'engineering.packages.freeze', 'engineering.proposals.associate_review',
        'engineering.executions.dispatch', 'engineering.submissions.record_report'}
    dispatch = by_id['engineering.executions.dispatch']
    assert dispatch.contract['completion_semantics'].endswith('always false.')
    report = by_id['engineering.submissions.record_report']
    assert report.contract['workflow_outcomes'] == ['submitted', 'unknown']
    assert 'accepted' not in report.contract['workflow_outcomes']
    assert set(by_id['engineering.packages.freeze'].contract['input_schema']
               ['properties']['record']['properties']) == {
        'scope','package_id','created_at','created_by','payload','digest'}
    submission_schema = report.contract['input_schema']['properties']['record']
    assert len(submission_schema['oneOf']) == 2
    for version_schema in submission_schema['oneOf']:
        assert 'scope' not in version_schema['properties']
        assert {'realm_id','project_id','submission_id'} <= set(version_schema['properties'])
    assert all(item.contract['registered'] is False for item in by_id.values())
    report.contract['workflow_outcomes'].append('accepted')
    fresh_report = next(item for item in owner_capabilities()
                        if item.capability_id == 'engineering.submissions.record_report')
    assert 'accepted' not in fresh_report.contract['workflow_outcomes']


def test_constructor_requires_same_original_authority_objects():
    factory, blobs = _Factory(), _Blobs()
    records = object()
    execution = type('Execution', (), {'records': records,
        'query_factory': staticmethod(lambda binding: object())})()
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_FACTORY_MISMATCH'):
        EngineeringOwnerOperations(factory, packages=_Owner(object()), dispatch=_Owner(factory, blobs, execution),
            submissions=_Owner(factory), records=records, blobs=blobs)
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_SOURCE_AUTHORITY_UNAVAILABLE'):
        EngineeringOwnerOperations(factory, packages=_Owner(factory), dispatch=_Owner(factory, blobs, execution),
            submissions=_Owner(factory), records=records, blobs=object())


def test_dispatch_rejects_boolean_timeout_and_duplicate_actions_before_owner_call():
    operations = _ops()
    # The active write entry takes a declared Work identity; the same input
    # checks apply to it.
    base = {'work_id':'work-1','action_id':'incremental.prepare-packages','step_id':'draft','attempt':1,
        'unit_ref':{'environmentNamespace':'env','unitId':'unit','ownerProviderRef':{},'sourceRevision':'rev'},
        'params':{},'actions':['edit_repository'],'timeout':1}
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.dispatch_execution({'dispatch':base | {'timeout':True}}, object())
    with pytest.raises(ApplicationError, match='OWNER_OPERATION_INPUT_INVALID'):
        operations.dispatch_execution({'dispatch':base | {'actions':['edit_repository','edit_repository']}}, object())
    assert not operations.dispatch.called


def test_report_same_key_replay_and_changed_record_digest_conflict_in_original_journal(tmp_path):
    import hashlib
    import runpy
    from dataclasses import replace
    from pathlib import Path

    from ordessa_infrastructure.encoding import canonical_bytes, decode_json
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.application.contracts.commands import ReadSet, request_digest, read_set_projection
    from ordessa_engineering.application.contracts.submissions import report_input_schema
    from ordessa_engineering.application.usecases.changes.submissions import SubmissionUseCases
    from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
    from ordessa_engineering.domain.changes.submission_codec import encode_submission
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.application.contracts.commands import CommandContext

    tests=Path(__file__).parents[1]
    record=runpy.run_path(str(tests/'application/test_submission_agent_report.py'))['_report_record']()
    output=ArtifactRevisionRef(record.scope.realm_id,record.scope.project_id,'fixture-output',
        'fixture-revision',Digest('sha256','c'*64))
    coverage=(replace(record.coverage[0],output_refs=(output,)),)
    record=replace(record,output_refs=(output,),coverage=coverage)
    context=CommandContext(record.scope,'fixture-principal',record.created_by,'report-replay',
        record.created_at,'report-replay-trace')
    operation='engineering.submissions.record_report'
    schema=report_input_schema(record.schema_version)
    raw=encode_submission(record)
    digest=request_digest(operation,context,{'record':decode_json(raw)},
        read_set_projection(ReadSet(context.scope,())),
        input_schema_id=schema['$id'],
        input_schema_digest=Digest('sha256',hashlib.sha256(canonical_bytes(schema)).hexdigest()),
        interface_version='1')
    lib=EngineeringLibrary.create((tmp_path/'report-replay.sqlite').resolve(),
        library_id='report-replay-fixture',schema_version=14)
    try:
        factory=SQLiteUoWFactory(lib)
        result_bytes=canonical_bytes({'cached':'pending-review-result'})
        with factory.begin(record.scope) as uow:
            reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                operation=operation,operation_id='cached-report-operation',request_digest=digest)
            uow.commands.complete(context.key,state='completed',result_bytes=result_bytes,
                expected_version=reservation.entry.version)
            uow.commit()

        class Never:
            def __getattr__(self,name):
                raise AssertionError('exact replay must return before Unit or Blob reads')

        access=type('Access',(),{'require':lambda self,ctx,op: None})()
        usecases=SubmissionUseCases(factory,access,report_source=object())
        replay=usecases.record_report(record,context,records=Never(),blobs=Never(),query_invocation=None)
        assert replay.status=='completed' and replay.result_bytes==result_bytes
        assert replay.operation_id=='cached-report-operation'
        with pytest.raises(ApplicationError,match='REQUEST_IDENTITY_CONFLICT'):
            usecases.record_report(replace(record,submission_id='changed-report'),context,
                records=Never(),blobs=Never(),query_invocation=None)
        assert lib._connection.execute('SELECT count(*) FROM eng_submissions').fetchone()==(0,)
    finally:
        lib.close()
