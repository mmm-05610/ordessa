"""Finite wire projection of the public EngineeringService and MethodBridge.

No database, issuer, Work scheduler or consent authority is created here.
Composition binds the original library/UoW and the current instance authority.
"""
from dataclasses import asdict, dataclass

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_engineering.application.contracts.commands import CommandResult
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.application.api import (
    BlobRef, DispatchBinding, EngineeringService, EXECUTION_DISPATCH, FailureDiagnostic,
    OwnerOperationResult, SUPPORTED_COMMANDS,
)
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision
from ordessa_engineering.domain.changes.models import Change, Proposal, ProposalControl
from ordessa_engineering.domain.reviews.models import ControlledReview
from ordessa_engineering.domain.approvals.consent import (
    ApprovalGrant, AuthorizationIntent, ConversationNotice,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server_plugin_api import ServerMethodDescriptor
from ordessa_server_plugin_api.wire_errors import WireError

from .engineering import EngineeringCommandAccess
from ordessa_engineering.application.contracts.implementation_routes import (
    IMPLEMENTATION_COMMANDS as DISPATCH_COMMANDS,
    IMPLEMENTATION_QUERIES as DISPATCH_QUERIES,
)

CAPABILITIES_METHOD = "engineering.capabilities"
REVIEW_REQUEST_QUERY = 'engineering.reviews.get_request'
RUN_WAIT_QUERY = 'engineering.runs.get_wait'
CONTRACT_VERSION = "engineering-wire/1"
SUPPORTED_QUERIES = EngineeringService.supported_queries
SUPPORTED_METHODS = tuple(dict.fromkeys((CAPABILITIES_METHOD, *SUPPORTED_COMMANDS, *SUPPORTED_QUERIES,
    *DISPATCH_COMMANDS, *DISPATCH_QUERIES, REVIEW_REQUEST_QUERY, RUN_WAIT_QUERY)))


@dataclass(frozen=True)
class EngineeringApplicationPorts:
    """Trusted owner construction inputs; never accepted from wire JSON."""
    proposal_control_admission: object = None
    review_admission: object = None
    review_control: object = None
    blobs: object = None
    conversation_admission: object = None
    dispatch_routes_factory: object = None
    review_presentation: object = None
    acceptance_admission: object = None
    submission_source: object = None
    current_wait_bindings: object = None
    submission_report_source: object = None
    execution_records: object = None
    execution_query_factory: object = None
    # Explicit Agent execution is independent of the historical Unit report trio.
    agent_execution_records: object = None
    agent_execution_query_factory: object = None
    method_guard: object = None
    source_materials: object = None
    execution_dispatch_binder: object = None
    declared_generation_binder: object = None
    reviewer_assignments: object = None
    # Bound by trusted composition; request JSON never selects a reviewer.
    review_run: object = None
    review_plan_factory: object = None


def _failure(error):
    code = error.code
    if code in {"OPERATION_UNAVAILABLE", "QUERY_UNAVAILABLE", "REFERENCE_OWNER_UNAVAILABLE"}:
        family = "CAPABILITY_UNSUPPORTED"
    elif code.startswith("ACCESS_") or code == "SCOPE_MISMATCH":
        family = "FORBIDDEN"
    elif "CONFLICT" in code:
        family = "CONFLICT"
    elif code.endswith("NOT_FOUND"):
        family = "NOT_FOUND"
    elif code.startswith("INVALID_") or code.startswith("METHOD_"):
        family = "INVALID_REQUEST"
    else:
        family = "UNAVAILABLE"
    details = {
        "internalCode": code, "source_error": {"owner": "engineering", "code": code},
        "retryable": False, "recoveryAction": "queryOriginalRequest" if error.retry == "reconcile" else "inspectRequest",
    }
    if type(error.failure_diagnostic) is FailureDiagnostic:
        details['failureDiagnostic'] = error.failure_diagnostic.to_dict()
    if type(error.failure_evidence_ref) is BlobRef:
        details['failureEvidenceRef'] = asdict(error.failure_evidence_ref)
        details['failureEvidenceLinked'] = error.failure_evidence_linked
    return WireError(family, "Engineering request could not be completed", details)


def _command(result, scope, request_id):
    if type(result) is not CommandResult:
        raise ApplicationError("INVALID_RESULT")
    return {"contract_version": CONTRACT_VERSION, "record_type": "command_result",
        "scope": asdict(scope), "request_id": request_id,
        "authority_id": result.authority_id, "operation_id": result.operation_id,
        "status": result.status, "result": result.result,
        "status_query": {"method": "engineering.commands.get", "parameters": {"request_id": request_id}}}


def _owner_result(result, scope, request_id):
    if (type(result) is not OwnerOperationResult
            or result.operation != EXECUTION_DISPATCH
            or result.outcome not in {"completed", "failed", "unknown"}
            or type(result.engineering_completed) is not bool
            or type(result.accepted) is not bool
            or (result.dispatch_phase is not None and type(result.dispatch_phase) is not str)
            or (result.reason is not None and type(result.reason) is not str)):
        raise ApplicationError("INVALID_RESULT")
    value = result.value
    if value is not None:
        if type(value) is not dict or set(value) != {"binding", "observation_ref"}:
            raise ApplicationError("INVALID_RESULT")
        binding, observation = value["binding"], value["observation_ref"]
        if type(binding) is not DispatchBinding or (observation is not None and type(observation) is not BlobRef):
            raise ApplicationError("INVALID_RESULT")
        value = {"binding": binding.projection(),
            "observation_ref": None if observation is None else {
                "digest": asdict(observation.digest), "byte_length": observation.byte_length,
                "media_type": observation.media_type, "storage_object_id": observation.storage_object_id}}
    return {"contract_version": CONTRACT_VERSION, "record_type": "owner_operation_result",
        "scope": asdict(scope), "request_id": request_id, "operation": result.operation,
        "outcome": result.outcome, "value": value,
        "engineering_completed": result.engineering_completed, "accepted": result.accepted,
        "dispatch_phase": result.dispatch_phase, "reason": result.reason}


def _record(value, query):
    from ordessa_engineering.domain.changes.adoption import AcceptanceReceipt
    if type(value) is AcceptanceReceipt:
        return "AcceptanceReceipt", asdict(value)
    if type(value) in (Artifact, Change, ProposalControl, ApprovalGrant,
                      AuthorizationIntent, ConversationNotice):
        return type(value).__name__, asdict(value)
    if type(value) in (ArtifactRevision, Proposal):
        return type(value).__name__, value.projection()
    if type(value) is ControlledReview:
        return "ControlledReview", {"record": value.record.projection(), "control": asdict(value.control)}
    projections = {
        "engineering.approvals.get_control": "ApprovalControl",
        "engineering.approvals.get_budget": "ApprovalBudget",
        "engineering.approvals.get_challenge": "ApprovalChallenge",
        "engineering.approvals.list_pending": "PendingApprovals",
        "engineering.runs.get_wait": "RunWait",
        "engineering.work.get": "MethodWork",
        "engineering.operations.get": "Operation",
        "engineering.work.current_condition": "CurrentCondition",
    }
    if type(value) is dict and query in projections:
        if query == 'engineering.work.get':
            # Work's declaration/query API uses immutable tuples. Project its
            # nested sequences into JSON arrays before the strict wire encoder.
            value = decode_json(safe_json(value).encode('utf-8'))
        return projections[query], value
    raise ApplicationError("REFERENCE_OWNER_UNAVAILABLE")


class EngineeringWireBinding:
    """Exact-scope, authenticated facade calls, including serialization under lease."""
    def __init__(self, factory, authority, *, scope, proposal_control_admission=None,
                 application_ports_factory=None):
        if type(scope) is not Scope:
            raise ValueError("Explicit realm/project scope required")
        self.scope = scope
        self.factory = factory
        self.access = EngineeringCommandAccess(authority)
        ports = (application_ports_factory(factory, self.access, scope)
                 if application_ports_factory is not None else EngineeringApplicationPorts(
                     proposal_control_admission=proposal_control_admission))
        if type(ports) is not EngineeringApplicationPorts:
            raise ValueError("Explicit Engineering owner ports required")
        if ports.review_run is not None and not callable(ports.review_run):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        selected_plan = ports.review_plan_factory
        declared_plan = callable(getattr(selected_plan, 'implementation_plan', None))
        if (selected_plan is not None and (
                not callable(selected_plan) and not declared_plan
                or declared_plan and getattr(selected_plan, 'factory', None) is not factory)):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.ports = ports
        self.dispatch_routes = (ports.dispatch_routes_factory(factory, self.access, scope)
            if ports.dispatch_routes_factory is not None else None)
        if self.dispatch_routes is not None and self.dispatch_routes.factory is not factory:
            raise ValueError('Original Engineering dispatch authority required')
        report_ports = {}
        if any(value is not None for value in (ports.submission_report_source,
                ports.execution_records, ports.execution_query_factory)):
            if (ports.submission_report_source is None or ports.execution_records is None
                    or not callable(ports.execution_query_factory)):
                raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
            report_ports = {'submission_report_source':ports.submission_report_source,
                'execution_records':ports.execution_records,
                'execution_query_factory':ports.execution_query_factory}
        self.agent_work_execution = any(value is not None for value in (
            ports.agent_execution_records, ports.agent_execution_query_factory))
        if self.agent_work_execution:
            if (ports.agent_execution_records is None
                    or not callable(ports.agent_execution_query_factory)
                    or ports.submission_report_source is not None
                    or ports.execution_records is not None or ports.execution_query_factory is not None
                    or ports.execution_dispatch_binder is None
                    or getattr(ports.method_guard, 'factory', None) is not factory
                    or getattr(ports.source_materials, 'factory', None) is not factory
                    or getattr(ports.agent_execution_records, 'blob_store', None) is not ports.blobs
                    or not callable(getattr(ports.agent_execution_records, 'capture_dispatch', None))
                    or not callable(getattr(ports.agent_execution_records, 'read_agent_reference', None))):
                raise ApplicationError('AGENT_WORK_EXECUTION_AUTHORITY_UNBOUND')
            report_ports = {'execution_records':ports.agent_execution_records,
                            'execution_query_factory':ports.agent_execution_query_factory}
        self.service = build_engineering_service(factory, EngineeringPorts(access=self.access,
            proposal_control_admission=ports.proposal_control_admission,
            review_admission=ports.review_admission, review_control=ports.review_control,
            blobs=ports.blobs, conversation_admission=ports.conversation_admission,
            acceptance_admission=ports.acceptance_admission,submission_source=ports.submission_source,
            current_wait_bindings=ports.current_wait_bindings,
            reviewer_assignments=ports.reviewer_assignments,
            review_run=ports.review_run,
            review_plan_factory=ports.review_plan_factory,
            method_guard=ports.method_guard,source_materials=ports.source_materials,
            implementation_routes=self.dispatch_routes, **report_ports))
        self.execution_dispatch = None
        self.declared_generation_dispatch = None
        if (ports.execution_dispatch_binder is not None
                and ports.declared_generation_binder is not None):
            raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
        if ports.declared_generation_binder is not None:
            if not callable(ports.declared_generation_binder):
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
            generation = ports.declared_generation_binder(self.service)
            if (generation is None or generation is not self.service.declared_generation_dispatch
                    or getattr(generation, 'factory', None) is not factory
                    or getattr(generation, 'access', None) is not self.access
                    or not self.service.declared_generation_ready
                    or not callable(getattr(generation, 'dispatch_generation', None))
                    or not callable(getattr(generation, 'acquire_effect_write', None))):
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
            self.declared_generation_dispatch = generation
        if ports.execution_dispatch_binder is not None:
            if not callable(ports.execution_dispatch_binder):
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
            self.execution_dispatch = ports.execution_dispatch_binder(self.service)
            if (getattr(self.execution_dispatch, "factory", None) is not factory
                    or getattr(self.execution_dispatch, "access", None) is not self.access
                    or not callable(getattr(self.execution_dispatch, "execute", None))):
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
            capabilities = self.service.bound_operation_capabilities()
            if not any(getattr(item, "capability_id", None) == EXECUTION_DISPATCH
                       for item in capabilities.capabilities):
                raise ApplicationError("DISPATCH_AUTHORITY_MISMATCH")
        self.bridge = MethodBridge()

    def capabilities(self):
        # Work reads are always part of the query grammar, but only project
        # persisted Work when the original Work source is bound to this same
        # EngineeringService. These two bound operations are validated by the
        # service against its retained MethodRunBindings and current-wait
        # reader; they say nothing about method publication or readiness.
        bound_capabilities = self.service.bound_operation_capabilities().capabilities
        bound_operations = {item.capability_id for item in bound_capabilities}
        work_projection = "engineering.work.start" in bound_operations
        commands = []
        for descriptor in bound_capabilities:
            commands.append({"operation": descriptor.capability_id,
                "interface_version": descriptor.interface_version,
                "contract_digest": descriptor.contract_digest,
                "contract": descriptor.contract})
        if self.dispatch_routes is not None:
            commands.extend({'operation':name,'interface_version':'1',
                'contract':'ordessa.product-dispatch-route/1'} for name in DISPATCH_COMMANDS)
        active = SUPPORTED_METHODS if self.dispatch_routes is not None else tuple(
            name for name in SUPPORTED_METHODS if name not in (*DISPATCH_COMMANDS,*DISPATCH_QUERIES))
        if self.execution_dispatch is not None:
            active = tuple(dict.fromkeys((*active, EXECUTION_DISPATCH)))
        if self.agent_work_execution and self.ports.submission_report_source is None:
            active = tuple(name for name in active if name != 'engineering.submissions.record_report')
            commands = [item for item in commands
                if item['operation'] != 'engineering.submissions.record_report']
        return {"contract_version": CONTRACT_VERSION, "scope": asdict(self.scope),
            "supported_methods": list(active), "commands": commands,
            "queries": list(dict.fromkeys((*SUPPORTED_QUERIES, REVIEW_REQUEST_QUERY, RUN_WAIT_QUERY,
                *(DISPATCH_QUERIES if self.dispatch_routes is not None else ())))),
            "supports": {"exact_queries": True, "method_slot_bridge": True,
                "work_projection": work_projection, "durable_events": False,
                "consent": False, "dispatch": self.execution_dispatch is not None, "semantic_review": False,
                "consent_recording": self.ports.conversation_admission is not None
                    and self.ports.review_admission is not None,
                "did_apply": False, "grant_budget_consumption": False}}

    def _scope(self, params):
        try:
            scope = Scope(**params["scope"])
        except (TypeError, ValueError, KeyError):
            raise WireError("INVALID_REQUEST", "Explicit realm/project scope required") from None
        if scope != self.scope:
            raise WireError("FORBIDDEN", "Engineering scope is not selected",
                {"internalCode": "SCOPE_MISMATCH", "retryable": False})
        return scope

    async def invoke(self, operation, params, caller):
        scope = self._scope(params)
        try:
            with self.access.admit(caller, scope, operation,
                    request_id=params["requestId"], trace_id=params["requestId"]) as context:
                if operation == CAPABILITIES_METHOD:
                    value = self.capabilities()
                elif operation == EXECUTION_DISPATCH:
                    if self.execution_dispatch is None:
                        raise ApplicationError("DISPATCH_AUTHORITY_UNAVAILABLE")
                    result = await self.service.execute(operation, params["parameters"], context)
                    value = _owner_result(result, scope, context.request_id)
                elif operation == REVIEW_REQUEST_QUERY:
                    original = await self.service.query(operation, params['parameters'], context)
                    request, plan = original['request'], original['plan']
                    value={'contract_version':CONTRACT_VERSION,'query':operation,'scope':asdict(scope),
                        'record_type':'ReviewRequest','data':{'request':asdict(request),
                            'plan':dict(asdict(plan),check_keys=[asdict(k) for k in plan.check_keys])}}
                    if self.ports.review_presentation is not None:
                        value['data']['human_review'] = self.ports.review_presentation.project(context,plan,request)
                elif operation in (*DISPATCH_COMMANDS,*DISPATCH_QUERIES):
                    result = (await self.service.execute(operation, params['parameters'], context)
                        if operation in DISPATCH_COMMANDS else
                        await self.service.query(operation, params['parameters'], context))
                    if type(result) is CommandResult:
                        value = _command(result,scope,context.request_id)
                    else:
                        value = {'contract_version':CONTRACT_VERSION,'scope':asdict(scope),
                            'record_type':'implementation_dispatch','query':operation,'data':result}
                elif operation in SUPPORTED_COMMANDS:
                    result = await self.service.execute(operation, params["parameters"], context)
                    value = _command(result, scope, context.request_id)
                else:
                    result = await self.service.query(operation, params["parameters"], context)
                    if type(result) is CommandResult:
                        value = _command(result, scope, params["parameters"]["request_id"])
                    else:
                        kind, record = _record(result, operation)
                        value = {"contract_version": CONTRACT_VERSION, "query": operation,
                            "scope": asdict(scope), "record_type": kind, "data": record}
                        if operation == 'engineering.approvals.get_challenge':
                            project = getattr(self.ports.conversation_admission, 'project_confirmation', None)
                            if callable(project):
                                value['data'] = dict(record, conversation_confirmation=project(
                                    self.access, context, record))
                # Validate and detach before releasing the actual admission lease.
                return decode_json(canonical_bytes(value))
        except ApplicationError as error:
            raise _failure(error) from None
        except ReferenceError as error:
            raise _failure(ApplicationError(error.code)) from None

    async def execute_node(self, program, node_id, slots, *, caller, request_id):
        """Trusted composition supplies a real CompiledProgram, never client config."""
        parameters = self.bridge.operation_inputs(program, node_id, slots)
        node = next(node for node in program.workflow.steps if node.id == node_id)
        return await self.invoke(node.operation, {"scope": asdict(self.scope),
            "requestId": request_id, "parameters": parameters}, caller)

    def methods(self, *, owner="ordessa.engineering"):
        descriptors = []
        operations = tuple(self.capabilities()["supported_methods"])
        for operation in operations:
            async def handle(params, caller, operation=operation):
                return await self.invoke(operation, params, caller)
            required = {"scope", "requestId"}
            if operation != CAPABILITIES_METHOD:
                required.add("parameters")
            descriptors.append(ServerMethodDescriptor(method_id=operation,
                required_params=frozenset(required), optional_params=frozenset(),
                handler=handle, owner=owner, contextual=True))
        return tuple(descriptors)
