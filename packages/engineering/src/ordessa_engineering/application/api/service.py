"""Finite application entry point over the existing command/UoW owners.

Composition supplies authentication and control admission. No method policy,
dynamic handler lookup, legacy workflow fallback or second journal lives here.
The async surface follows E6; handlers currently perform bounded synchronous
SQLite work and never suspend with an open transaction.
"""
from ..usecases.artifacts import ArtifactUseCases, input_schema as artifact_schema
from ..usecases.changes.proposals import ProposalUseCases, input_schema as proposal_schema
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ..usecases.queries.service import EngineeringQueries, SUPPORTED_QUERIES as OWNER_QUERIES
from ..usecases.queries.run_waits import CurrentRunWaitUseCases
from ..orchestration.method_runs import MethodRunOrchestrator, MethodRunBindings
from ..usecases.reviews.service import ReviewUseCases, input_schema as review_schema, command_input_schema as review_command_schema
from ..usecases.approvals.service import ApprovalUseCases, SUPPORTED_APPROVAL_COMMANDS, input_schema as approval_schema
from ..usecases.changes.apply import ChangeApplyUseCases
from ..usecases.changes.acceptance_adopt import AcceptanceUseCases
from ..usecases.changes.submissions import SubmissionUseCases
from ..usecases.packages.implementation import ImplementationUseCases
from ..contracts.submissions import report_input_schema
from ..contracts.commands import ReadSet
from ...domain.changes.submission_codec import decode_submission
from ...domain.packages.codec import decode_package
from ...domain.changes.dispatch_codec import decode_dispatch
from ordessa_infrastructure.encoding import canonical_bytes
from ..contracts.implementation_routes import IMPLEMENTATION_COMMANDS, IMPLEMENTATION_QUERIES
from ..contracts.execution_dispatch import EXECUTION_DISPATCH
from ..usecases.reviews.assignments import (
    ASSIGN_REVIEWER, REVOKE_REVIEWER, ReviewerAssignmentUseCases,
    command_input_schema as reviewer_assignment_schema,
    decode_command_input as decode_reviewer_assignment_input,
)


SUPPORTED_COMMANDS = (
    "engineering.artifacts.create",
    "engineering.artifacts.append_revision",
    "engineering.proposals.create",
    "engineering.proposals.withdraw",
    "engineering.proposals.supersede",
    "engineering.reviews.request",
    "engineering.reviews.record",
    "engineering.submissions.record_report",
    "engineering.packages.freeze", ASSIGN_REVIEWER, REVOKE_REVIEWER,
) + SUPPORTED_APPROVAL_COMMANDS

SUPPORTED_QUERIES = OWNER_QUERIES + (
    "engineering.work.get", "engineering.work.current_condition", "engineering.runs.get_wait",
    "engineering.runs.list",
)

_ARTIFACT_COMMANDS = frozenset({
    "engineering.artifacts.create",
    "engineering.artifacts.append_revision",
})
_PROPOSAL_COMMANDS = frozenset({
    "engineering.proposals.create",
    "engineering.proposals.withdraw",
    "engineering.proposals.supersede",
})
_REVIEW_COMMANDS = frozenset({
    "engineering.reviews.request",
    "engineering.reviews.record",
})


