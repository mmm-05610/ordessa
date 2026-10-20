"""Finite application entry point over the existing command/UoW owners.

Composition supplies authentication and control admission. No method policy,
dynamic handler lookup, legacy workflow fallback or second journal lives here.
The async surface follows E6; handlers currently perform bounded synchronous
SQLite work and never suspend with an open transaction.
"""
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from collections.abc import Mapping
from ..usecases.artifacts import ArtifactUseCases, input_schema as artifact_schema
from ..usecases.changes.proposals import ProposalUseCases, input_schema as proposal_schema
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ..usecases.queries.service import EngineeringQueries, SUPPORTED_QUERIES as OWNER_QUERIES
from ..usecases.queries.run_waits import CurrentRunWaitUseCases
from ..orchestration.method_runs import MethodRunOrchestrator, MethodRunBindings
from ..usecases.reviews.service import ReviewUseCases, input_schema as review_schema, command_input_schema as review_command_schema
from ..usecases.approvals.service import ApprovalUseCases, SUPPORTED_APPROVAL_COMMANDS, input_schema as approval_schema
from ..usecases.works import WorkUseCases, SUPPORTED_WORK_COMMANDS, input_schema as works_input_schema
from ..usecases.queries.works import WorkQueries, GUARD_STEP
from ..orchestration.declared_review_change import (
    DECLARED_REVIEW_STEPS as _DECLARED_REVIEW_STEPS, DeclaredReviewChangeSteps)
from ..orchestration.declared_prepare_packages import (
    DeclaredPreparePackagesSteps)
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
    "engineering.proposals.associate_review",
    "engineering.proposals.withdraw",
    "engineering.proposals.supersede",
    "engineering.reviews.request",
    "engineering.reviews.record",
    "engineering.submissions.record_report",
    "engineering.packages.freeze", ASSIGN_REVIEWER, REVOKE_REVIEWER,
) + SUPPORTED_APPROVAL_COMMANDS + SUPPORTED_WORK_COMMANDS

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
    "engineering.proposals.associate_review",
    "engineering.proposals.withdraw",
    "engineering.proposals.supersede",
})
_REVIEW_COMMANDS = frozenset({
    "engineering.reviews.request",
    "engineering.reviews.record",
})


