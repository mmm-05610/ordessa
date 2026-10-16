"""Exact method report declaration and original dispatch/output association."""
from contextlib import contextmanager

from ....application.contracts.errors import ApplicationError
from ....application.contracts.commands import ReadSet, ReadVersion
from ....application.usecases.changes.report_source import DeclaredUnitReportBinding
from ....application.orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....methods.definitions.models.compiled import thaw_value


class SQLiteMethodUnitReportBindings:
    def __init__(self,factory,method_control,*,phase_key):
        if (getattr(method_control,'factory',None) is not factory
                or type(phase_key) is not str or not phase_key):
            raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
        self.factory,self.methods,self.phase_key=factory,method_control,phase_key

    @contextmanager
    def guard_report_binding(self,context,snapshot,package,submission):
        method=package.payload.method_ref
        ref=snapshot.ref
        if ((ref.method_id,ref.release_version,ref.schema_version,ref.snapshot_digest)!=
                (method.method_id,method.release_version,method.schema_version,method.snapshot_digest.hex)
                or context.scope!=package.scope or context.scope!=submission.scope
                or submission.package_ref!=package.ref or submission.method_content is None
                or submission.method_content.schema_ref.method_ref!=method):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        nodes=tuple(n for n in snapshot.program.workflow.steps if n.id==self.phase_key
            and getattr(n,'operation',None)=='engineering.submissions.record_report')
        if len(nodes)!=1 or nodes[0].config is None:
            raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
        config=thaw_value(nodes[0].config)
        strategy=config.get('unit_submission_review_strategy',{})
        fixed=strategy.get('fixed_delivery',{}) if type(strategy) is dict else None
        if type(fixed) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
        declared=fixed.get('author_result_schema')
        boundary=config.get('report_mode_boundary',{})
        if type(boundary) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
        if declared is None:
            declared=boundary.get('method_content_schema')
        if (type(declared) is not str or declared!=submission.method_content.schema_ref.resource_id
                or ('method_content_schema' in boundary and boundary['method_content_schema']!=declared)):
            raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
        docs=tuple(d for d in snapshot.program.document_definitions if d.schema_resource.resource_id==declared)
        outputs=submission.output_refs
        if (len(docs)!=1 or type(outputs) is not tuple or not outputs
                or len(set(outputs))!=len(outputs) or any(type(r) is not ArtifactRevisionRef for r in outputs)):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        with self.methods.guard_method(context,method) as current_snapshot:
            if current_snapshot!=snapshot:
                raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
            with self.factory.begin(context.scope,'read') as uow:
                binding=resolve_dispatch_submission_binding(uow,submission)
                original_package=uow.implementation.resolve_package(binding.package_ref)
                row=uow.dispatch.by_operation(submission.execution_ref.operation_ref,context.scope)
                if (original_package!=package or binding.package_ref!=package.ref or row['dispatch_phase']!='completed'
                        or submission.authorization_refs!=(binding.approval_ref,)):
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                versions={}
                for ref in outputs:
                    revision=uow.engineering.resolve_revision(ref)
                    if method not in revision.method_refs:
                        raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                    artifact=uow.engineering.get_artifact(ref.artifact_id)
                    versions[ref.artifact_id]=artifact.version
            reads=ReadSet(context.scope,tuple(ReadVersion('artifact',k,v) for k,v in sorted(versions.items())))
            with self.factory.guard_read_set(reads):
                yield DeclaredUnitReportBinding(docs[0].document_type,submission.execution_ref,outputs)


__all__=['SQLiteMethodUnitReportBindings']
