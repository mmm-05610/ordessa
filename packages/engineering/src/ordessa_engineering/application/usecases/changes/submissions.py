"""Submission facts or explicit quarantine on the original Engineering authority."""
from contextlib import ExitStack
from dataclasses import asdict
from uuid import uuid4
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.commands import CommandContext, CommandResult, request_digest, ReadSet, read_set_projection
from ...contracts.submissions import report_input_schema, agent_report_input_schema
from ...contracts.errors import ApplicationError
from ...contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from ....domain.changes.submission import Submission
from ....domain.changes.agent_submission_report import AgentSubmissionReport
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

    @staticmethod
    def report_request_digest(record, context):
        if type(record) is AgentSubmissionReport:
            schema = agent_report_input_schema()
            return request_digest('engineering.submissions.record_report', context,
                {'record':decode_json(encode_submission(record))},
                read_set_projection(ReadSet(context.scope,())), input_schema_id=schema['$id'],
                input_schema_digest=Digest('sha256',hashlib.sha256(canonical_bytes(schema)).hexdigest()),
                interface_version='2')
        operation = 'engineering.submissions.record_report'
        schema = report_input_schema(record.schema_version)
        return request_digest(operation,context,{'record':decode_json(encode_submission(record))},
            read_set_projection(ReadSet(context.scope,())), input_schema_id=schema['$id'],
            input_schema_digest=Digest('sha256',hashlib.sha256(canonical_bytes(schema)).hexdigest()),
            interface_version='1')

    def record_report(self, record, context, *, records, blobs, query_invocation=None, query_factory=None):
        """Record a method-bound agent report as pending review, never accepted.

        This path admits only a report source that
        resolves the current Method and binds actual Unit output to the report
        body and fixed artifact revisions.  The text in MethodContent remains
        authored report content; it does not create test/file/effect facts.
        """
        if type(record) is AgentSubmissionReport:
            return self._record_agent_report(record, context, records=records, blobs=blobs,
                query_factory=query_factory)
        operation='engineering.submissions.record_report'
        if type(context) is not CommandContext or self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)
        if (type(record) is not Submission or record.scope != context.scope
                or record.created_by != context.authenticated_actor or record.created_at != context.received_at):
            raise ApplicationError('SUBMISSION_ATTRIBUTION_MISMATCH')
        if self.report_source is None:
            raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
        self._validate_report_fact_shape(record)
        digest=self.report_request_digest(record,context)
        with self.factory.begin(context.scope,'read') as uow:
            entry=uow.commands.get(context.key)
            if entry is not None:
                if entry.operation != operation or entry.request_digest != digest or entry.project_id != context.scope.project_id:
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
            if query_factory is not None:
                if not callable(query_factory):
                    raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
                from ...orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
                binding = resolve_dispatch_submission_binding(uow,record,method_runs=self.method_runs)
        # Replays never issue another native query invocation. For a new write
        # the original producer receives only the exact persisted binding.
        if query_factory is not None:
            query_invocation = query_factory(binding)
        execution=record.execution_ref
        unit_ref={'environmentNamespace':execution.environment_namespace,'unitId':execution.unit_id,
            'ownerProviderRef':decode_json(execution.owner_provider_ref_bytes),'sourceRevision':execution.source_revision}
        captured=capture_execution_observation(records,blobs,authority_id=self.factory.authority_id,
            unit_ref=unit_ref,operation_ref=execution.operation_ref,
            expected_prompt_digest='sha256:'+execution.prompt_input_digest.hex,query_invocation=query_invocation,
            max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES if record.schema_version == 2 else 262144)
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

    def _record_agent_report(self, record, context, *, records, blobs, query_factory):
        """Input2 ordinary Agent report, through the original approval/COMMIT cuts."""
        from jsonschema import Draft202012Validator
        from .agent_declared_report import DeclaredAgentWorkReportSource, resolve_agent_declared_report_binding
        operation = 'engineering.submissions.record_report'
        if type(context) is not CommandContext or self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, operation)
        if (record.scope != context.scope or record.created_by != context.authenticated_actor
                or record.created_at != context.received_at):
            raise ApplicationError('SUBMISSION_ATTRIBUTION_MISMATCH')
        if record.checkpoint_ref is not None:
            raise ApplicationError('AGENT_REPORT_CHECKPOINT_UNAVAILABLE')
        source = self.report_source
        if (type(source) is not DeclaredAgentWorkReportSource or source.factory is not self.factory
                or source.blobs is not blobs or source.records is not records
                or source.query_factory is not query_factory):
            raise ApplicationError('SUBMISSION_AGENT_REPORT_SOURCE_UNAVAILABLE')
        if not Draft202012Validator(agent_report_input_schema()).is_valid({'record':decode_json(encode_submission(record))}):
            raise ApplicationError('INVALID_INPUT')
        digest = self.report_request_digest(record, context)
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            if entry is not None:
                if entry.operation != operation or entry.request_digest != digest or entry.project_id != context.scope.project_id:
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)
            binding = resolve_agent_declared_report_binding(uow, record)
            package = uow.implementation.resolve_package(record.package_ref)
            grant = uow.authorization.get_grant(record.authorization_refs[0])
        invocation = query_factory(binding)
        if invocation is None:
            raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
        captured = records.capture_reference(record.execution_ref, read_invocation=invocation)
        if self.approvals is None:
            raise ApplicationError('IMPLEMENTATION_GRANT_AUTHORITY_UNAVAILABLE')
        try:
            with ExitStack() as guards:
                admission_port = self.approvals._admission()
                guards.enter_context(admission_port.guard_intent(context, grant.intent))
                guards.enter_context(admission_port.guard_evidence(context, grant.intent, grant.evidence))
                decisions = guards.enter_context(self.approvals._gates(context, grant.intent))
                admission = guards.enter_context(source.guard_report(context, package, record, captured))
                self._validate_report_admission(record, package, captured, admission)
                if (admission.agent_ref_bytes != record.execution_ref.agent_ref_bytes
                        or admission.turn_ref_bytes != record.execution_ref.turn_ref_bytes
                        or admission.engineering_attempt_ref != record.execution_ref.engineering_attempt_ref):
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                return self._commit_agent_report(record, context, digest, decisions=decisions)
        except ReferenceError as error:
            raise ApplicationError(error.code) from error

    def _commit_agent_report(self, record, context, digest, *, decisions):
        from .agent_declared_report import resolve_agent_declared_report_binding
        from ...orchestration.steps.declared_implementation_dispatch import _grant_facts
        from ..support.clock import utc_now
        with self.factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation='engineering.submissions.record_report', operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
            package = uow.implementation.resolve_package(record.package_ref)
            grant = uow.authorization.get_grant(record.authorization_refs[0])
            self.approvals._check_gates(uow, decisions)
            binding = resolve_agent_declared_report_binding(uow, record)
            _grant_facts(uow,binding.work['work_id'],binding.work['action_id'],binding.step_id,
                utc_now(),binding=binding)
            uow.authorization.check_action_consumptions(binding.approval_ref,
                intent_digest=binding.intent_digest, target_digest=binding.digest,
                action_instances=binding.action_instances)
            validate_submission_graph(record,package,grant,(),())
            refs = (record.execution_ref.captured_observation_ref, record.method_content.rendered_body_ref,
                *record.output_refs, *(ref for item in record.coverage for ref in item.evidence_refs if type(ref) is BlobRef))
            for ref in set(refs):
                uow.implementation.read_blob(ref)
            for item in record.coverage:
                for ref in item.evidence_refs:
                    if type(ref) is ArtifactRevisionRef:
                        uow.engineering.resolve_revision(ref)
            ref = uow.submissions.create(record)
            result = canonical_bytes({'submission_ref':asdict(ref),'workflow_state':'submitted',
                'review_status':'pending_review','accepted':False})
            uow.commands.complete(context.key,state='completed',result_bytes=result,expected_version=entry.version)
            uow.commit()
            return CommandResult(uow.authority_id,entry.operation_id,'completed',result)

    @staticmethod
    def _validate_report_fact_shape(record):
        """Report-only writes/admission cannot carry asserted host execution facts."""
        if (type(record) is not Submission or record.method_content is None
                or record.resulting_snapshots or record.file_changes
                or record.commit_refs or record.test_evidence or record.effect_observations
                or not record.output_refs
                or record.schema_version == 1 and any(type(ref) is not ArtifactRevisionRef for ref in record.output_refs)):
            raise ApplicationError('SUBMISSION_REPORT_FACT_SHAPE_INVALID')

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
            if record.schema_version == 1:
                ImplementationUseCases._resolve_package(uow,package,now=utc_now())
            self.approvals._check_gates(uow,decisions)
            from ...orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
            binding=resolve_dispatch_submission_binding(uow,record,method_runs=self.method_runs)
            if record.schema_version == 2:
                from ...orchestration.steps.declared_implementation_dispatch import _grant_facts
                _grant_facts(uow,binding.work['work_id'],binding.work['action_id'],binding.step_id,
                    utc_now(),binding=binding)
            before=tuple(uow.implementation.resolve_repository_baseline(r) for r in record.baseline_snapshots)
            validate_submission_graph(record,package,grant,before,())
            for ref in self._blobs(record):
                uow.implementation.read_blob(ref)
            for ref in record.output_refs:
                if type(ref) is ArtifactRevisionRef:
                    uow.engineering.resolve_revision(ref)
            if record.schema_version == 1:
                verify_sources(record.source_refs,(),uow.proposals.validated_budget())
            # v2 sources are the exact immutable baseline/candidate refs of
            # PreparedPackage, checked by the Work/package graph above. The
            # historical artifact-source resolver cannot reinterpret them.
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

