"""Finite application entry point over the existing command/UoW owners.

Composition supplies authentication and control admission. No method policy,
dynamic handler lookup, legacy workflow fallback or second journal lives here.
The async surface follows E6; handlers currently perform bounded synchronous
SQLite work and never suspend with an open transaction.
"""
from contextlib import ExitStack
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
            source_bindings_valid = source_review_authority(admission,
                getattr(admission, "source_materials", None),
                getattr(admission, "method_guard", None), source_bindings)
            valid = (type(owner) is ReviewUseCases
                and owner.factory is factory and owner.access is access
                and type(admission) is EngineeringReviewAdmission
                and admission.factory is factory
                and getattr(getattr(admission, "methods", None), "factory", None) is factory
                and (legacy_bindings_valid or source_bindings_valid)
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
            and callable(getattr(dispatch, "execute", None)))
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
                                           unit_ref_resolver=None):
        """Attach the composition's existing Unit transport to the declared step.

        The handles are the same objects the implementation dispatch line already
        uses; no Unit, store, permission or credential is created here. The
        The same dispatch owner is retained for the generation port and the
        original Unit effect-write guard. Each call uses its admitted context.
        """
        if blobs is None or execution is None:
            raise ApplicationError('CAPABILITY_NOT_BOUND')
        self._declared_generation_handles = {'blobs': blobs, 'execution': execution,
                                              'unit_ref_resolver': unit_ref_resolver}
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
                                      validation=self._prepare_packages_steps.validate_generated_package,
                                      registration_guard=self._prepare_packages_steps.verify_generated_registration)

    def __init__(self, factory, access, *, proposal_control_admission=None,
                 review_admission=None, review_control=None, blobs=None, conversation_admission=None,
                 acceptance_admission=None, submission_source=None, current_wait_bindings=None,
                 submission_report_source=None, execution_records=None, execution_query_factory=None,
                 implementation_routes=None, execution_dispatch=None,
                 source_materials=None, method_guard=None, source_review_bindings=None,
                 reviewer_assignments=None, review_run=None, review_plan_factory=None):
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
        if 'operation' in parameters:
            # A caller-selected command would bypass the declared step order.
            raise ApplicationError('WORK_ACTION_OPERATION_NOT_CALLER_SELECTED')
        value, digest, replay = self._works.invoke_replay(parameters, context, read_set=read_set)
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

        operation_id, reserved = self._works.begin_invoke(context, digest)
        if operation_id is None:
            return reserved
        inputs_digest = hashlib.sha256(canonical_bytes(action_inputs)).hexdigest()
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
                    else:
                        answer = await self.execute(capability, payload, step_context)
                        state, result = getattr(answer, 'status', None), getattr(answer, 'result', None)
                    step_operation_id = self._works.read_command_operation_id(step_context)
                # The original authority has now restored/revalidated the parent.
                # The review guards remain held through its same-TX completion.
                steps.append({'step_id': step['step_id'], 'kind': step['kind'],
                              'operation': capability, 'journal_request_id': derived,
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
        return self._works.finish_invoke(context, operation_id, outcome)

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
        mapped = {
            # Native steps resolved through the real dispatch capability. It is
            # only "bound" when this process composed the dispatch owner, so an
            # unbound dispatch is reported (CAPABILITY_NOT_BOUND) and never as
            # available merely because the name exists in the frozen registry.
            'implement-approved-package': 'engineering.executions.dispatch',
        }
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
        with self._factory.begin(context.scope, 'read') as uow:
            row = uow.dispatch.by_operation(record.execution_ref.operation_ref, context.scope)
            binding = decode_dispatch(row['binding_bytes'])
        invocation = self._execution_query_factory(binding)
        return self._submission_reports.record_report(record, context,
            records=self._execution_records, blobs=self._blobs, query_invocation=invocation)

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
