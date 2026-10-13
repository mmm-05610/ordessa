"""Submission facts or explicit quarantine on the original Engineering authority."""
from contextlib import ExitStack
from dataclasses import asdict
from uuid import uuid4
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.commands import CommandContext, CommandResult, request_digest, ReadSet, read_set_projection
from ...contracts.submissions import report_input_schema
from ...contracts.errors import ApplicationError
from ....domain.changes.submission import Submission
from ....domain.changes.submission_codec import encode_submission
from ....domain.changes.submission_binding import validate_submission_graph
from ....domain.common.models.values import Digest
from ....domain.common.models.refs import BlobRef
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.artifacts.refs import ArtifactRevisionRef
from ..packages.implementation import ImplementationUseCases
from ..material_closure import verify_sources
from .execution_capture import capture_execution_observation


class SubmissionUseCases:
    """Missing dispatch/material source refuses normal seal, preserving facts.

    An injected source must be the original trusted dispatch/observation owner;
    no concrete production owner is available yet. Fixture ports cannot qualify
    production. A completed ACP RPC never supplies package-execution binding.
    """
    def __init__(self, factory, access=None, *, approval_usecases=None, report_source=None, method_runs=None):
        if approval_usecases is not None and getattr(approval_usecases,'factory',None) is not factory:
            raise ApplicationError('AUTHORIZATION_AUTHORITY_MISMATCH')
        self.factory,self.access,self.approvals=factory,access,approval_usecases
        self.report_source=report_source
        if method_runs is not None and getattr(method_runs,'factory',None) is not factory:
            raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
        self.method_runs=method_runs

    def record_report(self, record, context, *, records, blobs, query_invocation):
        """Record a method-bound agent report as pending review, never accepted.

        This path admits only a report source that
        resolves the current Method and binds actual Unit output to the report
        body and fixed artifact revisions.  The text in MethodContent remains
        authored report content; it does not create test/file/effect facts.
        """
        operation='engineering.submissions.record_report'
        if type(context) is not CommandContext or self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)
        if (type(record) is not Submission or record.scope != context.scope
                or record.created_by != context.authenticated_actor or record.created_at != context.received_at):
            raise ApplicationError('SUBMISSION_ATTRIBUTION_MISMATCH')
        if self.report_source is None:
            raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
        if (record.method_content is None or record.resulting_snapshots or record.file_changes
                or record.commit_refs or record.test_evidence or record.effect_observations
                or not record.output_refs
                or any(type(ref) is not ArtifactRevisionRef for ref in record.output_refs)):
            raise ApplicationError('SUBMISSION_REPORT_FACT_SHAPE_INVALID')
        raw=encode_submission(record)
        schema=report_input_schema()
        digest=request_digest(operation,context,{'record':decode_json(raw)},read_set_projection(ReadSet(context.scope,())),
            input_schema_id=schema['$id'],input_schema_digest=Digest('sha256',hashlib.sha256(canonical_bytes(schema)).hexdigest()),interface_version='1')
        with self.factory.begin(context.scope,'read') as uow:
            entry=uow.commands.get(context.key)
            if entry is not None:
                if entry.operation != operation or entry.request_digest != digest or entry.project_id != context.scope.project_id:
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
        execution=record.execution_ref
        unit_ref={'environmentNamespace':execution.environment_namespace,'unitId':execution.unit_id,
            'ownerProviderRef':decode_json(execution.owner_provider_ref_bytes),'sourceRevision':execution.source_revision}
        captured=capture_execution_observation(records,blobs,authority_id=self.factory.authority_id,
            unit_ref=unit_ref,operation_ref=execution.operation_ref,
            expected_prompt_digest='sha256:'+execution.prompt_input_digest.hex,query_invocation=query_invocation)
        if captured.blob_ref.identity_projection() != execution.captured_observation_ref.identity_projection():
            raise ApplicationError('SUBMISSION_EXECUTION_OBSERVATION_CHANGED')
        if self.approvals is None:
            raise ApplicationError('IMPLEMENTATION_GRANT_AUTHORITY_UNAVAILABLE')
        try:
            with ExitStack() as guards:
                with self.factory.begin(context.scope,'read') as uow:
                    package=uow.implementation.resolve_package(record.package_ref)
                    grant=uow.authorization.get_grant(record.authorization_refs[0])
                admission_port=self.approvals._admission()
                guards.enter_context(admission_port.guard_intent(context,grant.intent))
                guards.enter_context(admission_port.guard_evidence(context,grant.intent,grant.evidence))
                decisions=guards.enter_context(self.approvals._gates(context,grant.intent))
                admission=guards.enter_context(self.report_source.guard_report(context,package,record,captured))
                self._validate_report_admission(record,package,captured,admission)
                return self._commit_report(record,context,digest,decisions=decisions)
        except ReferenceError as exc:
            raise ApplicationError(exc.code) from exc

    @staticmethod
    def _validate_report_admission(record,package,captured,admission):
        if (admission is None or record.method_content.schema_ref != admission.report_schema_ref
                or record.method_content.schema_ref.method_ref != admission.method_ref
                or package.payload.method_ref != admission.method_ref
                or hashlib.sha256(record.method_content.value_bytes).hexdigest() != admission.report_content_digest.hex
                or record.output_refs != admission.output_refs
                or admission.execution_operation_ref != record.execution_ref.operation_ref
                or admission.prompt_input_digest != record.execution_ref.prompt_input_digest
                or admission.query_digest != captured.query_digest
                or admission.captured_observation_ref != captured.blob_ref):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        covered=tuple(ref for item in record.coverage for ref in item.output_refs)
        if set(covered) != set(record.output_refs):
            raise ApplicationError('SUBMISSION_REPORT_OUTPUT_COVERAGE_INCOMPLETE')

    def _commit_report(self,record,context,digest,*,decisions):
        with self.factory.begin(context.scope) as uow:
            reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                operation='engineering.submissions.record_report',operation_id=str(uuid4()),request_digest=digest)
            entry=reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
            package=uow.implementation.resolve_package(record.package_ref)
            grant=uow.authorization.get_grant(record.authorization_refs[0])
            from ..support.clock import utc_now
            ImplementationUseCases._resolve_package(uow,package,now=utc_now())
            self.approvals._check_gates(uow,decisions)
            from ...orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
            resolve_dispatch_submission_binding(uow,record,method_runs=self.method_runs)
            before=tuple(uow.implementation.resolve_repository_baseline(r) for r in record.baseline_snapshots)
            validate_submission_graph(record,package,grant,before,())
            for ref in self._blobs(record):
                uow.implementation.read_blob(ref)
            for ref in record.output_refs:
                uow.engineering.resolve_revision(ref)
            verify_sources(record.source_refs,(),uow.proposals.validated_budget())
            ref=uow.submissions.create(record)
            result=canonical_bytes({'submission_ref':asdict(ref),'workflow_state':'submitted',
                'review_status':'pending_review','accepted':False})
            uow.commands.complete(context.key,state='completed',result_bytes=result,expected_version=entry.version)
            uow.commit()
            return CommandResult(uow.authority_id,entry.operation_id,'completed',result)



    @staticmethod
    def _blobs(record):
        return tuple({r for r in (record.execution_ref.captured_observation_ref,record.checkpoint_ref,
            None if record.method_content is None else record.method_content.rendered_body_ref,
            *(r for r in record.output_refs if type(r) is BlobRef),
            *(r for c in record.coverage for r in c.evidence_refs if type(r) is BlobRef),
            *(t.observation_ref for t in record.test_evidence),
            *(t.execution_ref.captured_observation_ref for t in record.test_evidence),
            *(r for e in record.effect_observations for r in e.evidence_refs),
            *(e.compensation_ref for e in record.effect_observations)) if r is not None})

