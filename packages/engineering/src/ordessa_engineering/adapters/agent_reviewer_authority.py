"""AgentReviewerAuthority backed by original Engineering and Agent records."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes

from ..application.contracts.commands import ReadSet, ReadVersion
from ..application.contracts.errors import ApplicationError
from ..domain.common.mechanisms.hashing import record_digest
from ..domain.common.models.identity import ActorRef
from ..domain.common.models.values import Digest
from ..domain.reviews.evidence import VerifiedReviewerEvidence
from ..application.contracts.agent_review import AgentReviewBinding
from ..domain.common.models.refs import BlobRef
from ..domain.changes.agent_execution_ref import AgentExecutionRecordRef
from ..domain.reviews.assignments import ReviewerAssignment
from ..domain.reviews.models import ReviewPlan, ReviewRequestState


_CAPABILITY = "engineering.reviews.assign_reviewer"
_IDENTITY_CONSTRAINT = "original_author_agent_identity_must_differ_from_original_reviewer_agent_identity"


class SQLiteAgentReviewerAuthority:
    """Authenticate assigned reviewer/author Agent refs and fence role through COMMIT.

    This verifies an original Agent read invocation and exact immutable method
    and request bindings. It does not invoke a model or make a review decision.
    """

    def __init__(self, factory, *, expected_access, expected_scope, assignments,
                 method_control, agent_records, agent_query_factory,
                 author_agent_resolver=None, authorship_source=None):
        same_assignment_owner = (
            getattr(assignments, "factory", None) is factory
            and getattr(assignments, "access", None) is expected_access
            and getattr(assignments, "methods", None) is method_control
            and getattr(assignments, "records", None) is agent_records
            and getattr(assignments, "agent_query_factory", None) is agent_query_factory
            and getattr(assignments, "author_agent_resolver", None) is author_agent_resolver
            and getattr(assignments, "authorship_source", None) is authorship_source
            and getattr(assignments, "expected_scope", None) is expected_scope)
        if (factory is None or getattr(method_control, "factory", None) is not factory
                or not same_assignment_owner
                or expected_access is None
                or not callable(getattr(expected_access, "guard_current_capability", None))
                or not callable(getattr(method_control, "guard_method", None))
                or not callable(getattr(agent_records, "read_agent_reference", None))
                or not callable(agent_query_factory)
                or (author_agent_resolver is not None and not callable(author_agent_resolver))
                or type(getattr(factory, "library", None)) is type(None)
                or getattr(factory.library, "schema_version", None) != 15
                or expected_scope is None
                or type(getattr(expected_scope, "realm_id", None)) is not str
                or not expected_scope.realm_id
                or type(getattr(expected_scope, "project_id", None)) is not str
                or not expected_scope.project_id):
            raise ApplicationError("UNIT_REVIEW_AUTHORITY_UNAVAILABLE")
        self.factory, self.access, self.expected_scope = factory, expected_access, expected_scope
        self.assignments, self.methods = assignments, method_control
        self.records, self.agent_query_factory = agent_records, agent_query_factory
        self.author_agent_resolver = author_agent_resolver
        if authorship_source is not None and (
                getattr(authorship_source,'factory',None) is not factory
                or getattr(authorship_source,'methods',None) is not method_control
                or not callable(getattr(authorship_source,'resolve_authorship',None))):
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_UNAVAILABLE')
        self.authorship_source=authorship_source

    @staticmethod
    def _declared_identity_constraint(plan, snapshot):
        from ..methods.definitions.models.compiled import thaw_value
        nodes = [node for node in snapshot.program.workflow.steps
                 if node.id == plan.requirement.phase_key
                 and getattr(node, "operation", None) == "engineering.reviews.request"]
        if len(nodes) != 1:
            raise ApplicationError("METHOD_PHASE_BINDING_MISMATCH")
        config = thaw_value(nodes[0].config)
        strategy = config.get("unit_submission_review_strategy", {})
        roles = strategy.get("roles", {}) if type(strategy) is dict else {}
        constraint = roles.get("identity_constraint") if type(roles) is dict else None
        from ..application.contracts.review_authorship import validate_authorship_policy
        return validate_authorship_policy(constraint)

    @staticmethod
    def _agent_bytes(ref):
        from ..domain.common.models.execution_refs import agent_instance_ref_bytes
        from ..domain.common.outcomes.diagnostics import ReferenceError
        try:return agent_instance_ref_bytes(ref)
        except ReferenceError as exc:raise ApplicationError('AGENT_REVIEW_SOURCE_UNAVAILABLE') from exc

    def _read_original_agent(self,context,ref,plan,request,purpose):
        raw=self._agent_bytes(ref)
        try:
            invocation=self.agent_query_factory(context,ref,plan,request,purpose=purpose)
            if invocation is None:raise ApplicationError('AGENT_REVIEW_AUTHORITY_UNAVAILABLE')
            actual=self.records.read_agent_reference(ref,read_invocation=invocation)
        except ApplicationError:raise
        except Exception as exc:raise ApplicationError('AGENT_REVIEW_AUTHORITY_UNAVAILABLE') from exc
        if actual!=raw:raise ApplicationError('UNTRUSTED_REVIEWER')
        return raw

    @contextmanager
    def guard_agent_reviewer(self, context, plan, request, binding, raw_response_ref,
                            observation_digest, *, expected=None):
        if (type(plan) is not ReviewPlan or type(request) is not ReviewRequestState
                or type(binding) is not AgentReviewBinding or type(raw_response_ref) is not BlobRef
                or request.state not in {"requested", "recorded"}
                or context.scope != plan.scope or request.scope != plan.scope
                or request.review_id != plan.review_id or binding.plan_digest != plan.plan_digest
                or binding.request_version != request.version or binding.request_fence != request.fence
                or type(binding.execution_ref) is not AgentExecutionRecordRef or type(raw_response_ref.digest) is not Digest
                or type(observation_digest) is not Digest):
            raise ApplicationError("REVIEW_REQUEST_CHANGED")
        constraints = binding.reviewer_identity_constraints
        from ..application.contracts.review_authorship import AGENT_SOURCE_BOUND_POLICY, validate_authorship_policy, resolve_plan_authorship, authorship_mode,authorship_projection
        source_bound = type(constraints) is dict and constraints.get('identity_constraint')==AGENT_SOURCE_BOUND_POLICY
        if (type(constraints) is not dict
                or set(constraints) != ({"identity_constraint", "authorAgentRef", "reviewerAgentRef", "authorship"} if source_bound
                    else {"identity_constraint", "authorAgentRef", "reviewerAgentRef"})
                or constraints["reviewerAgentRef"] != binding.execution_ref.agent_ref):
            raise ApplicationError("UNIT_REVIEW_IDENTITY_CONSTRAINT_UNAVAILABLE")
        validate_authorship_policy(constraints['identity_constraint'])
        if not source_bound and ((constraints['identity_constraint']==_IDENTITY_CONSTRAINT)
                != (constraints['authorAgentRef'] is not None)):
            raise ApplicationError('UNIT_REVIEW_IDENTITY_CONSTRAINT_UNAVAILABLE')
        reviewer_bytes = self._agent_bytes(binding.execution_ref.agent_ref)
        author_bytes = (None if constraints["authorAgentRef"] is None
                        else self._agent_bytes(constraints["authorAgentRef"]))
        if (author_bytes is not None and
                (binding.execution_ref.agent_ref["namespace"], binding.execution_ref.agent_ref["instanceId"]) == (
                    constraints["authorAgentRef"]["namespace"],
                    constraints["authorAgentRef"]["instanceId"])):
            raise ApplicationError("UNTRUSTED_REVIEWER")
        with ExitStack() as guards:
            caller = guards.enter_context(self.access.guard_current_capability(
                context, self.expected_scope, _CAPABILITY))
            principal_id = getattr(caller, "principal_id", None)
            credential_epoch = getattr(caller, "credential_epoch", None)
            if (type(principal_id) is not str or principal_id != context.principal_id
                    or type(credential_epoch) is not int or credential_epoch < 0):
                raise ApplicationError("UNIT_REVIEW_AUTHORITY_UNAVAILABLE")
            snapshot = guards.enter_context(self.methods.guard_method(context, plan.requirement.method_ref))
            declared_constraint = self._declared_identity_constraint(plan, snapshot)
            if declared_constraint != constraints["identity_constraint"]:
                raise ApplicationError("UNIT_REVIEW_IDENTITY_CONSTRAINT_UNAVAILABLE")
            origin = (resolve_plan_authorship(self.authorship_source,context,plan,binding.delivery_refs)
                      if source_bound else None)
            if origin is not None and (authorship_projection(origin)!=constraints['authorship']
                    or getattr(origin,'author_agent_ref',None)!=constraints['authorAgentRef']):
                raise ApplicationError('REVIEW_AUTHOR_SOURCE_INVALID')
            needs_native_author = declared_constraint is not None and (
                origin is None or authorship_mode(declared_constraint,origin)=='different_original_agent')
            if needs_native_author:
                if origin is None and self.author_agent_resolver is None:
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                selected_author = origin.author_agent_ref if origin is not None else self.author_agent_resolver(context, plan)
                if self._agent_bytes(selected_author) != canonical_bytes(constraints["authorAgentRef"]):
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            with self.factory.begin(context.scope, "read") as uow:
                assignment, control = uow.reviewer_assignments.active_for_review(plan.review_id)
            if (type(assignment) is not ReviewerAssignment or assignment.plan_digest != plan.plan_digest
                    or assignment.request_version != request.version
                    or assignment.fence != request.fence
                    or assignment.method_ref != plan.requirement.method_ref
                    or assignment.roles != tuple(sorted(plan.reviewer_requirements))
                    or assignment.reviewer_agent_ref_bytes != reviewer_bytes
                    or assignment.author_agent_ref_bytes != author_bytes
                    or control.state != "active"
                    or assignment.issuer_principal_id != principal_id
                    or assignment.issuer_credential_epoch != credential_epoch):
                raise ApplicationError("UNTRUSTED_REVIEWER")
            # Authenticated original Agent queries are required for both
            # sides; stored refs and caller-supplied identity fields are not proof.
            if (self._read_original_agent(context, binding.execution_ref.agent_ref, plan, request, "reviewer")
                    != assignment.reviewer_agent_ref_bytes
                    or ((None if author_bytes is None else self._read_original_agent(
                        context, constraints["authorAgentRef"], plan, request, "author"))
                        != assignment.author_agent_ref_bytes)):
                raise ApplicationError("UNTRUSTED_REVIEWER")
            guards.enter_context(self.factory.guard_read_set(ReadSet(context.scope, (
                ReadVersion("unit_reviewer_assignment", assignment.assignment_id, control.version),))))
            actor = ActorRef(record_digest("agent-reviewer-actor", {
                "agent_ref": assignment.reviewer_agent_ref,
                "assignment": asdict(assignment.ref)}).hex, "agent", "ordessa-agent-records")
            capability_inputs = {
                    "assignment_ref": asdict(assignment.ref), "control_version": control.version,
                    "issuer_principal_id": principal_id,
                    "issuer_credential_epoch": credential_epoch,
                    "method_ref": asdict(assignment.method_ref),
                    "reviewer_agent_ref": assignment.reviewer_agent_ref,
                    "author_agent_ref": assignment.author_agent_ref,
                }
            if origin is not None:
                capability_inputs['authorship']=authorship_projection(origin)
            evidence = VerifiedReviewerEvidence(
                context.scope, actor, assignment.roles,
                "ordessa.agent-reviewer-assignment", "2", control.version,
                plan.request_digest, raw_response_ref.digest, observation_digest,
                record_digest("agent-reviewer-capability", capability_inputs))
            if expected is not None and evidence != expected:
                raise ApplicationError("UNTRUSTED_REVIEWER")
            yield evidence


__all__ = ["SQLiteAgentReviewerAuthority"]