class EngineeringService:
    supported_commands = SUPPORTED_COMMANDS
    supported_queries = SUPPORTED_QUERIES
    conditional_commands = IMPLEMENTATION_COMMANDS + (EXECUTION_DISPATCH,)
    conditional_queries = IMPLEMENTATION_QUERIES

    @staticmethod
    def operation_capabilities():
        """Detached descriptions of actual handlers, never access grants.

        Binding these descriptions to a published method is the registered
        catalog owner's responsibility; this service does not publish a method.
        """
        from ..orchestration.method_bridge import command_capabilities
        return command_capabilities()

    def bound_operation_capabilities(self):
        """Return only existing operation descriptors backed by selected owners.

        This is a source-binding projection, not a registration, permission,
        runtime grant check, or claim that an operation will succeed. Product
        composition intersects it with its actual callable registrations.
        """
        from ..orchestration.method_bridge import command_capabilities
        from ..orchestration.owner_capabilities import owner_capabilities
        from ..orchestration.method_bridge import CompilationCapabilities
        from ..orchestration.method_runs import MethodRunBindings, MethodRunOrchestrator
        from ..usecases.artifacts import ArtifactUseCases
        from ..usecases.changes.proposals import ProposalUseCases
        from ..usecases.reviews.service import ReviewUseCases
        from ..usecases.reviews.admission import EngineeringReviewAdmission
        from ..usecases.approvals.service import ApprovalUseCases
        from ..usecases.changes.apply import ChangeApplyUseCases
        from ..usecases.changes.acceptance_adopt import AcceptanceUseCases
        from ..usecases.packages.implementation import ImplementationUseCases
        from ..usecases.changes.submissions import SubmissionUseCases
        from ..usecases.queries.run_waits import CurrentRunWaitUseCases

        factory, access = self._factory, self._access
        if (factory is None or access is None
                or not callable(getattr(factory, "begin", None))
                or not callable(getattr(access, "require", None))):
            return CompilationCapabilities((), trust_class="host")
        described = {item.capability_id: item
                     for item in command_capabilities().capabilities}
        selected = set()

        def handler_owner(operation):
            handler = self._commands.get(operation)
            return getattr(handler, "__self__", None)

        def same_declared_authority(port):
            if port is None:
                return False
            if hasattr(port, "factory") and port.factory is not factory:
                return False
            if hasattr(port, "access") and port.access is not access:
                return False
            return True

        def callable_guards(port, *names):
            return (same_declared_authority(port)
                    and all(callable(getattr(port, name, None)) for name in names))

        def review_source():
            owner = handler_owner("engineering.reviews.request")
            admission = getattr(owner, "admission", None)
            valid = (type(owner) is ReviewUseCases
                and owner.factory is factory and owner.access is access
                and type(admission) is EngineeringReviewAdmission
                and admission.factory is factory
                and getattr(getattr(admission, "methods", None), "factory", None) is factory
                and callable(getattr(admission, "guard_plan", None))
                and callable(getattr(admission, "verify_response", None))
                and callable(getattr(admission, "guard_trust", None)))
            return owner, admission, valid

        def conversation_review_gates(owner):
            conversation = getattr(owner, "admission", None)
            review = getattr(owner, "review_admission", None)
            _, required_review, valid_review = review_source()
            return (valid_review and review is required_review
                and callable_guards(conversation, "guard_intent", "guard_evidence")
                and callable(getattr(review, "guard_plan", None))
                and callable(getattr(review, "guard_trust", None)))

        def run_bindings():
            bindings = getattr(self._work, "bindings", None)
            source = getattr(bindings, "source", None)
            valid = (type(self._work) is MethodRunOrchestrator
                and self._work.factory is factory and self._work.access is access
                and type(bindings) is MethodRunBindings
                and bindings.factory is factory
                and getattr(getattr(bindings, "methods", None), "factory", None) is factory
                and callable(getattr(bindings, "registry_loader", None))
                and same_declared_authority(source))
            return bindings, source, valid

        def add(operation):
            if operation in described:
                selected.add(operation)

        # Basic original artifact and proposal owners.
        artifacts = handler_owner("engineering.artifacts.create")
        if (type(artifacts) is ArtifactUseCases and artifacts.factory is factory
                and artifacts.access is access
                and handler_owner("engineering.artifacts.append_revision") is artifacts):
            add("engineering.artifacts.create")
            add("engineering.artifacts.append_revision")

        proposals = handler_owner("engineering.proposals.create")
        if type(proposals) is ProposalUseCases and proposals.factory is factory and proposals.access is access:
            add("engineering.proposals.create")
            control = proposals.control_admission
            if callable_guards(control, "guard_control"):
                add("engineering.proposals.withdraw")
                add("engineering.proposals.supersede")

        # Review request uses the original exact review admission; record also
        # reads raw response bytes through the same-authority BlobStore.
        review_owner, _, has_review = review_source()
        if has_review:
            add("engineering.reviews.request")
            blobs = getattr(review_owner, "blobs", None)
            if (blobs is self._blobs and getattr(blobs, "authority_id", None)
                    == getattr(factory, "authority_id", None)):
                add("engineering.reviews.record")

        assignments = self._reviewer_assignments
        if (type(assignments) is ReviewerAssignmentUseCases
                and assignments.factory is factory and assignments.access is access
                and callable(getattr(access, "guard_current_capability", None))
                and callable(getattr(assignments.records, "resolve_unit_reference", None))
                and callable(assignments.unit_query_factory)
                and getattr(assignments.methods, "factory", None) is factory):
            add(ASSIGN_REVIEWER)
            add(REVOKE_REVIEWER)

        # Retain one original ApprovalUseCases/admission pair across approval,
        # change, acceptance and package owners. Port substitution is allowed,
        # but any advertised source factory/access must be this same authority.
        approval_ops = tuple(name for name in described
            if name.startswith("engineering.approvals.") or name == "engineering.notices.publish")
        approvals = handler_owner("engineering.approvals.prepare_intent")
        has_approval_gates = (type(approvals) is ApprovalUseCases
            and approvals.factory is factory and approvals.access is access
            and conversation_review_gates(approvals))
        if has_approval_gates:
            for operation in approval_ops:
                if handler_owner(operation) is approvals:
                    add(operation)

        change = handler_owner("engineering.changes.apply")
        if (type(change) is ChangeApplyUseCases and change.factory is factory
                and change.access is access and has_approval_gates
                and change.admission is approvals.admission
                and change.review_admission is approvals.review_admission):
            add("engineering.changes.apply")

        acceptance = handler_owner("engineering.acceptance.adopt")
        if (type(acceptance) is AcceptanceUseCases and acceptance.factory is factory
                and acceptance.access is access and has_approval_gates
                and acceptance.admission is approvals.admission
                and acceptance.review_admission is approvals.review_admission
                and callable_guards(acceptance.acceptance_admission, "guard_intent")
                and callable_guards(acceptance.submission_source, "guard_submission")):
            add("engineering.acceptance.adopt")

        # The service method is the actual package handler; its implementation
        # owner must retain the same original ApprovalUseCases and its guards.
        package_owner = getattr(self, "_packages", None)
        if (handler_owner("engineering.packages.freeze") is self
                and type(package_owner) is ImplementationUseCases
                and package_owner.factory is factory and package_owner.access is access
                and package_owner.approvals is approvals and has_approval_gates):
            add("engineering.packages.freeze")

        # Report descriptors require the selected method-bound report source,
        # the original execution-record reader, and its invocation factory.
        report_owner = handler_owner("engineering.submissions.record_report")
        reports = getattr(self, "_submission_reports", None)
        report_source = getattr(reports, "report_source", None)
        report_blobs = getattr(report_source, "blobs", None)
        records = getattr(self, "_execution_records", None)
        records_valid = (callable(getattr(records, "query_acp_turn", None))
            and callable(getattr(records, "acp_turn_query_digest", None)))
        report_bindings = getattr(report_source, "bindings", None)
        report_valid = (report_owner is self and type(reports) is SubmissionUseCases
            and reports.factory is factory and reports.access is access
            and callable_guards(report_source, "guard_report")
            and getattr(report_source, "factory", None) is factory
            and getattr(getattr(report_source, "methods", None), "factory", None) is factory
            and getattr(report_blobs, "authority_id", None) == getattr(factory, "authority_id", None)
            and report_blobs is self._blobs
            and getattr(report_bindings, "factory", None) is factory
            and callable(getattr(report_bindings, "guard_report_binding", None))
            and reports.method_runs is getattr(self._work, "bindings", None)
            and records_valid
            and callable(self._execution_query_factory))
        if report_valid:
            add("engineering.submissions.record_report")

        # Work routes require the exact MethodRunBindings retained by both
        # original consumers, its selected method-control owner, and live
        # business source/registry gates.
        bindings, work_source, has_work = run_bindings()
        if has_work:
            if (callable(getattr(work_source, "guard_inputs", None))
                    and handler_owner("engineering.work.bind_inputs") is self._work):
                add("engineering.work.bind_inputs")
            if (callable(getattr(work_source, "guard_start", None))
                    and handler_owner("engineering.work.start") is self._work):
                add("engineering.work.start")
            if (callable(getattr(work_source, "guard_step_completion", None))
                    and handler_owner("engineering.work.record_command_step") is self._work):
                add("engineering.work.record_command_step")
            waits = getattr(self, "_waits", None)
            if (type(waits) is CurrentRunWaitUseCases and waits.factory is factory
                    and waits.access is access and waits.bindings is bindings
                    and callable(getattr(bindings, "guard_wait", None))
                    and callable(getattr(work_source, "guard_condition", None))
                    and handler_owner("engineering.runs.resume") is waits):
                add("engineering.runs.resume")

        dispatch = self._execution_dispatch
        dispatch_valid = (dispatch is not None
            and getattr(dispatch, "factory", None) is factory
            and getattr(dispatch, "access", None) is access
            and callable(getattr(dispatch, "execute", None)))
        native = next((item for item in owner_capabilities()
            if item.capability_id == EXECUTION_DISPATCH), None)
        if dispatch_valid and native is not None:
            described[EXECUTION_DISPATCH] = native
            add(EXECUTION_DISPATCH)
            if (has_work and callable(getattr(work_source, "guard_step_completion", None))
                    and handler_owner("engineering.work.record_dispatch_step") is self._work):
                add("engineering.work.record_dispatch_step")

        return CompilationCapabilities(tuple(described[name] for name in sorted(selected)), trust_class="host")

    def __init__(self, factory, access, *, proposal_control_admission=None,
                 review_admission=None, review_control=None, blobs=None, conversation_admission=None,
                 acceptance_admission=None, submission_source=None, current_wait_bindings=None,
                 submission_report_source=None, execution_records=None, execution_query_factory=None,
                 implementation_routes=None, execution_dispatch=None,
                 reviewer_assignments=None):
        if reviewer_assignments is not None and (
                type(reviewer_assignments) is not ReviewerAssignmentUseCases
                or reviewer_assignments.factory is not factory
                or reviewer_assignments.access is not access):
            raise ApplicationError("REVIEWER_ASSIGNMENT_AUTHORITY_MISMATCH")
        self._reviewer_assignments = reviewer_assignments
        if execution_dispatch is not None and (
                getattr(execution_dispatch,'factory',None) is not factory
                or getattr(execution_dispatch,'access',None) is not access
                or not callable(getattr(execution_dispatch,'execute',None))):
            raise ApplicationError('DISPATCH_AUTHORITY_MISMATCH')
        self._execution_dispatch=execution_dispatch
        if implementation_routes is not None and (
                getattr(implementation_routes, "factory", None) is not factory
                or getattr(implementation_routes, "access", None) is not access
                or not callable(getattr(implementation_routes, "invoke", None))):
            raise ApplicationError("IMPLEMENTATION_AUTHORITY_MISMATCH")
        self._implementation_routes = implementation_routes
        self._access = access
        self._blobs = blobs
        artifacts = ArtifactUseCases(factory, access)
        proposals = ProposalUseCases(factory, access, proposal_control_admission)
        reviews = ReviewUseCases(factory, access, review_admission, review_control, blobs=blobs)
        approvals = ApprovalUseCases(factory, access, conversation_admission, review_admission)
        self._packages = ImplementationUseCases(factory,access,approval_usecases=approvals)
        changes = ChangeApplyUseCases(factory, access, conversation_admission, review_admission)
        acceptance = AcceptanceUseCases(factory, access, conversation_admission, review_admission,
            acceptance_admission=acceptance_admission, submission_source=submission_source)
        self._waits = CurrentRunWaitUseCases(factory, access, current_wait_bindings, review_admission)
        self._work = MethodRunOrchestrator(factory, access,
            current_wait_bindings if type(current_wait_bindings) is MethodRunBindings else None)
        self._factory = factory
        self._execution_records = execution_records
        self._execution_query_factory = execution_query_factory
        self._submission_reports = SubmissionUseCases(factory, access, approval_usecases=approvals,
            report_source=submission_report_source,
            method_runs=current_wait_bindings if type(current_wait_bindings) is MethodRunBindings else None)
        self._commands = {
            "engineering.packages.freeze": self._freeze_package,
            "engineering.submissions.record_report": self._record_report,
            "engineering.work.start": self._work.start,
            "engineering.work.bind_inputs": self._work.bind_inputs,
            "engineering.work.record_command_step": self._work.record_command_step,
            "engineering.work.record_dispatch_step": self._work.record_dispatch_step,
            "engineering.runs.resume": self._waits.resume,
            "engineering.acceptance.adopt": acceptance.adopt,
            "engineering.changes.apply": changes.apply,
            "engineering.artifacts.create": artifacts.create,
            "engineering.artifacts.append_revision": artifacts.append_revision,
            "engineering.proposals.create": proposals.create,
            "engineering.proposals.withdraw": proposals.withdraw,
            "engineering.proposals.supersede": proposals.supersede,
            "engineering.reviews.request": reviews.request,
            "engineering.reviews.record": reviews.record_command,
            "engineering.notices.publish": approvals.publish_notice,
            "engineering.approvals.prepare_intent": approvals.prepare_intent,
            "engineering.approvals.request": approvals.request,
            "engineering.approvals.record_conversation": approvals.record_conversation,
            "engineering.approvals.revoke": approvals.revoke,
        }
        self._queries = EngineeringQueries(factory, access)
        self._commands[ASSIGN_REVIEWER] = self._assign_reviewer
        self._commands[REVOKE_REVIEWER] = self._revoke_reviewer

    @staticmethod
    def input_schema(operation):
        if operation==EXECUTION_DISPATCH:
            from ..orchestration.owner_capabilities import owner_capabilities
            descriptor=next(d for d in owner_capabilities() if d.capability_id==operation)
            return {'$schema':'https://json-schema.org/draft/2020-12/schema',
                    '$id':descriptor.contract['input_schema_id'], **descriptor.contract['input_schema']}
        if type(operation) is not str or operation not in SUPPORTED_COMMANDS:
            raise ApplicationError("OPERATION_UNAVAILABLE")
        if operation == "engineering.submissions.record_report":
            return report_input_schema()
        if operation in (ASSIGN_REVIEWER, REVOKE_REVIEWER):
            return reviewer_assignment_schema(operation)
        if operation == 'engineering.packages.freeze':
            from ..orchestration.owner_capabilities import owner_capabilities
            descriptor=next(d for d in owner_capabilities() if d.capability_id==operation)
            return {'$schema':'https://json-schema.org/draft/2020-12/schema',
                    '$id':'urn:ordessa:engineering:implementation-content:1',
                    **descriptor.contract['input_schema']}
        if operation in _ARTIFACT_COMMANDS:
            return artifact_schema(operation)
        if operation in _REVIEW_COMMANDS:
            if operation == "engineering.reviews.record":
                return review_command_schema(operation)
            return review_schema(operation)
        if operation in _PROPOSAL_COMMANDS:
            return proposal_schema(operation)
        if operation in SUPPORTED_APPROVAL_COMMANDS:
            return approval_schema(operation)
        # Membership and schema ownership are deliberately checked separately:
        # adding a handler without its owning schema is an unavailable contract,
        # never an accidental proposal-schema alias.
        raise ApplicationError("OPERATION_SCHEMA_UNAVAILABLE")

    def _reviewer_assignment_command(self, operation, parameters, context, read_set):
        if self._access is None:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        self._access.require(context, operation)
        if self._reviewer_assignments is None:
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        if read_set is not None and read_set != ReadSet(context.scope, ()):
            raise ApplicationError("REVIEWER_ASSIGNMENT_READ_SET_UNSUPPORTED")
        from jsonschema import Draft202012Validator
        if (type(parameters) is not dict
                or not Draft202012Validator(self.input_schema(operation)).is_valid(parameters)):
            raise ApplicationError("INVALID_INPUT")
        decoded = decode_reviewer_assignment_input(operation, parameters)
        handler = (self._reviewer_assignments.assign_reviewer if operation == ASSIGN_REVIEWER
                   else self._reviewer_assignments.revoke_reviewer)
        return handler(context, **decoded)

    def _assign_reviewer(self, parameters, context, *, read_set=None):
        return self._reviewer_assignment_command(ASSIGN_REVIEWER, parameters, context, read_set)

    def _revoke_reviewer(self, parameters, context, *, read_set=None):
        return self._reviewer_assignment_command(REVOKE_REVIEWER, parameters, context, read_set)

    def _freeze_package(self, parameters, context, *, read_set=None):
        if self._access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self._access.require(context,'engineering.packages.freeze')
        if read_set is not None and read_set != ReadSet(context.scope,()):
            raise ApplicationError('PACKAGE_READ_SET_UNSUPPORTED')
        from jsonschema import Draft202012Validator
        if type(parameters) is not dict or not Draft202012Validator(self.input_schema('engineering.packages.freeze')).is_valid(parameters):
            raise ApplicationError('INVALID_INPUT')
        try:
            record=decode_package(canonical_bytes(parameters['record']))
        except Exception as exc:
            raise ApplicationError('INVALID_INPUT') from exc
        return self._packages.freeze_package(record,context)

    @staticmethod
    def command_request_digest(operation, parameters, context, reads):
        """Exact original owner identity used to correlate a declared run step."""
        if operation=='engineering.packages.freeze':
            if reads != ReadSet(context.scope,()):
                raise ApplicationError('PACKAGE_READ_SET_UNSUPPORTED')
            return ImplementationUseCases.package_request_digest(
                decode_package(canonical_bytes(parameters['record'])),context)
        import hashlib
        from ..contracts.commands import request_digest, read_set_projection, artifact_read_set_projection
        from ...domain.common.models.values import Digest
        schema=EngineeringService.input_schema(operation)
        projection=artifact_read_set_projection(reads) if operation.startswith('engineering.artifacts.') else read_set_projection(reads)
        return request_digest(operation,context,parameters,projection,
            input_schema_id=schema['$id'],input_schema_digest=Digest('sha256',hashlib.sha256(canonical_bytes(schema)).hexdigest()),
            interface_version=schema['$id'].rsplit(':',1)[1])

    def _record_report(self, parameters, context, *, read_set=None):
        if self._access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self._access.require(context, 'engineering.submissions.record_report')
        if read_set is not None and read_set != ReadSet(context.scope,()):
            raise ApplicationError('SUBMISSION_REPORT_READ_SET_UNSUPPORTED')
        if (type(parameters) is not dict or set(parameters) != {'record'}
                or self._execution_records is None or not callable(self._execution_query_factory)):
            raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
        try:
            raw = canonical_bytes(parameters['record'])
            if len(raw) > 2*1024*1024:
                raise ApplicationError('INVALID_INPUT')
            record = decode_submission(raw)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('INVALID_INPUT') from exc
        with self._factory.begin(context.scope, 'read') as uow:
            row = uow.dispatch.by_operation(record.execution_ref.operation_ref, context.scope)
            binding = decode_dispatch(row['binding_bytes'])
        invocation = self._execution_query_factory(binding)
        return self._submission_reports.record_report(record, context,
            records=self._execution_records, blobs=self._blobs, query_invocation=invocation)

    async def execute(self, operation, parameters, context, *, read_set=None):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if type(operation) is not str:
            raise ApplicationError("INVALID_ARGUMENT")
        if operation==EXECUTION_DISPATCH:
            if self._access is None:
                raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
            self._access.require(context,operation)
            if self._execution_dispatch is None:
                raise ApplicationError('DISPATCH_AUTHORITY_UNAVAILABLE')
            if read_set is not None:
                raise ApplicationError('DISPATCH_READ_SET_UNSUPPORTED')
            from jsonschema import Draft202012Validator
            if not Draft202012Validator(self.input_schema(operation)).is_valid(parameters):
                raise ApplicationError('INVALID_INPUT')
            return self._execution_dispatch.execute(operation,parameters,context)
        if operation in IMPLEMENTATION_COMMANDS:
            if read_set is not None:
                raise ApplicationError("IMPLEMENTATION_READ_SET_UNSUPPORTED")
            return self._implementation_invoke(operation, parameters, context)
        handler = self._commands.get(operation)
        if handler is None:
            # Consent callbacks, missing dispatch/Work contracts and unknown
            # methods cannot become arbitrary dynamically imported handlers.
            if self._access is None:
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
            self._access.require(context, operation)
            raise ApplicationError("OPERATION_UNAVAILABLE")
        return handler(parameters, context, read_set=read_set)

    async def query(self, query, parameters, context):
        if query in IMPLEMENTATION_QUERIES:
            return self._implementation_invoke(query, parameters, context)
        if query == "engineering.work.get":
            return self._work.read(parameters,context)
        if query == 'engineering.runs.list':
            return self._work.list(parameters,context)
        if query == "engineering.work.current_condition":
            return self._waits.read(parameters, context, query_operation=query)
        if query == "engineering.runs.get_wait":
            return self._waits.read(parameters, context)
        return self._queries.query(query, parameters, context)

    def _implementation_invoke(self, operation, parameters, context):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if self._access is None:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        self._access.require(context, operation)
        if self._implementation_routes is None:
            raise ApplicationError("OPERATION_UNAVAILABLE")
        return self._implementation_routes.invoke(operation, parameters, context)