def _termination_ref(record, name):
    """The owner-read termination evidence reference, nested under outcome.

    C never synthesises a top-level field and the contract is not widened here:
    a missing or non-string reference is a refusal, not an empty value.
    """
    outcome = record.get('outcome') if isinstance(record, Mapping) else None
    ref = outcome.get('terminationEvidenceRef') if isinstance(outcome, Mapping) else None
    if type(ref) is not str or not ref:
        raise ApplicationError('CONTINUATION_EVIDENCE_INVALID')
    return ref


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

        def source_method_authority(source, method):
            return (getattr(source, "factory", None) is factory
                    and callable_guards(source, "read")
                    and getattr(method, "factory", None) is factory
                    and callable_guards(method, "guard", "read_resource"))

        def source_review_authority(admission, source, method, bindings):
            return (type(admission) is EngineeringReviewAdmission
                    and admission.factory is factory
                    and admission.source_materials is source
                    and admission.method_guard is method
                    and admission.source_review_bindings is bindings
                    and source_method_authority(source, method)
                    and callable(getattr(bindings, "resolve_source_plan", None))
                    and callable(getattr(admission, "guard_plan", None))
                    and callable(getattr(admission, "verify_response", None))
                    and callable(getattr(admission, "guard_trust", None)))

        def review_source():
            owner = handler_owner("engineering.reviews.request")
            admission = getattr(owner, "admission", None)
            bindings = getattr(admission, "bindings", None)
            source_bindings = getattr(admission, "source_review_bindings", None)
            legacy_bindings_valid = (getattr(bindings, "factory", None) is factory
                and callable(getattr(bindings, "resolve_bindings", None)))
            declared_bindings_valid = (getattr(bindings, 'factory', None) is factory
                and callable(getattr(bindings, 'resolve_declared_submission_plan', None))
                and getattr(getattr(admission, 'method_guard', None), 'factory', None) is factory)
            source_bindings_valid = source_review_authority(admission,
                getattr(admission, "source_materials", None),
                getattr(admission, "method_guard", None), source_bindings)
            valid = (type(owner) is ReviewUseCases
                and owner.factory is factory and owner.access is access
                and type(admission) is EngineeringReviewAdmission
                and admission.factory is factory
                and getattr(getattr(admission, "methods", None), "factory", None) is factory
                and (legacy_bindings_valid or source_bindings_valid or declared_bindings_valid)
                and callable(getattr(admission, "guard_plan", None))
                and callable(getattr(admission, "verify_response", None))
                and callable(getattr(admission, "guard_trust", None)))
            return owner, admission, valid

        def conversation_review_gates(owner):
            conversation = getattr(owner, "admission", None)
            review = getattr(owner, "review_admission", None)
            _, required_review, valid_review = review_source()
            return (valid_review and review is required_review
                and callable_guards(getattr(review, "source", None), "verify_response", "guard_trust")
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
            if source_method_authority(proposals.source_materials, proposals.method_guard):
                add("engineering.proposals.create")
            source_review = proposals.review_admission
            source_bindings = getattr(source_review, "source_review_bindings", None)
            if source_review_authority(source_review, proposals.source_materials,
                    proposals.method_guard, source_bindings):
                add("engineering.proposals.associate_review")
            control = proposals.control_admission
            if callable_guards(control, "guard_control"):
                add("engineering.proposals.withdraw")
                add("engineering.proposals.supersede")

        # Review request uses the original exact review admission; record also
        # reads raw response bytes through the same-authority BlobStore.
        review_owner, review_admission, has_review = review_source()
        if has_review:
            add("engineering.reviews.request")
            blobs = getattr(review_owner, "blobs", None)
            if (callable_guards(getattr(review_admission, "source", None), "verify_response", "guard_trust")
                    and blobs is self._blobs and getattr(blobs, "authority_id", None)
                    == getattr(factory, "authority_id", None)):
                add("engineering.reviews.record")

        assignments = self._reviewer_assignments
        if (type(assignments) is ReviewerAssignmentUseCases
                and assignments.factory is factory and assignments.access is access
                and callable(getattr(access, "guard_current_capability", None))
                and callable(getattr(assignments.records, "read_agent_reference", None))
                and callable(assignments.agent_query_factory)
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

        # Package preparation reads only source, method, and review authorities;
        # it has no approval/grant input or legacy package writer.
        package_owner = getattr(self, "_packages", None)
        if (handler_owner("engineering.packages.freeze") is self
                and type(package_owner) is ImplementationUseCases
                and package_owner.factory is factory and package_owner.access is access
                and package_owner.approvals is approvals
                and source_review_authority(package_owner.review_admission,
                    package_owner.source_materials, package_owner.method_guard,
                    getattr(package_owner.review_admission, "source_review_bindings", None))
                and callable(getattr(package_owner.method_guard, "preparation_roles", None))):
            add("engineering.packages.freeze")

        # Report descriptors require the selected method-bound report source,
        # the original execution-record reader, and its invocation factory.
        report_owner = handler_owner("engineering.submissions.record_report")
        reports = getattr(self, "_submission_reports", None)
        report_source = getattr(reports, "report_source", None)
        report_blobs = getattr(report_source, "blobs", None)
        records = getattr(self, "_execution_records", None)
        # Original typed Unit reports remain historical contracts. The current
        # command descriptor is published only with the selected Agent owner.
        from ..usecases.changes.agent_declared_report import DeclaredAgentWorkReportSource
        agent_report_valid = (report_owner is self and type(reports) is SubmissionUseCases
            and reports.factory is factory and reports.access is access and reports.approvals is approvals
            and type(report_source) is DeclaredAgentWorkReportSource
            and report_source.factory is factory and report_source.methods is self._method_guard
            and getattr(report_source.methods, 'factory', None) is factory
            and report_source.blobs is self._blobs
            and getattr(report_source.blobs, 'authority_id', None) == factory.authority_id
            and report_source.records is records and getattr(records, 'blob_store', None) is self._blobs
            and all(callable(getattr(records, name, None)) for name in ('capture_reference','read_agent_binding'))
            and report_source.query_factory is self._execution_query_factory
            and callable(self._execution_query_factory))
        if agent_report_valid:
            add('engineering.submissions.record_report')

        # Work routes require the exact MethodRunBindings retained by both
        # original consumers, its selected method-control owner, and live
        # business source/registry gates.
        bindings, work_source, has_work = run_bindings()
        # Declarative Work is the only advertised creation route. It needs the
        # work owner bound to this exact factory/access plus a method guard able
        # to read a released declaration under current control. The legacy
        # compiled create/advance operations are withdrawn: their handlers are
        # gone, so no route reaches them.
        works_valid = (type(self._works) is WorkUseCases
            and self._works.factory is factory and self._works.access is access
            and callable(getattr(self._method_guard, "read_declaration", None)))
        if works_valid and handler_owner("engineering.work.start") is self._works:
            add("engineering.work.start")
        if (works_valid and handler_owner("engineering.work.invoke") is self
                and callable(getattr(access, 'admit_work_step', None))
                and callable(getattr(access, 'check_work_capability', None))):
            add("engineering.work.invoke")
        # Every legacy compiled route (start/bind_inputs/record_*/resume/cancel)
        # is withdrawn: it either created or advanced a compiled program run, and
        # this stage keeps those persisted rows for reading only.

        dispatch = self._execution_dispatch
        dispatch_valid = (dispatch is not None
            and getattr(dispatch, "factory", None) is factory
            and getattr(dispatch, "access", None) is access
            and callable(getattr(dispatch, "execute", None))
            and getattr(dispatch, 'declared_implementation_ready', False) is True)
        native = (getattr(dispatch, 'dispatch_descriptor', None) if dispatch_valid else None)
        if native is None:
            native = next((item for item in owner_capabilities()
                if item.capability_id == EXECUTION_DISPATCH), None)
        # The declared generation step's owner is the attached Unit transport:
        # the capability is projected only from a real attached owner whose
        # transport callables exist, never from the name alone.
        handles = getattr(self, "_declared_generation_handles", None)
        generation_valid = (self.declared_generation_ready
            and callable(getattr(handles.get("blobs"), "read_verified", None))
            and all(callable(getattr(handles.get("execution"), name, None))
                    for name in ("freeze_input", "send", "capture",
                                 "guard_effect_handoff")))
        if (dispatch_valid or generation_valid) and native is not None:
            described[EXECUTION_DISPATCH] = native
            add(EXECUTION_DISPATCH)

        return CompilationCapabilities(tuple(described[name] for name in sorted(selected)), trust_class="host")

    def attach_declared_generation_handles(self, *, blobs, execution,
                                           unit_ref_resolver=None, generation_timeout=60,
                                           format_rework=None):
        """Attach the composition's existing Unit transport to the declared step.

        The handles are the same objects the implementation dispatch line already
        uses; no Unit, store, permission or credential is created here. The
        The same dispatch owner is retained for the generation port and the
        original Unit effect-write guard. Each call uses its admitted context.
        """
        import math
        from ..contracts.execution_observations import MAX_GENERATION_TIMEOUT_SECONDS
        from ..orchestration.steps.generation_format_rework import validate_format_rework
        if (blobs is None or execution is None
                or type(generation_timeout) not in (int, float)
                or not math.isfinite(generation_timeout) or not 0 < generation_timeout <= MAX_GENERATION_TIMEOUT_SECONDS):
            raise ApplicationError('CAPABILITY_NOT_BOUND')
        self._declared_generation_handles = {'blobs': blobs, 'execution': execution,
                                              'unit_ref_resolver': unit_ref_resolver,
                                              'generation_timeout': float(generation_timeout),
                                              'format_rework': validate_format_rework(format_rework)}
        from ..orchestration.steps.declared_generation_dispatch import DeclaredGenerationDispatch
        self._declared_generation_dispatch = DeclaredGenerationDispatch(
            self._factory, self._access, blobs=blobs, execution=execution,
            review_admission=self._review_admission, method_guard=self._method_guard)
        return self

    @property
    def declared_generation_ready(self):
        handles = getattr(self, '_declared_generation_handles', None)
        return (handles is not None and callable(handles.get('unit_ref_resolver'))
                and getattr(self._source_materials, 'factory', None) is self._factory
                and callable(getattr(self._source_materials, 'read', None))
                and callable(getattr(self._review_admission, 'guard_plan', None))
                and callable(getattr(self._review_admission, 'guard_trust', None)))

    @property
    def declared_generation_dispatch(self):
        """The exact generation owner selected for this service's Unit guard."""
        return getattr(self, '_declared_generation_dispatch', None)

    def _declared_generation_port(self):
        handles = getattr(self, '_declared_generation_handles', None)
        if handles is None:
            return None
        from ordessa_engineering.application.orchestration.steps.declared_generation_port import (
            DeclaredGenerationPort)
        resolver = handles.get('unit_ref_resolver')
        if not callable(resolver):
            def resolver(context, binding, profile_ref):
                # Without a selection-resolved Unit there is nothing to dispatch.
                raise ApplicationError('WORK_ACTION_GENERATION_UNIT_UNAVAILABLE')
        return DeclaredGenerationPort(self._factory, self._access,
                                      blobs=handles['blobs'],
                                      execution=handles['execution'],
                                      unit_ref_resolver=resolver,
                                      dispatch=self.declared_generation_dispatch,
                                      source_materials=self._source_materials,
                                      generation_timeout=handles['generation_timeout'],
                                      format_rework=handles['format_rework'],
                                      validation=self._prepare_packages_steps.validate_generated_package,
                                      registration_guard=self._prepare_packages_steps.verify_generated_registration)

    def __init__(self, factory, access, *, proposal_control_admission=None,
                 review_admission=None, review_control=None, blobs=None, conversation_admission=None,
                 acceptance_admission=None, submission_source=None, current_wait_bindings=None,
                 submission_report_source=None, execution_records=None, execution_query_factory=None,
                 implementation_routes=None, execution_dispatch=None,
                 source_materials=None, method_guard=None, source_review_bindings=None,
                 reviewer_assignments=None, review_run=None, review_plan_factory=None,
                 continuation_evidence=None, continuation_unit_resolver=None):
        # Construct this same-owner coordinator only after the command surface
        # is defined: its report guards also use MethodBridge, which describes
        # this service's finite schemas during module initialization.
        from ..orchestration.declared_implementation_results import DeclaredImplementationResults
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
        if continuation_unit_resolver is not None and not callable(continuation_unit_resolver):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        self._continuation_evidence=continuation_evidence
        self._continuation_unit_resolver=continuation_unit_resolver
        self._execution_dispatch=execution_dispatch
        self._work_dispatch_scope = ContextVar('declared-work-dispatch', default=None)
        if implementation_routes is not None and (
                getattr(implementation_routes, "factory", None) is not factory
                or getattr(implementation_routes, "access", None) is not access
                or not callable(getattr(implementation_routes, "invoke", None))):
            raise ApplicationError("IMPLEMENTATION_AUTHORITY_MISMATCH")
        self._implementation_routes = implementation_routes
        self._access = access
        self._blobs = blobs
        self._source_materials=source_materials
        self._method_guard=method_guard
        self._source_review_bindings=source_review_bindings
        self._review_admission=review_admission
        if review_admission is not None:
            for name,selected in (('source_materials',source_materials),
                                  ('method_guard',method_guard),
                                  ('source_review_bindings',source_review_bindings)):
                actual=getattr(review_admission,name,None)
                if selected is not None and actual is not selected:
                    raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
                if selected is None and actual is not None:
                    if name=='source_materials': self._source_materials=actual
                    elif name=='method_guard': self._method_guard=actual
                    else: self._source_review_bindings=actual
        artifacts = ArtifactUseCases(factory, access)
        proposals = ProposalUseCases(factory, access, proposal_control_admission,
            source_materials=self._source_materials,method_guard=self._method_guard,
            review_admission=review_admission)
        reviews = ReviewUseCases(factory, access, review_admission, review_control, blobs=blobs)
        approvals = ApprovalUseCases(factory, access, conversation_admission, review_admission)
        self._packages = ImplementationUseCases(factory,access,approval_usecases=approvals,blobs=blobs,
            source_materials=self._source_materials,method_guard=self._method_guard,
            review_admission=review_admission)
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
        self._works = WorkUseCases(factory, access, self._method_guard)
        self._prepare_packages_steps = DeclaredPreparePackagesSteps(
            factory, method_guard=self._method_guard,
            review_admission=review_admission)
        self._review_run = review_run
        self._review_change_steps = DeclaredReviewChangeSteps(
            factory, method_guard=self._method_guard,
            plan_factory=review_plan_factory, blobs=blobs,
            dispatch=self._run_declared_step_command, review_run=review_run,
            review_admission=review_admission)
        self._implementation_results = DeclaredImplementationResults(
            factory, method_guard=self._method_guard, blobs=blobs,
            plan_factory=review_plan_factory, review_run=review_run,
            review_admission=review_admission, dispatch=self._run_declared_step_command,
            agent_records=execution_records, agent_query_factory=execution_query_factory)
        self._work_queries = WorkQueries(factory, access, self._method_guard,
            mapped_steps=self._work_step_capabilities,
            bound_capabilities=lambda: {item.capability_id
                for item in self.bound_operation_capabilities().capabilities},
            permit_execute=self._work_action_execute_permission)
        self._commands = {
            "engineering.packages.freeze": self._freeze_package,
            "engineering.submissions.record_report": self._record_report,
            "engineering.work.start": self._works.open,
            "engineering.work.invoke": self._invoke_work_action,
            "engineering.acceptance.adopt": acceptance.adopt,
            "engineering.changes.apply": changes.apply,
            "engineering.artifacts.create": artifacts.create,
            "engineering.artifacts.append_revision": artifacts.append_revision,
            "engineering.proposals.create": proposals.create,
            "engineering.proposals.associate_review": proposals.associate_review,
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

    def _prepare_work_continuation(self, value, context, work, declared, digest):
        """Qualify and claim one origin before entering the shared Work steps."""
        import hashlib
        from ordessa_infrastructure.encoding import decode_json
        from ..usecases.changes.dispatch_continuation import (
            continuation_operation_id, origin_ref_from_row, qualify_continuation,
            resolve_continuation_root)
        from ...domain.packages.codec import decode_package_ref
        from ...domain.common.models.values import Digest
        if self._continuation_evidence is None:
            raise ApplicationError('CONTINUATION_EVIDENCE_UNAVAILABLE')
        if self._continuation_unit_resolver is None:
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        selector = value['continuation_of']
        with self._factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.by_operation(selector['execution_operation_ref'], context.scope)
            binding = decode_dispatch(row['binding_bytes'])
            if row['dispatch_version'] != selector['expected_dispatch_version']:
                raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
            origin = origin_ref_from_row(row, binding,
                expected_acp_revision=selector['expected_acp_revision'])
            implementation_steps = tuple(step for step in declared['steps']
                if step['name'] == 'implement-approved-package')
            if (len(implementation_steps) != 1 or implementation_steps[0]['step_id'] != binding.step_id
                    or decode_package_ref(value['inputs'].get('package')) != binding.package_ref):
                raise ApplicationError('CONTINUATION_ORIGIN_MISMATCH')
            resolve_continuation_root(uow, binding)
            root_origin = row['continuation'].reservation_origin if row.get('continuation') else origin
            frozen = decode_json(uow.implementation.read_blob(binding.prompt_ref))
        derived = continuation_operation_id(context.scope, origin)
        # The original query factory accepts a real dispatch child context,
        # never the parent Work context. No Engineering write UoW is held here.
        with self._work_step_admission(context, EXECUTION_DISPATCH, derived) as step_context:
            self._execution_dispatch.verify_continuation_grant(binding, step_context)
            candidate = qualify_continuation(step_context, work, value['action_id'], binding.step_id,
                origin, factory=self._factory, evidence_reader=self._continuation_evidence)
        stop_ref = _termination_ref(candidate.evidence.stop_record, 'stop_record')
        release_ref = _termination_ref(candidate.evidence.release_record, 'release_record')
        semantic = Digest('sha256', hashlib.sha256(canonical_bytes(frozen['prompt'])).hexdigest())
        reservation = self._works.begin_continuation_claim(context, candidate, digest)
        if not reservation.created:
            # Exact-request replay was handled before reading the evidence. A
            # competing request never receives or executes another caller's result.
            raise ApplicationError('CONTINUATION_ALREADY_CLAIMED', retry='reconcile')
        observation = candidate.evidence.acp_observation
        draft = {'origin': origin, 'reservation_origin': root_origin,
            'causal_operation_id': reservation.operation_id,
            'failure_evidence_ref': candidate.failure_evidence_ref,
            'acp_observation_ref': observation.blob_ref, 'acp_revision': observation.revision,
            'stop_proof_ref': stop_ref, 'release_proof_ref': release_ref,
            'semantic_prompt_digest': semantic}
        return candidate, draft, reservation.operation_id

    def _dispatch_work_continuation(self, context, continuation, inputs):
        candidate, draft, _ = continuation
        owner = self._execution_dispatch
        owner.verify_continuation_grant(candidate.origin_binding, context)
        unit = self._continuation_unit_resolver(context, candidate, inputs)
        if type(unit) is not dict or canonical_bytes(unit) == candidate.origin_binding.unit_ref_bytes:
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        request = {'work_id': candidate.work.work_id,
            'action_id': candidate.origin_binding.work['action_id'],
            'step_id': candidate.origin.step_id, 'attempt': candidate.attempt,
            'unit_ref': unit, 'params': {}, 'actions': list(candidate.actions),
            'timeout': owner.implementation_timeout}
        return owner.dispatch_continuation(request, draft, context)

    def _report_correction_input(self, parameters, context, fields):
        """Authenticate the original parent; this is not another Work invoke."""
        if type(context) is not CommandContext or self._access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        current = getattr(self._access, 'current_context', None)
        if not callable(current) or current() is not context:
            raise ApplicationError('REPORT_CORRECTION_CONTEXT_REQUIRED')
        self._access.require(context, 'engineering.work.invoke')
        if (type(parameters) is not dict or set(parameters) != set(fields)
                or type(parameters.get('invoke_parameters')) is not dict
                or 'invocation_version' in parameters['invoke_parameters']):
            raise ApplicationError('REPORT_CORRECTION_INPUT_INVALID')
        value, digest, replay = self._works.invoke_replay(
            parameters['invoke_parameters'], context)
        if replay is None or replay.authority_id != self._factory.authority_id:
            raise ApplicationError('REPORT_CORRECTION_PARENT_REQUIRED')
        return value, digest, replay

    def _report_correction_work(self, context, value):
        import hashlib
        request = 'report-correction-work-' + hashlib.sha256(
            context.request_id.encode()).hexdigest()[:48]
        with self._work_step_admission(context, 'engineering.work.get', request) as child:
            view = self._work_queries.read({'work_id': value['work_id']}, child)
            work = self._work_queries.read_binding(child, value['work_id'])
        if ('expected_revision' in value
                and value['expected_revision'] != work.revision):
            raise ApplicationError('WORK_REVISION_STALE')
        return work, view

    def _report_correction_source(self):
        source = self._submission_reports.report_source
        if (getattr(source, 'factory', None) is not self._factory
                or getattr(source, 'methods', None) is not self._method_guard
                or getattr(source, 'blobs', None) is not self._blobs
                or any(not callable(getattr(source, name, None)) for name in (
                    'prepare_correction', 'correction_record',
                    'validate_correction', 'finish_correction_claim'))):
            raise ApplicationError('REPORT_CORRECTION_SOURCE_UNAVAILABLE')
        return source

    def _report_correction_tail_inputs(self, context, value, work, view, *, step_id=None):
        """Validate the entire declared tail before reserving any correction."""
        declared = next((item for item in view['declared_actions']
                         if item['action_id'] == value['action_id']), None)
        names = ('implement-approved-package', 'independently-review-report',
                 'resolve-one-operation-disposition', 'record-operation-result')
        if (declared is None or tuple(s['name'] for s in declared['steps']) != names
                or step_id is not None and declared['steps'][0]['step_id'] != step_id
                or not self._implementation_results.runnable):
            raise ApplicationError('REPORT_CORRECTION_METHOD_UNSUPPORTED')
        first, review, disposition, record = declared['steps']

        def linked(step, name, previous, output):
            items = [item for item in step['inputs'] if item['name'] == name]
            return (len(items) == 1 and items[0]['source_kind'] == 'step_output'
                    and items[0]['step_id'] == previous['step_id']
                    and items[0]['source_name'] == output and output in previous['outputs'])

        def action_input(step, name):
            items = [item for item in step['inputs'] if item['name'] == name]
            return (len(items) == 1 and items[0]['source_kind'] == 'action_input'
                    and items[0]['source_name'] == name)

        if (tuple(s['kind'] for s in declared['steps']) != ('invoke', 'invoke', 'invoke', 'record')
                or not linked(review, 'report', first, 'implementation_report')
                or not linked(disposition, 'report', first, 'implementation_report')
                or not linked(disposition, 'review', review, 'review_result')
                or not linked(record, 'result', disposition, 'operation_result')
                or not all(action_input(disposition, name)
                           for name in ('package', 'reviewer_profile', 'method'))):
            raise ApplicationError('REPORT_CORRECTION_METHOD_UNSUPPORTED')
        action_inputs = value.get('inputs') or {}
        mapped = dict(self._work_step_capabilities(), **{names[0]: GUARD_STEP})
        bound = {item.capability_id for item in self.bound_operation_capabilities().capabilities}
        with self._method_guard.guard(context, work.method_ref):
            resources = self._precheck_declared_steps(
                context, declared, work, mapped, bound, action_inputs)
        return declared, action_inputs, resources

    def prepare_report_content_rework(self, parameters, context):
        """Qualify one report-only rework; a selected approval guard is required."""
        from ..orchestration.report_content_rework import ReportContentReworkConsumer
        return ReportContentReworkConsumer(self).prepare(parameters, context)

    async def complete_report_content_rework(self, parameters, context):
        """Record a new report and its independent disposition without reopening work."""
        from ..orchestration.report_content_rework import ReportContentReworkConsumer
        return await ReportContentReworkConsumer(self).complete(parameters, context)

    def prepare_report_correction(self, parameters, context):
        """Reserve one format-only report operation through the original source.

        The source, not the host script, qualifies the completed implementation,
        rejected bytes and evidence. An occupied claim never grants another send.
        """
        from ...domain.common.mechanisms.codec import decode_blob_ref
        value, digest, replay = self._report_correction_input(
            parameters, context, ('invoke_parameters', 'origin', 'evidence'))
        selector = parameters['origin']
        required = {'parent_operation_id', 'execution_operation_ref',
                    'expected_parent_version', 'expected_dispatch_version',
                    'expected_observation_revision'}
        if (replay.status != 'pending' or type(selector) is not dict
                or set(selector) != required
                or selector['parent_operation_id'] != replay.operation_id
                or type(parameters['evidence']) is not dict):
            raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
        for name, minimum in (('expected_parent_version', 0),
                              ('expected_dispatch_version', 1),
                              ('expected_observation_revision', 1)):
            if type(selector[name]) is not int or selector[name] < minimum:
                raise ApplicationError('REPORT_CORRECTION_INPUT_INVALID')
        work, view = self._report_correction_work(context, value)
        self._report_correction_tail_inputs(context, value, work, view)
        result = self._report_correction_source().prepare_correction(
            context, work=work, selector=selector, invoke_digest=digest,
            evidence=parameters['evidence'])
        if (type(result) is not dict or set(result) != {
                'plan_ref', 'operation_ref', 'created', 'state', 'params', 'submission_ref'}
                or type(result['created']) is not bool):
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        plan = decode_blob_ref(result['plan_ref'])
        if result['operation_ref'] != 'report-format-rework/' + plan.digest.hex:
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        state = result['state']
        if state == 'ready':
            valid = (result['created'] and type(result['params']) is dict
                     and 'sessionId' not in result['params']
                     and result['submission_ref'] is None)
        elif state == 'pending_query_only':
            valid = (not result['created'] and result['params'] is None
                     and result['submission_ref'] is None)
        elif state == 'report_registered':
            from ...domain.reviews.target_codec import decode_subject_ref
            from ...domain.reviews.refs import SubmissionRef
            valid = (not result['created'] and result['params'] is None
                     and type(decode_subject_ref(result['submission_ref'])) is SubmissionRef)
        else:
            valid = False
        if not valid:
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        return result

    async def complete_report_correction(self, parameters, context):
        """Register an actual corrected capture and close only the report tail.

        No implementation dispatch is reachable here. Partial native review is
        query-only; this deliberately does not implement general Work recovery.
        """
        return await self._complete_report_correction(parameters, context, successor=False)

    async def resume_report_correction_review(self, parameters, context):
        """Run one explicit successor of a closed, unusable native review.

        The predecessor is re-read through the original owner before a stable
        Journal claim can authorize a new review. Existing or UNKNOWN attempts
        are never sent again, and accepted remains the original disposition.
        """
        return await self._complete_report_correction(parameters, context, successor=True)

    async def _complete_report_correction(self, parameters, context, *, successor):
        from dataclasses import asdict
        import hashlib
        from ordessa_infrastructure.encoding import decode_json
        from ...domain.common.mechanisms.codec import decode_blob_ref
        from ...domain.reviews.target_codec import decode_subject_ref
        from ...domain.reviews.refs import SubmissionRef
        fields = ('invoke_parameters', 'checkpoint_ref', 'predecessor_review') if successor else (
            'invoke_parameters', 'checkpoint_ref')
        value, digest, replay = self._report_correction_input(parameters, context, fields)
        predecessor = parameters['predecessor_review'] if successor else None
        checkpoint = decode_blob_ref(parameters['checkpoint_ref'])
        if replay.status != 'pending':
            result = decode_json(replay.result_bytes)
            if ((result.get('report_correction') or {}).get('checkpoint_ref')
                    != asdict(checkpoint)
                    or successor and (result.get('review_recovery') or {}).get('predecessor') != predecessor):
                raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
            return replay
        source = self._report_correction_source()
        work, view = self._report_correction_work(context, value)
        plan, binding, captured = source.validate_correction(
            context, checkpoint_ref=checkpoint)
        origin = plan['origin']
        if (origin['parent_key'] != asdict(context.key)
                or origin['parent_operation_id'] != replay.operation_id
                or origin['parent_request_digest'] != asdict(digest)
                or origin['work_id'] != work.work_id
                or origin['work_revision'] != work.revision
                or origin['action_id'] != value['action_id']
                or binding.work['work_id'] != work.work_id
                or binding.work['action_id'] != value['action_id']
                or captured.operation_ref != binding.execution_operation_ref
                or captured.state != 'completed'):
            raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
        declared, action_inputs, resources = self._report_correction_tail_inputs(
            context, value, work, view, step_id=binding.step_id)
        envelope = decode_json(self._blobs.read_verified(checkpoint))
        plan_ref = decode_blob_ref(envelope['plan_ref'])
        suffix = plan_ref.digest.hex
        record_request = 'report-correction-record-' + suffix[:48]
        with self._work_step_admission(
                context, 'engineering.submissions.record_report', record_request) as child:
            with self._factory.begin(context.scope, 'read') as uow:
                prior = uow.commands.get(child.key)
            if prior is None:
                record = source.correction_record(child, checkpoint_ref=checkpoint)
                stored = self._implementation_results._completed(await self.execute(
                    'engineering.submissions.record_report', {'record': record}, child))
            else:
                if (prior.operation != 'engineering.submissions.record_report'
                        or prior.state != 'completed'):
                    raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
                stored = decode_json(prior.result_bytes)
            subject = decode_subject_ref(stored['submission_ref'])
            if type(subject) is not SubmissionRef:
                raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
            with self._factory.begin(context.scope, 'read') as uow:
                submission = uow.submissions.resolve(subject)
                from ..usecases.changes.declared_report import resolve_declared_report_binding
                actual = resolve_declared_report_binding(uow, submission)
                if actual != binding or submission.checkpoint_ref != checkpoint:
                    raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
            source.finish_correction_claim(child, plan_ref=plan_ref, submission_ref=subject)
        recovery = None
        if successor:
            qualify = getattr(source, 'qualify_review_successor', None)
            if not callable(qualify):
                raise ApplicationError('REPORT_REVIEW_SUCCESSOR_UNAVAILABLE')
            recovery = qualify(context, checkpoint_ref=checkpoint,
                submission_ref=subject, predecessor=predecessor)
            if type(recovery) is not dict or set(recovery) != {'proof_ref', 'proof'}:
                raise ApplicationError('REPORT_REVIEW_SUCCESSOR_SOURCE_INVALID')
            proof_ref = decode_blob_ref(recovery['proof_ref'])
            proof = recovery['proof']
            if (type(proof) is not dict
                    or proof.get('contract') != 'ordessa.declared-review-successor-source/1'
                    or proof.get('checkpoint_ref') != asdict(checkpoint)
                    or proof.get('submission_ref') != asdict(subject)
                    or proof.get('predecessor') != predecessor
                    or self._blobs.read_verified(proof_ref) != canonical_bytes(proof)):
                raise ApplicationError('REPORT_REVIEW_SUCCESSOR_SOURCE_INVALID')
        try:
            return await self._complete_report_correction_tail(
                context, value, digest, replay, work, declared, action_inputs,
                resources, source, plan, plan_ref, checkpoint, binding, captured, subject,
                recovery=recovery)
        except ApplicationError as error:
            if error.code not in {'VERSION_CONFLICT', 'REPORT_CORRECTION_PARENT_CONFLICT'}:
                raise
            # Another identical caller may have closed the original parent
            # after our first read. Return only that persisted exact result.
            _, _, latest = self._works.invoke_replay(parameters['invoke_parameters'], context)
            if latest is not None and latest.status == 'completed':
                final = decode_json(latest.result_bytes)
                if ((final.get('report_correction') or {}).get('checkpoint_ref') == asdict(checkpoint)
                        and (not successor or (final.get('review_recovery') or {}).get('predecessor') == predecessor)):
                    return latest
            raise

    async def _complete_report_correction_tail(
            self, context, value, digest, parent, work, declared, action_inputs,
            resources, source, plan, plan_ref, checkpoint, binding, captured, subject,
            *, recovery=None):
        """One journal-owned review tail, with no route back to implementation."""
        from dataclasses import asdict
        import hashlib
        from ordessa_infrastructure.encoding import decode_json
        from ..contracts.commands import CommandKey
        from ...domain.common.mechanisms.hashing import record_digest
        from ...domain.changes.dispatch_codec import encode_dispatch

        key = CommandKey(context.scope.realm_id, context.principal_id,
                         'report-correction-tail-' + plan_ref.digest.hex[:48])
        operation = 'engineering.report_correction.tail'
        tail_digest = record_digest('report-correction-tail', {
            'parent_key': asdict(context.key), 'parent_operation_id': parent.operation_id,
            'parent_request_digest': asdict(digest), 'plan_ref': asdict(plan_ref),
            'checkpoint_ref': asdict(checkpoint), 'submission_ref': asdict(subject)})
        with self._factory.begin(context.scope) as uow:
            original = uow.commands.get(context.key)
            if (original is None or original.operation_id != parent.operation_id
                    or original.request_digest != digest or original.state != 'pending'
                    or original.version != plan['origin']['parent_version']):
                raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
            if recovery is not None:
                existing_tail = uow.commands.get(key)
                if (existing_tail is None or existing_tail.operation != operation
                        or existing_tail.request_digest != tail_digest
                        or existing_tail.state != 'pending'):
                    raise ApplicationError('REPORT_REVIEW_SUCCESSOR_TAIL_REQUIRED')
            claim = uow.commands.reserve(key, project_id=context.scope.project_id,
                operation=operation,
                operation_id='report-correction-tail/' + plan_ref.digest.hex,
                request_digest=tail_digest)
            uow.commit()
        if claim.entry.state != 'pending':
            raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')

        successor_claim = successor_key = successor_digest = None
        if recovery is not None:
            successor_digest = record_digest('report-review-successor', {
                'parent_key': asdict(context.key), 'parent_operation_id': parent.operation_id,
                'tail_key': asdict(key), 'tail_operation_id': claim.entry.operation_id,
                'tail_version': claim.entry.version, 'checkpoint_ref': asdict(checkpoint),
                'submission_ref': asdict(subject), 'proof_ref': recovery['proof_ref']})
            successor_key = CommandKey(context.scope.realm_id, context.principal_id,
                'report-review-successor-' + successor_digest.hex[:48])
            with self._factory.begin(context.scope) as uow:
                current_parent = uow.commands.get(context.key)
                current_tail = uow.commands.get(key)
                if (current_parent != original or current_tail != claim.entry):
                    raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
                successor_claim = uow.commands.reserve(successor_key,
                    project_id=context.scope.project_id,
                    operation='engineering.report_correction.review_successor',
                    operation_id='report-review-successor/' + successor_digest.hex,
                    request_digest=successor_digest)
                if successor_claim.entry.state != 'pending':
                    raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
                uow.commit()

        first, review_step, disposition_step, record_step = declared['steps']
        report = {'binding': decode_json(encode_dispatch(binding)),
                  'observation_ref': asdict(captured.blob_ref),
                  'params_assembly': 'VERIFIED_DECLARED_WORK_PACKAGE_METHOD_UNIT',
                  'phase': 'completed', 'reason': None,
                  'engineering_completed': False, 'accepted': False,
                  'submission_ref': asdict(subject)}
        steps = [{'step_id': first['step_id'], 'kind': first['kind'],
                  'operation': EXECUTION_DISPATCH, 'journal_request_id': None,
                  'operation_id': binding.execution_operation_ref, 'state': 'completed',
                  'completion_semantics': self._registered_completion(EXECUTION_DISPATCH),
                  'business': report}]
        suffix = plan_ref.digest.hex
        review_request = 'report-correction-review-' + suffix[:48]
        review_record = 'report-correction-review-record-' + suffix[:48]
        review_id = 'implementation-review-' + hashlib.sha256(
            canonical_bytes({'parent': parent.operation_id, 'plan_ref': asdict(plan_ref)})).hexdigest()
        if successor_claim is not None:
            suffix = successor_digest.hex
            review_request = 'review-successor-request-' + suffix[:48]
            review_record = 'review-successor-record-' + suffix[:48]
            review_id = 'implementation-review-successor-' + suffix
        review_key = CommandKey(context.scope.realm_id, context.principal_id, review_record)
        with self._factory.begin(context.scope, 'read') as uow:
            prior_review = uow.commands.get(review_key)
        if prior_review is not None:
            if prior_review.operation != 'engineering.reviews.record' or prior_review.state != 'completed':
                raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
            stored = decode_json(prior_review.result_bytes)
            review_result = {'review_ref': stored['review_ref'],
                             'submission_ref': asdict(subject),
                             'reviewer_profile': action_inputs['reviewer_profile']}
            review_operation_id = prior_review.operation_id
        else:
            # An occupied tail or partial review is query-only. In particular,
            # do not call the existing review runner a second time: it creates
            # its Unit before assigning it to the persisted request.
            if not (successor_claim.created if successor_claim is not None else claim.created):
                raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
            with self._factory.begin(context.scope, 'read') as uow:
                try:
                    uow.reviews.get_request(review_id)
                except ApplicationError as error:
                    if error.code != 'NOT_FOUND':
                        raise
                else:
                    raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
            payload = {}
            for item in review_step['inputs']:
                if item['source_kind'] == 'action_input':
                    payload[item['name']] = action_inputs[item['source_name']]
                elif item['source_kind'] == 'step_output':
                    if (item['step_id'] != first['step_id']
                            or item['source_name'] != 'implementation_report'):
                        raise ApplicationError('REPORT_CORRECTION_METHOD_UNSUPPORTED')
                    payload[item['name']] = report
                else:
                    payload[item['name']] = resources[(review_step['step_id'], item['name'])]
            with self._work_step_admission(
                    context, 'engineering.reviews.request', review_request) as child:
                contract = await self._implementation_results.request_review(
                    child, work, payload['report'], payload['reviewer_profile'],
                    review_id=review_id, step_id=review_step['step_id'], resources=payload)
            with self._work_step_admission(
                    context, 'engineering.reviews.record', review_record) as child:
                review_result = await self._implementation_results.record_review(child, contract)
                review_operation_id = self._works.read_command_operation_id(child)
        steps.append({'step_id': review_step['step_id'], 'kind': review_step['kind'],
            'operation': 'engineering.reviews.record', 'journal_request_id': review_record,
            'operation_id': review_operation_id, 'state': 'completed',
            'completion_semantics': 'independent_report_review_recorded_not_acceptance',
            'business': review_result})
        with ExitStack() as guards:
            with self._work_step_admission(context, 'engineering.reviews.record',
                    'report-correction-disposition-' + suffix[:48]) as child:
                method_result, validate_disposition = guards.enter_context(
                    self._implementation_results.guard_disposition(
                        child, work, report, review_result,
                        review_step_id=review_step['step_id']))
            steps.extend((
                {'step_id': disposition_step['step_id'], 'kind': disposition_step['kind'],
                 'operation': GUARD_STEP, 'journal_request_id': None, 'operation_id': None,
                 'state': 'completed',
                 'completion_semantics': 'method_disposition_pending_journal_commit',
                 'business': method_result},
                {'step_id': record_step['step_id'], 'kind': record_step['kind'],
                 'operation': GUARD_STEP, 'journal_request_id': None, 'operation_id': None,
                 'state': 'completed',
                 'completion_semantics': 'method_result_in_original_work_journal',
                 'business': method_result}))
            current_plan, current_binding, current_capture = source.validate_correction(
                context, checkpoint_ref=checkpoint)
            if (current_plan != plan or current_binding != binding
                    or current_capture != captured):
                raise ApplicationError('REPORT_CORRECTION_SOURCE_CHANGED')
            link = {'checkpoint_ref': asdict(checkpoint), 'plan_ref': asdict(plan_ref),
                    'submission_ref': asdict(subject)}
            outcome = {'work_id': work.work_id, 'action_id': value['action_id'],
                'revision': work.revision, 'state': 'completed', 'steps': tuple(steps),
                'completed_steps': tuple(step['step_id'] for step in steps),
                'method_result': method_result, 'report_correction': link}
            if recovery is not None:
                outcome['review_recovery'] = {
                    'source_proof_ref': recovery['proof_ref'],
                    'predecessor': recovery['proof']['predecessor'],
                    'new_review_ref': review_result['review_ref'],
                    'successor_operation_id': successor_claim.entry.operation_id}

            def validate(uow):
                validate_disposition(uow)
                original = uow.commands.get(context.key)
                tail = uow.commands.get(key)
                if (original is None or original.operation_id != parent.operation_id
                        or original.request_digest != digest or original.state != 'pending'
                        or original.version != plan['origin']['parent_version']
                        or tail is None or tail.operation != operation
                        or tail.request_digest != tail_digest or tail.state != 'pending'):
                    raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
                if successor_claim is not None:
                    current_successor = uow.commands.get(successor_key)
                    if (current_successor != successor_claim.entry
                            or current_successor.operation != 'engineering.report_correction.review_successor'
                            or current_successor.request_digest != successor_digest
                            or current_successor.state != 'pending'):
                        raise ApplicationError('REPORT_CORRECTION_PARENT_CONFLICT')
                    uow.commands.complete(successor_key,
                        expected_version=current_successor.version,
                        result_bytes=canonical_bytes(outcome), state='completed')
                # The parent and this one tail reservation close in the same
                # original transaction. There is no second result ledger.
                uow.commands.complete(key, expected_version=tail.version,
                    result_bytes=canonical_bytes({'parent_operation_id': parent.operation_id,
                                                 **link}), state='completed')

            return self._works.finish_invoke(
                context, parent.operation_id, outcome, validate=validate)

    async def _invoke_work_action(self, parameters, context, *, read_set=None):
        """Execute a declared action's steps in declaration order, inside one Work.

        The caller names the Work, the action, the action's inputs and an optional
        revision condition - never a command and never a step subset: order, step
        inputs (action_input / step_output / resource) and prerequisites come from
        the released declaration.

        Before anything runs, every step is pre-checked (mapping present, command
        bound and admitted, inputs assemblable) so a missing implementation or
        missing permission refuses the whole action instead of half-running it.

        The parent request is journaled: the same request with the same content
        replays the recorded output; the same request with different content is
        refused. Each step is delegated under a key derived from Work + action +
        revision + step + method version + inputs digest + the invoking request,
        so a replayed parent request reuses the step rows it already wrote.
        """
        import hashlib

        from ordessa_infrastructure.encoding import canonical_bytes, decode_json
        continuation = None
        is_continuation = type(parameters) is dict and parameters.get('invocation_version') == 2
        if 'operation' in parameters:
            # A caller-selected command would bypass the declared step order.
            raise ApplicationError('WORK_ACTION_OPERATION_NOT_CALLER_SELECTED')
        replay_input = self._works.continuation_replay if is_continuation else self._works.invoke_replay
        value, digest, replay = replay_input(parameters, context, read_set=read_set)
        if replay is not None:
            return replay
        read_request = 'work-view-' + hashlib.sha256(context.request_id.encode()).hexdigest()
        with self._work_step_admission(context, 'engineering.work.get', read_request) as read_context:
            view = self._work_queries.read({'work_id': value['work_id']}, read_context)
            binding = self._work_queries.read_binding(read_context, value['work_id'])
        if 'expected_revision' in value and value['expected_revision'] != view.get('revision'):
            raise ApplicationError('WORK_REVISION_STALE')
        action = next((item for item in view['actions']
                       if item['action_id'] == value['action_id']), None)
        if action is None:
            raise ApplicationError('WORK_ACTION_UNKNOWN')
        if action['disposition'] != 'available':
            raise ApplicationError('WORK_ACTION_UNAVAILABLE')
        declared = next((item for item in view['declared_actions']
                         if item['action_id'] == value['action_id']), None)
        if declared is None or declared.get('steps') is None:
            raise ApplicationError('WORK_ACTION_UNKNOWN')
        action_inputs = value.get('inputs') or {}
        method_version = (view.get('method_control') or {}).get('version')
        bound = {item.capability_id for item in self.bound_operation_capabilities().capabilities}
        mapped_steps = self._work_step_capabilities()
        # Pre-check every step against this composition before any effect. The
        # resource reads run inside the released declaration's guard, which is
        # what pins their identity, digest and content.
        guard_entry = getattr(self._method_guard, 'guard', None)
        if not callable(guard_entry):
            raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
        with guard_entry(context, binding.method_ref):
            step_resources = self._precheck_declared_steps(
                context, declared, binding, mapped_steps, bound, action_inputs)

        if is_continuation:
            continuation = self._prepare_work_continuation(value, context, binding, declared, digest)
            operation_id = continuation[2]
        else:
            operation_id, reserved = self._works.begin_invoke(context, digest)
            if operation_id is None:
                return reserved
        inputs_digest = hashlib.sha256(canonical_bytes(action_inputs)).hexdigest()
        method_result, result_validator = None, None
        with ExitStack() as result_guards:
            outputs = {}
            steps = []
            for step in declared['steps']:
                capability = mapped_steps[step['name']]
                payload = {}
                for item in step['inputs']:
                    if item['source_kind'] == 'action_input':
                        payload[item['name']] = action_inputs.get(item['source_name'])
                    elif item['source_kind'] == 'step_output':
                        payload[item['name']] = outputs.get(item['step_id'])
                    else:
                        # A declared resource is passed as the exact bytes the guard
                        # verified during pre-check; nothing is re-read or invented.
                        payload[item['name']] = step_resources.get(
                            (step['step_id'], item['name']))
                basis = '-'.join((str(value['work_id']), str(value['action_id']),
                                  'r%s' % view.get('revision'), str(step['step_id']),
                                  'm%s' % method_version, 'i%s' % inputs_digest[:32],
                                  str(context.request_id)))
                derived = (basis if len(basis) <= 512
                           else 'invoke-' + hashlib.sha256(basis.encode()).hexdigest())
                if continuation is not None and step['name'] == 'implement-approved-package':
                    derived = operation_id
                if step['name'] == 'check-package-admission':
                    guard = self._prepare_packages_steps
                    result = guard.check_package_admission(context, binding, inputs=payload)
                    state = 'completed'
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                                  'operation': GUARD_STEP, 'journal_request_id': None,
                                  'operation_id': None, 'state': state,
                                  'completion_semantics': 'declared_admission_checked_no_effect',
                                  'business': result})
                    if state != 'completed':
                        raise ApplicationError('WORK_ACTION_STEP_REJECTED')
                    outputs[step['step_id']] = result
                    continue
                if step['name'] == 'prepare-spec-kit-package':
                    port = self._declared_generation_port()
                    if port is None:
                        raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
                    materials = {key: value for key, value in payload.items()
                                 if key != 'inputs'}
                    with self._work_step_admission(context, capability, derived) as step_context:
                        result = port(step_context, binding, payload.get('inputs'),
                                      materials, action_id=parameters['action_id'],
                                      step_id=step['step_id'], profile_ref=action_inputs.get('profile'))
                        state = result.get('state', 'completed')
                        if state not in {'completed', 'failed'}:
                            raise ApplicationError('WORK_ACTION_GENERATION_RESULT_UNCONFIRMED')
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                                  'operation': 'engineering.executions.dispatch',
                                  'journal_request_id': derived,
                                  'operation_id': (result.get('run_association') or {}).get(
                                      'dispatch_key'),
                                  'state': state,
                                  'completion_semantics': result['completion_semantics'],
                                  'business': result})
                    if steps[-1]['state'] != 'completed':
                        outcome = {'work_id': value['work_id'], 'action_id': value['action_id'],
                                   'revision': view.get('revision'), 'state': 'failed',
                                   'failed_step': step['step_id'], 'steps': tuple(steps),
                                   'completed_steps': tuple(item['step_id'] for item in steps[:-1])}
                        return self._works.finish_invoke(
                            context, operation_id, outcome, state='rejected')
                    outputs[step['step_id']] = result
                    continue
                if step['name'] == 'independently-review-report':
                    import hashlib
                    record_request = 'implementation-review-record-' + hashlib.sha256(derived.encode()).hexdigest()
                    review_id = 'implementation-review-' + hashlib.sha256(derived.encode()).hexdigest()
                    with self._work_step_admission(context, 'engineering.reviews.request', derived) as step_context:
                        contract = await self._implementation_results.request_review(
                            step_context, binding, payload['report'], payload['reviewer_profile'],
                            review_id=review_id, step_id=step['step_id'], resources=payload)
                    with self._work_step_admission(context, 'engineering.reviews.record', record_request) as step_context:
                        result = await self._implementation_results.record_review(step_context, contract)
                        review_operation_id = self._works.read_command_operation_id(step_context)
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                        'operation': 'engineering.reviews.record', 'journal_request_id': record_request,
                        'operation_id': review_operation_id, 'state': 'completed',
                        'completion_semantics': 'independent_report_review_recorded_not_acceptance',
                        'business': result})
                    outputs[step['step_id']] = result
                    continue
                if step['name'] == 'resolve-one-operation-disposition':
                    review_step = next(item['step_id'] for item in declared['steps']
                                       if item['name'] == 'independently-review-report')
                    with self._work_step_admission(context, 'engineering.reviews.record', derived) as step_context:
                        method_result, result_validator = result_guards.enter_context(
                            self._implementation_results.guard_disposition(step_context, binding,
                                payload['report'], payload['review'], review_step_id=review_step))
                    result = method_result
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                        'operation': GUARD_STEP, 'journal_request_id': None, 'operation_id': None,
                        'state': 'completed', 'completion_semantics': 'method_disposition_pending_journal_commit',
                        'business': result})
                    outputs[step['step_id']] = result
                    continue
                if step['name'] == 'record-operation-result':
                    if method_result is None or payload.get('result') is not method_result:
                        raise ApplicationError('WORK_ACTION_RESULT_BINDING_MISMATCH')
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                        'operation': GUARD_STEP, 'journal_request_id': None, 'operation_id': None,
                        'state': 'completed', 'completion_semantics': 'method_result_in_original_work_journal',
                        'business': method_result})
                    outputs[step['step_id']] = method_result
                    continue
                with ExitStack() as review_guards:
                    refusal = None
                    with self._work_step_admission(context, capability, derived) as step_context:
                        if step['name'] == 'emit-explicitly-registered-change':
                            compare_id = next(item['step_id'] for item in declared['steps']
                                              if item['name'] == 'jev-review-explicit-change')
                            refusal = review_guards.enter_context(
                                self._review_change_steps.guard_failed_registration(
                                    step_context, binding, payload.get('review'),
                                    compare_result=outputs.get(compare_id), compare_step_id=compare_id,
                                    parent_request_id=context.request_id))
                        if refusal is not None:
                            result, _validate = refusal
                            state = 'failed'
                        elif step['name'] in _DECLARED_REVIEW_STEPS:
                            # Business step organisation stays with its owning use case.
                            result = await self._review_change_steps.run_declared_step(
                                step['name'], step_context, binding,
                                step_id=step['step_id'], parent_request_id=context.request_id,
                                payload=payload)
                            state = 'completed'
                        elif step['name'] == 'implement-approved-package':
                            owner = self._execution_dispatch
                            if continuation is not None:
                                answer = self._dispatch_work_continuation(step_context, continuation, action_inputs)
                            else:
                                assemble = getattr(owner, 'assemble_declared_work_dispatch', None)
                                if not callable(assemble):
                                    raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
                                envelope = assemble(binding, value['action_id'], step['step_id'], payload, step_context)
                                answer = await self._execute_declared_dispatch(envelope, step_context,
                                    work=binding, action_id=value['action_id'], step_id=step['step_id'])
                            if answer.outcome not in {'completed', 'failed'}:
                                # Preserve the already reserved parent as pending /
                                # query-only unknown. A missing native answer is not
                                # a recorded engineering failure or rework permit.
                                native = answer.value or {}
                                diagnostic = native.get('failure_diagnostic')
                                raise ApplicationError('WORK_ACTION_IMPLEMENTATION_RESULT_UNCONFIRMED',
                                    retry='reconcile', failure_diagnostic=diagnostic,
                                    failure_evidence_ref=(native.get('observation_ref')
                                        if diagnostic is not None else None),
                                    failure_evidence_linked=(diagnostic is not None
                                        and native.get('observation_ref') is not None))
                            state, result = answer.outcome, self._work_dispatch_business(answer)
                        else:
                            answer = await self.execute(capability, payload, step_context)
                            state, result = getattr(answer, 'status', None), getattr(answer, 'result', None)
                        step_operation_id = (
                            self._dispatch_attempt_operation(answer.value['binding'])
                            if step['name'] == 'implement-approved-package' and answer.value
                            else self._works.read_command_operation_id(step_context))
                    if (step['name'] == 'implement-approved-package' and state == 'completed'
                            and self._implementation_results.runnable):
                        report_request = 'implementation-report-' + hashlib.sha256(derived.encode()).hexdigest()
                        with self._work_step_admission(context, 'engineering.submissions.record_report', report_request) as step_context:
                            report = self._implementation_results.report_record(step_context, binding, result)
                            stored = self._implementation_results._completed(await self.execute(
                                'engineering.submissions.record_report', {'record': report}, step_context))
                            result = {**result, **stored}
                    # The original authority has now restored/revalidated the parent.
                    # The review guards remain held through its same-TX completion.
                    steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                                  'operation': capability,
                                  'journal_request_id': (None if step['name'] == 'implement-approved-package' else derived),
                                  'operation_id': step_operation_id,
                                  'state': state,
                                  'completion_semantics': ('formal_review_failed_no_successor'
                                      if refusal is not None else self._registered_completion(capability)),
                                  'business': result})
                    if state != 'completed':
                        outcome = {'work_id': value['work_id'], 'action_id': value['action_id'],
                                   'revision': view.get('revision'), 'state': 'failed',
                                   'failed_step': step['step_id'], 'steps': tuple(steps),
                                   'completed_steps': tuple(item['step_id'] for item in steps[:-1])}
                        return self._works.finish_invoke(context, operation_id, outcome, state='rejected',
                            validate=refusal[1] if refusal is not None else None)
                    outputs[step['step_id']] = result
            outcome = {'work_id': value['work_id'], 'action_id': value['action_id'],
                       'revision': view.get('revision'), 'state': 'completed',
                       'steps': tuple(steps),
                       'completed_steps': tuple(item['step_id'] for item in steps)}
            if method_result is not None:
                outcome['method_result'] = method_result
            if continuation is not None:
                outcome['continuation'] = {'operation_id': operation_id,
                    'attempt': continuation[0].attempt,
                    'origin_operation_ref': continuation[0].origin.execution_operation_ref}
            return self._works.finish_invoke(context, operation_id, outcome, validate=result_validator)

    @staticmethod
    def _work_dispatch_business(answer):
        """Journal a detached native binding, never opaque objects or acceptance."""
        from dataclasses import asdict
        from ordessa_infrastructure.encoding import decode_json
        from ...domain.changes.dispatch_codec import encode_dispatch
        from ..usecases.owner_operations import OwnerOperationResult
        if (type(answer) is not OwnerOperationResult
                or answer.engineering_completed is not False or answer.accepted is not False):
            raise ApplicationError('OWNER_OPERATION_RESULT_AUTHORITY_MISMATCH')
        native = answer.value or {}
        binding, observation = native.get('binding'), native.get('observation_ref')
        from ...domain.changes.agent_dispatch import AgentWorkDispatchBinding
        from ...domain.changes.agent_dispatch_codec import encode_agent_dispatch
        encoded = (None if binding is None else
                   encode_agent_dispatch(binding) if type(binding) is AgentWorkDispatchBinding
                   else encode_dispatch(binding))
        return {'binding': None if encoded is None else decode_json(encoded),
                'observation_ref': None if observation is None else asdict(observation),
                'params_assembly': native.get('params_assembly'), 'phase': answer.dispatch_phase,
                'reason': answer.reason, 'engineering_completed': False, 'accepted': False}

    @staticmethod
    def _dispatch_attempt_operation(binding):
        from ...domain.changes.agent_dispatch import AgentWorkDispatchBinding
        if type(binding) is AgentWorkDispatchBinding:
            return binding.engineering_attempt_ref
        from ...domain.changes.dispatch import DispatchBinding
        if type(binding) is not DispatchBinding:
            raise ApplicationError('OWNER_OPERATION_RESULT_AUTHORITY_MISMATCH')
        return binding.execution_operation_ref

    async def _execute_declared_dispatch(self, parameters, context, *, work, action_id, step_id):
        """Bind transient step assembly to this exact admitted child context.

        This token authenticates no caller and grants no permission; the real
        access, Grant and original Unit authorities still guard every effect.
        It prevents a serialized payload from choosing another enclosing Work.
        """
        request = parameters.get('dispatch') if type(parameters) is dict else None
        if (type(request) is not dict or work.scope != context.scope
                or (request.get('work_id'), request.get('action_id'), request.get('step_id'))
                   != (work.work_id, action_id, step_id)):
            raise ApplicationError('WORK_ACTION_DISPATCH_BINDING_MISMATCH')
        token = self._work_dispatch_scope.set((context, canonical_bytes(parameters)))
        try:
            return await self.execute(EXECUTION_DISPATCH, parameters, context)
        finally:
            self._work_dispatch_scope.reset(token)

    def _registered_completion(self, operation):
        """Registered completion semantics of a command, or None if unregistered."""
        from ..orchestration.method_bridge import command_capabilities
        for item in command_capabilities().capabilities:
            if getattr(item, 'capability_id', None) != operation:
                continue
            contract = getattr(item, 'contract', None)
            if isinstance(contract, dict):
                return contract.get('completion')
            return getattr(item, 'completion', None)
        return None

    def _work_step_admission(self, context, operation, request_id):
        """Ask the original authority to issue this declared step's context."""
        admit = getattr(self._access, 'admit_work_step', None)
        if not callable(admit):
            raise ApplicationError('WORK_ACTION_STEP_ADMISSION_UNAVAILABLE')
        return admit(context, operation, request_id=request_id)

    def _check_work_capability(self, context, operation):
        check = getattr(self._access, 'check_work_capability', None)
        if not callable(check):
            raise ApplicationError('ACTION_EXECUTE_NOT_PERMITTED')
        return check(context, operation)

    def _work_step_capabilities(self):
        """Declared method step name -> capability bound by this composition.

        A step is mapped only when this composition both binds the command it
        needs and can assemble that step's declared inputs into the command's
        payload. Everything else stays unmapped and is reported as unsupported
        rather than available.

        Today only the two native steps are mapped, to the real dispatch
        capability. The review-change steps (`jev-review-explicit-change`,
        `record-explicit-review-result`, `emit-explicitly-registered-change`) and
        the admission/review/disposition/record steps of the package actions are
        NOT mapped: their assembly (review criteria/prompt/schemas/binding and
        the plan, the package admission, the disposition resolution, the
        operation-result record) is not implemented yet, so those actions refuse
        instead of running a caller-selected subset.
        """
        mapped = {}
        if getattr(self._execution_dispatch, 'declared_implementation_ready', False) is True:
            mapped['implement-approved-package'] = 'engineering.executions.dispatch'
        if self.declared_generation_ready:
            # Unit generation is only mapped once this process holds the real
            # dispatch owner; the guard step is implemented without any command.
            mapped['prepare-spec-kit-package'] = 'engineering.executions.dispatch'
        mapped['check-package-admission'] = GUARD_STEP
        if self._review_change_steps.runnable:
            # Mapped only when this process holds the review bindings *and* the
            # composition's review runner; otherwise the action refuses.
            mapped.update({
                'jev-review-explicit-change': 'engineering.reviews.request',
                'record-explicit-review-result': 'engineering.reviews.record',
                'emit-explicitly-registered-change': 'engineering.proposals.associate_review',
            })
        if self._implementation_results.runnable:
            mapped.update({
                'independently-review-report': 'engineering.reviews.request',
                'resolve-one-operation-disposition': 'engineering.reviews.record',
                'record-operation-result': GUARD_STEP,
            })
        return mapped

    async def _run_declared_step_command(self, operation, payload, context):
        """Run one step's command through the ordinary Service entry."""
        return await self.execute(operation, payload, context)

    def _precheck_declared_steps(self, context, declared, binding, mapped_steps,
                                 bound, action_inputs):
        """Every declared step must be implementable and permitted before any effect.

        Returns the resolved resource content per (step, input), read and verified
        inside the released declaration's guard, so execution uses exactly the
        bytes the guard pinned rather than re-reading them.
        """
        resources = {}
        if any(step['name'] == 'independently-review-report' for step in declared['steps']):
            for operation in ('engineering.submissions.record_report', 'engineering.reviews.record'):
                if operation not in bound:
                    raise ApplicationError('CAPABILITY_NOT_BOUND')
                self._check_work_capability(context, operation)
        for step in declared['steps']:
            capability = mapped_steps.get(step['name'])
            if capability is None:
                raise ApplicationError('WORK_ACTION_STEP_UNIMPLEMENTED')
            if capability == GUARD_STEP:
                # Guard-only step: executed by the orchestration straight from
                # real records; no command, no effect, nothing to be permitted.
                for item in step['inputs']:
                    if item['source_kind'] == 'action_input' and item['source_name'] not in action_inputs:
                        raise ApplicationError('WORK_ACTION_INPUT_MISSING')
                continue
            if capability not in bound:
                raise ApplicationError('CAPABILITY_NOT_BOUND')
            for item in step['inputs']:
                if item['source_kind'] == 'action_input':
                    if item['source_name'] not in action_inputs:
                        raise ApplicationError('WORK_ACTION_INPUT_MISSING')
                elif item['source_kind'] == 'step_output':
                    if not any(prior['step_id'] == item['step_id']
                               for prior in declared['steps']):
                        raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
                else:
                    exact = self._require_step_resource(context, binding.method_ref,
                                                        item['source_name'])
                    resources[(step['step_id'], item['name'])] = self._method_guard.read_resource(
                        context, exact)
            if capability == GUARD_STEP:
                continue
            try:
                self._check_work_capability(context, capability)
            except Exception:
                raise ApplicationError('ACTION_EXECUTE_NOT_PERMITTED') from None
        return resources

    def _require_step_resource(self, context, method_ref, resource_id):
        """Resolve and read one declared step resource through the method guard.

        `resource_ref` pins the released snapshot's exact resource (identity and
        digest) and `read_resource` reads and verifies that content, so an
        undeclared name, a different method, or content that does not match the
        released digest is refused here instead of being read from elsewhere.
        """
        guard = self._method_guard
        if not callable(getattr(guard, 'resource_ref', None)):
            raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
        exact = guard.resource_ref(context, method_ref, resource_id)
        if (getattr(exact, 'resource_id', None) != resource_id
                or getattr(exact, 'method_ref', None) != method_ref):
            raise ApplicationError('WORK_ACTION_RESOURCE_UNDECLARED')
        if not callable(getattr(guard, 'read_resource', None)):
            raise ApplicationError('WORK_ACTION_STEP_ASSEMBLY_MISSING')
        guard.read_resource(context, exact)
        return exact

    def _work_action_execute_permission(self, action_id, capabilities, context):
        """Execute permission for one declared action, from the real access owner.

        Read admission is the owning query's own `access.require`. Execution
        reuses the same command access authority: every command the action's
        mapped steps resolve to must be admitted for this caller. Nothing is
        granted by default and no credential is minted here.
        """
        if context is None:
            return False
        mapped = tuple(capability for capability in (capabilities or ())
                       if capability is not None and capability != GUARD_STEP)
        if not any(capability == GUARD_STEP for capability in (capabilities or ())) and not mapped:
            return False
        if not mapped:
            return True
        try:
            for operation in mapped:
                self._check_work_capability(context, operation)
        except Exception:
            return False
        return True

    @staticmethod
    def input_schema(operation, *, dispatch_descriptor=None, report_descriptor=None):
        if operation==EXECUTION_DISPATCH:
            from ..orchestration.owner_capabilities import owner_capabilities
            descriptor=(dispatch_descriptor if dispatch_descriptor is not None else
                        next(d for d in owner_capabilities() if d.capability_id==operation))
            return {'$schema':'https://json-schema.org/draft/2020-12/schema',
                    '$id':descriptor.contract['input_schema_id'], **descriptor.contract['input_schema']}
        if type(operation) is not str or operation not in SUPPORTED_COMMANDS:
            raise ApplicationError("OPERATION_UNAVAILABLE")
        if operation == "engineering.submissions.record_report":
            from ..contracts.submissions import agent_report_input_schema
            if report_descriptor is not None:
                from ..orchestration.owner_capabilities import agent_report_capability
                if report_descriptor != agent_report_capability():
                    raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
            return agent_report_input_schema()
        if operation in (ASSIGN_REVIEWER, REVOKE_REVIEWER):
            return reviewer_assignment_schema(operation)
        if operation == 'engineering.packages.freeze':
            from ..orchestration.owner_capabilities import owner_capabilities
            descriptor=next(d for d in owner_capabilities() if d.capability_id==operation)
            return {'$schema':'https://json-schema.org/draft/2020-12/schema',
                    '$id':'urn:ordessa:engineering:implementation-content:2',
                    **descriptor.contract['input_schema']}
        if operation in _ARTIFACT_COMMANDS:
            return artifact_schema(operation)
        if operation in _REVIEW_COMMANDS:
            if operation == "engineering.reviews.record":
                return review_command_schema(operation)
            return review_schema(operation)
        if operation in _PROPOSAL_COMMANDS:
            return proposal_schema(operation)
        if operation in SUPPORTED_WORK_COMMANDS:
            return works_input_schema(operation)
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
    def command_request_digest(operation, parameters, context, reads, *, work_selector=None):
        """Exact original owner identity used to correlate a declared run step."""
        if work_selector is not None and operation != 'engineering.reviews.request':
            raise ApplicationError('WORK_REVIEW_SELECTOR_UNSUPPORTED')
        if operation == 'engineering.reviews.record':
            return ReviewUseCases.record_command_request_digest(parameters, context, reads)
        if operation=='engineering.packages.freeze':
            if reads != ReadSet(context.scope,()):
                raise ApplicationError('PACKAGE_READ_SET_UNSUPPORTED')
            return ImplementationUseCases.package_request_digest(
                decode_package(canonical_bytes(parameters['record'])),context)
        if operation == 'engineering.submissions.record_report':
            if reads != ReadSet(context.scope,()):
                raise ApplicationError('SUBMISSION_REPORT_READ_SET_UNSUPPORTED')
            return SubmissionUseCases.report_request_digest(
                decode_submission(canonical_bytes(parameters['record'])), context)
        import hashlib
        from ..contracts.commands import request_digest, read_set_projection, artifact_read_set_projection
        from ...domain.common.models.values import Digest
        schema=EngineeringService.input_schema(operation)
        projection=artifact_read_set_projection(reads) if operation.startswith('engineering.artifacts.') else read_set_projection(reads)
        if work_selector is not None:
            from ..contracts.method_work import work_review_selector_projection
            projection = {'read_set': projection,
                          'work_review_selector': work_review_selector_projection(work_selector)}
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
        from ...domain.changes.agent_submission_report import AgentSubmissionReport
        if type(record) is not AgentSubmissionReport:
            raise ApplicationError('SUBMISSION_HISTORICAL_REPORT_READ_ONLY')
        return self._submission_reports.record_report(record, context,
            records=self._execution_records, blobs=self._blobs,
            query_factory=self._execution_query_factory)

    @contextmanager
    def _report_content_review_guard(self, operation, parameters, context):
        if operation not in {'engineering.reviews.request', 'engineering.reviews.record'}:
            yield
            return
        owner = getattr(self._submission_reports, 'report_source', None)
        source = getattr(owner, 'content_rework', None)
        if source is None:
            yield
            return
        self._access.require(context, operation)
        from ...domain.reviews.codec import decode_plan
        from ...domain.reviews.refs import SubmissionRef
        if type(parameters) is not dict:
            raise ApplicationError('INVALID_INPUT')
        if operation == 'engineering.reviews.request':
            plan = decode_plan(canonical_bytes(parameters.get('plan')))
        else:
            with self._factory.begin(context.scope, 'read') as uow:
                plan = uow.reviews.get_plan(parameters.get('review_id'))
        targets = plan.requirement.expected_targets.targets
        if len(targets) != 1 or type(targets[0].ref) is not SubmissionRef:
            yield
            return
        with self._factory.begin(context.scope, 'read') as uow:
            submission = uow.submissions.resolve(targets[0].ref)
        if submission.checkpoint_ref is None or not source._is_checkpoint(submission.checkpoint_ref):
            yield
            return
        with source.guard_review(context, plan, submission):
            yield

    async def execute(self, operation, parameters, context, *, read_set=None, work_selector=None):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if type(operation) is not str:
            raise ApplicationError("INVALID_ARGUMENT")
        if work_selector is not None:
            from ..contracts.method_work import WorkReviewSelector
            if operation != 'engineering.reviews.request':
                raise ApplicationError('WORK_REVIEW_SELECTOR_UNSUPPORTED')
            if type(work_selector) is not WorkReviewSelector or work_selector.scope != context.scope:
                raise ApplicationError('WORK_REVIEW_SELECTOR_INVALID')
        if operation==EXECUTION_DISPATCH:
            if self._access is None:
                raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
            self._access.require(context,operation)
            active = self._work_dispatch_scope.get()
            if (active is None or active[0] is not context
                    or active[1] != canonical_bytes(parameters)):
                raise ApplicationError('WORK_ACTION_DISPATCH_CONTEXT_REQUIRED')
            if self._execution_dispatch is None:
                raise ApplicationError('DISPATCH_AUTHORITY_UNAVAILABLE')
            if read_set is not None:
                raise ApplicationError('DISPATCH_READ_SET_UNSUPPORTED')
            from jsonschema import Draft202012Validator
            descriptor = getattr(self._execution_dispatch, 'dispatch_descriptor', None)
            if not Draft202012Validator(self.input_schema(operation,
                    dispatch_descriptor=descriptor)).is_valid(parameters):
                raise ApplicationError('INVALID_INPUT')
            returned = self._execution_dispatch.execute(operation,parameters,context)
            # Only this explicitly bound Agent interface awaits its original
            # async writer. No business transaction/method lock encloses await.
            if descriptor is not None and descriptor.interface_version == '2':
                import inspect
                if not inspect.isawaitable(returned):
                    raise ApplicationError('AGENT_DISPATCH_ASYNC_OWNER_REQUIRED')
                return await returned
            return returned
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
        with self._report_content_review_guard(operation, parameters, context):
            if work_selector is not None:
                answer = handler(parameters, context, read_set=read_set, work_selector=work_selector)
            else:
                answer = handler(parameters, context, read_set=read_set)
            # Only a handler that itself delegates to another command (Work invoke)
            # is async; every other handler stays sync. No new dispatch path.
            import inspect
            if inspect.isawaitable(answer):
                return await answer
            return answer

    async def query(self, query, parameters, context):
        if query in IMPLEMENTATION_QUERIES:
            return self._implementation_invoke(query, parameters, context)
        if query == "engineering.work.get":
            return self._work_queries.read(parameters, context)
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
