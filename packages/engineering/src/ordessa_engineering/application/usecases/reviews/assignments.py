"""Original-library Agent reviewer assignment and revocation commands."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
import hashlib
from uuid import uuid4

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ...contracts.commands import (CommandContext, CommandResult,
    ReadSet, read_set_projection, request_digest)
from ...contracts.errors import ApplicationError
from ....domain.artifacts.method_binding import MethodRef
from ....domain.common.models.identity import Scope
from ....domain.common.models.values import Digest
from ....domain.reviews.assignments import ReviewerAssignment, ReviewerAssignmentRef
from ....domain.reviews.models import ReviewPlan


ASSIGN_REVIEWER = "engineering.reviews.assign_reviewer"
REVOKE_REVIEWER = "engineering.reviews.revoke_reviewer"
_DIGEST = {"type": "object", "required": ["algorithm", "hex"],
    "properties": {"algorithm": {"const": "sha256"},
                    "hex": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
    "additionalProperties": False}
_AGENT_REF = {"type":"object","required":["schemaVersion","namespace","instanceId","bindingDigest"],
    "properties":{"schemaVersion":{"const":"agent-instance/1"},"namespace":{"type":"string","minLength":1},
        "instanceId":{"type":"string","minLength":1},"bindingDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"}},
    "additionalProperties":False}


def command_input_schema(operation):
    if operation == ASSIGN_REVIEWER:
        required = ["review_id", "expected_plan_digest", "request_version", "fence", "reviewer_agent_ref"]
        properties = {"review_id": {"type": "string", "minLength": 1},
            "expected_plan_digest": _DIGEST,
            "request_version": {"type": "integer", "minimum": 0, "maximum": (1 << 53) - 1},
            "fence": {"type": "integer", "minimum": 1, "maximum": (1 << 53) - 1},
            "reviewer_agent_ref": _AGENT_REF, "author_agent_ref": _AGENT_REF}
    elif operation == REVOKE_REVIEWER:
        required = ["assignment_ref", "expected_control_version", "reason"]
        properties = {"assignment_ref": {"type": "object", "required": ["scope", "assignment_id", "digest"],
            "properties": {"scope": {"type": "object", "required": ["realm_id", "project_id"],
                "properties": {"realm_id": {"type": "string", "minLength": 1},
                               "project_id": {"type": "string", "minLength": 1}},
                "additionalProperties": False}, "assignment_id": {"type": "string", "minLength": 1},
                "digest": _DIGEST}, "additionalProperties": False},
            "expected_control_version": {"type": "integer", "minimum": 0, "maximum": (1 << 53) - 1},
            "reason": {"type": "string", "minLength": 1, "maxLength": 16384}}
    else:
        raise ApplicationError("OPERATION_UNAVAILABLE")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:ordessa:engineering:operations:{operation}:input:{2 if operation==ASSIGN_REVIEWER else 1}",
        "type": "object", "required": required, "properties": properties,
        "additionalProperties": False}


def decode_command_input(operation, value):
    """Decode the public wire form to the exact original domain values."""
    try:
        if type(value) is not dict:
            raise ValueError
        if operation == ASSIGN_REVIEWER:
            allowed = {"review_id", "expected_plan_digest", "request_version", "fence",
                       "reviewer_agent_ref", "author_agent_ref"}
            required = allowed - {"author_agent_ref"}
            if not required <= set(value) or set(value) - allowed:
                raise ValueError
            digest = value["expected_plan_digest"]
            if type(digest) is not dict or set(digest) != {"algorithm", "hex"}:
                raise ValueError
            return {**value, "expected_plan_digest": Digest(digest["algorithm"], digest["hex"])}
        if operation == REVOKE_REVIEWER:
            if set(value) != {"assignment_ref", "expected_control_version", "reason"}:
                raise ValueError
            data = value["assignment_ref"]
            if (type(data) is not dict or set(data) != {"scope", "assignment_id", "digest"}
                    or type(data["scope"]) is not dict
                    or set(data["scope"]) != {"realm_id", "project_id"}
                    or type(data["digest"]) is not dict
                    or set(data["digest"]) != {"algorithm", "hex"}):
                raise ValueError
            ref = ReviewerAssignmentRef(Scope(**data["scope"]), data["assignment_id"],
                Digest(data["digest"]["algorithm"], data["digest"]["hex"]))
            return {**value, "assignment_ref": ref}
    except (KeyError, TypeError, ValueError):
        raise ApplicationError("INVALID_INPUT") from None
    raise ApplicationError("OPERATION_UNAVAILABLE")


class ReviewerAssignmentUseCases:
    """Persist reviewed Agent roles in the selected original SQLite owner.

    `issuer_access` is the same EngineeringCommandAccess selected by the
    Application. Its current-capability guard supplies authenticated principal
    and credential epoch; CommandContext attribution is never used as proof.
    """

    def __init__(self, factory, method_control, records,
                 *, expected_access, expected_scope, agent_query_factory,
                 author_agent_resolver=None, author_identity_resolver=None,
                 authorship_source=None):
        if (expected_scope is None
                or type(getattr(expected_scope, "realm_id", None)) is not str
                or not expected_scope.realm_id
                or type(getattr(expected_scope, "project_id", None)) is not str
                or not expected_scope.project_id):
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        if (factory is None or getattr(method_control, "factory", None) is not factory
                or not callable(getattr(factory, "begin", None))
                or not callable(getattr(expected_access, "require", None))
                or not callable(getattr(expected_access, "guard_current_capability", None))
                or not callable(getattr(records, "read_agent_reference", None))
                or not callable(agent_query_factory)
                or (author_agent_resolver is not None and not callable(author_agent_resolver))
                or (author_identity_resolver is not None and (
                    not callable(author_identity_resolver)
                    or getattr(author_identity_resolver, "factory", None) is not factory
                    or getattr(author_identity_resolver, "access", None) is not expected_access
                    or getattr(author_identity_resolver, "records", None) is not records))):
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        library = getattr(factory, "library", None)
        schema_version = getattr(library, "schema_version", None)
        if schema_version not in (15, 17):
            raise ApplicationError("REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED")
        if author_identity_resolver is not None and schema_version != 17:
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        required_guard = "guard_method" if schema_version == 15 else "guard"
        if not callable(getattr(method_control, required_guard, None)):
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        self.factory, self.access, self.methods = factory, expected_access, method_control
        self.schema_version = schema_version
        self.records, self.agent_query_factory = records, agent_query_factory
        self.author_agent_resolver = author_agent_resolver
        self.author_identity_resolver = author_identity_resolver
        if authorship_source is not None and (
                getattr(authorship_source,'factory',None) is not factory
                or getattr(authorship_source,'methods',None) is not method_control
                or not callable(getattr(authorship_source,'resolve_authorship',None))):
            raise ApplicationError('REVIEW_AUTHOR_SOURCE_UNAVAILABLE')
        self.authorship_source=authorship_source
        self.expected_scope = expected_scope

    def _authorize(self, context, capability):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if (context.scope.realm_id, context.scope.project_id) != (
                self.expected_scope.realm_id, self.expected_scope.project_id):
            raise ApplicationError("SCOPE_MISMATCH")
        self.access.require(context, capability)
        return self.access.guard_current_capability(context, self.expected_scope, capability)

    @staticmethod
    def _agent_ref(value):
        from ....domain.common.models.execution_refs import agent_instance_ref_bytes
        from ....domain.common.outcomes.diagnostics import ReferenceError
        try:
            return agent_instance_ref_bytes(value)
        except ReferenceError as exc:
            raise ApplicationError("INVALID_INPUT") from exc

    def _resolve_agent(self, context, ref, plan, request, purpose):
        raw = self._agent_ref(ref)
        if purpose == "author" and self.author_identity_resolver is not None:
            try:
                resolved = self.author_identity_resolver(context, ref, plan, request)
                if self._agent_ref(resolved) != raw:
                    raise ApplicationError("AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            except ApplicationError:
                raise
            except Exception as exc:
                raise ApplicationError("AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE") from exc
        try:
            invocation = self.agent_query_factory(context, ref, plan, request, purpose=purpose)
            if invocation is None:
                raise ApplicationError("AGENT_REVIEW_AUTHORITY_UNAVAILABLE")
            actual = self.records.read_agent_reference(ref, read_invocation=invocation)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("AGENT_REVIEW_AUTHORITY_UNAVAILABLE") from exc
        if type(actual) is not bytes or actual != raw:
            raise ApplicationError("UNTRUSTED_REVIEWER")
        return raw

    def _request(self, context, review_id, plan_digest, request_version, fence):
        if (type(review_id) is not str or not review_id or type(plan_digest) is not Digest
                or type(request_version) is not int or request_version < 0
                or type(fence) is not int or fence < 1):
            raise ApplicationError("INVALID_INPUT")
        with self.factory.begin(context.scope, "read") as uow:
            plan = uow.reviews.get_plan(review_id)
            request = uow.reviews.get_request(review_id)
        if (plan.scope != context.scope or plan.plan_digest != plan_digest
                or request.state != "requested" or request.version != request_version
                or request.fence != fence):
            raise ApplicationError("REVIEW_REQUEST_CHANGED")
        return plan, request

    @staticmethod
    def _identity_constraint(plan, snapshot):
        from ....methods.definitions.models.compiled import thaw_value
        nodes = [node for node in snapshot.program.workflow.steps
                 if node.id == plan.requirement.phase_key
                 and getattr(node, "operation", None) == "engineering.reviews.request"]
        if len(nodes) != 1:
            raise ApplicationError("METHOD_PHASE_BINDING_MISMATCH")
        config = thaw_value(nodes[0].config)
        strategy = config.get("unit_submission_review_strategy", {})
        roles = strategy.get("roles", {}) if type(strategy) is dict else {}
        constraint = roles.get("identity_constraint") if type(roles) is dict else None
        from ...contracts.review_authorship import validate_authorship_policy
        return validate_authorship_policy(constraint)

    @staticmethod
    def _declared_report_facts(uow, context, plan, declaration):
        """Resolve a schema-17 review's sole declared report from original owners.

        This path deliberately consumes the published declaration and the
        immutable Work dispatch relation. It does not compile a method or fall
        back to a MethodRun/legacy submission reader.
        """
        from ....domain.reviews.refs import SubmissionRef
        from ....domain.packages.models import PreparedPackagePayload
        from ordessa_engineering.application.usecases.changes.declared_report import (
            resolve_declared_report_binding,
        )
        from ordessa_infrastructure.encoding import decode_json
        from ..material_closure import _method_ref_matches

        requirement = plan.requirement
        targets = requirement.expected_targets.targets
        primary = tuple(target for target in targets if target.role == "primary")
        if (requirement.purpose != "acceptance" or requirement.schema_version != 2
                or requirement.scope != context.scope
                or not _method_ref_matches(declaration, requirement.method_ref)
                or len(targets) != 1 or len(primary) != 1
                or type(primary[0].ref) is not SubmissionRef):
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
        submission_ref = primary[0].ref
        try:
            submission = uow.submissions.resolve(submission_ref)
            from ....domain.changes.agent_submission_report import AgentSubmissionReport
            if type(submission) is AgentSubmissionReport:
                if submission.ref != submission_ref or submission.scope != context.scope:
                    raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
                from ..changes.agent_declared_report import resolve_agent_declared_report_binding
                binding = resolve_agent_declared_report_binding(uow, submission)
            else:
                if (submission.ref != submission_ref or submission.schema_version != 2
                        or submission.scope != context.scope):
                    raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
                binding = resolve_declared_report_binding(uow, submission)
            package = uow.implementation.resolve_package(binding.package_ref)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH") from exc
        if (type(package.payload) is not PreparedPackagePayload
                or package.payload.method_ref != requirement.method_ref
                or binding.scope != context.scope
                or binding.work.get("action_id") is None):
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")

        actions = tuple(action for action in declaration.actions
                        if action.action_id == binding.work["action_id"])
        if len(actions) != 1:
            raise ApplicationError("METHOD_PHASE_BINDING_MISMATCH")
        steps = tuple(step for step in actions[0].steps
                      if step.step_id == requirement.phase_key)
        if (len(steps) != 1 or steps[0].kind != 'invoke'
                or steps[0].name != "independently-review-report"):
            raise ApplicationError("METHOD_PHASE_BINDING_MISMATCH")
        # The released method places independence on the disposition consuming
        # this review, rather than on the review invocation itself.
        review_step = steps[0]
        def independent_disposition(step, gate):
            inputs = {item.name: item for item in step.inputs}
            required = {'report', 'review', 'package', 'reviewer_profile', 'method'}
            if (step.kind != 'invoke' or step.name != 'resolve-one-operation-disposition'
                    or gate.kind != 'reviewer_independent'
                    or not required <= set(gate.inputs) or not required <= set(inputs)):
                return False
            review_input, report_input = inputs['review'], inputs['report']
            return (review_input.source_kind == 'step_output'
                and review_input.step_id == review_step.step_id
                and review_input.source_name in review_step.outputs
                and report_input.source_kind == 'step_output'
                and report_input.step_id == binding.step_id
                and report_input.source_name == 'implementation_report'
                and all(inputs[name].source_kind == 'action_input'
                        and inputs[name].source_name == name
                        for name in ('package', 'reviewer_profile', 'method')))

        independence = any(independent_disposition(step, gate)
            for step in actions[0].steps for gate in step.admission)
        if not independence:
            raise ApplicationError("METHOD_PHASE_BINDING_MISMATCH")
        from ....domain.changes.agent_dispatch import AgentWorkDispatchBinding
        if type(binding) is AgentWorkDispatchBinding:
            from ....domain.common.models.execution_refs import read_agent_instance_ref
            read_agent_instance_ref(binding.agent_ref_bytes)
            return submission, binding, decode_json(binding.agent_ref_bytes)
        unit_ref = decode_json(binding.unit_ref_bytes)
        if (type(unit_ref) is not dict or set(unit_ref) != {
                "environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}):
            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
        return submission, binding, unit_ref

    @staticmethod
    def _same_unit(left, right):
        """Compare original Unit identity; sourceRevision is not identity."""
        return (left["environmentNamespace"], left["unitId"]) == (
            right["environmentNamespace"], right["unitId"])

    @staticmethod
    def _same_agent(left, right):
        return (left["namespace"], left["instanceId"]) == (right["namespace"], right["instanceId"])

    def _run(self, context, operation, parameters, mutate):
        request_hash = self._request_hash(operation, context, parameters)
        with self.factory.begin(context.scope, "write") as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=operation, operation_id=str(uuid4()), request_digest=request_hash)
            entry = reservation.entry
            if not reservation.created:
                if entry.operation != operation or entry.request_digest != request_hash:
                    raise ApplicationError("REQUEST_IDENTITY_CONFLICT")
                return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)
            with uow.isolate():
                result = mutate(uow)
            completed = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result))
            answer = CommandResult(uow.authority_id, completed.operation_id,
                                  completed.state, completed.result_bytes)
            uow.commit()
            return answer

    @staticmethod
    def _request_hash(operation, context, parameters):
        schema = command_input_schema(operation)
        # Match EngineeringService.command_request_digest exactly. These
        # commands currently accept only the canonical empty read set.
        reads = ReadSet(context.scope, ())
        return request_digest(operation, context, parameters, read_set_projection(reads),
            input_schema_id=schema["$id"],
            input_schema_digest=Digest("sha256", hashlib.sha256(canonical_bytes(schema)).hexdigest()),
            interface_version="2" if operation == ASSIGN_REVIEWER else "1")

    def _replay(self, context, operation, parameters):
        request_hash = self._request_hash(operation, context, parameters)
        with self.factory.begin(context.scope, "read") as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                return None
            if (entry.project_id != context.scope.project_id or entry.operation != operation
                    or entry.request_digest != request_hash):
                raise ApplicationError("REQUEST_IDENTITY_CONFLICT")
            return CommandResult(uow.authority_id, entry.operation_id, entry.state, entry.result_bytes)

    def assign_reviewer(self, context, *, review_id, expected_plan_digest,
                        request_version, fence, reviewer_agent_ref, author_agent_ref=None):
        issuer_guard = self._authorize(context, ASSIGN_REVIEWER)
        parameters = {"review_id": review_id, "expected_plan_digest": asdict(expected_plan_digest)
            if type(expected_plan_digest) is Digest else expected_plan_digest,
            "request_version": request_version, "fence": fence,
            "reviewer_agent_ref": reviewer_agent_ref}
        if author_agent_ref is not None:
            parameters["author_agent_ref"] = author_agent_ref
        with ExitStack() as guards:
            caller = guards.enter_context(issuer_guard)
            principal_id = getattr(caller, "principal_id", None)
            epoch = getattr(caller, "credential_epoch", None)
            if (type(principal_id) is not str or principal_id != context.principal_id
                    or type(epoch) is not int or epoch < 0):
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
            replay = self._replay(context, ASSIGN_REVIEWER, parameters)
            if replay is not None:
                return replay
            plan, request = self._request(context, review_id, expected_plan_digest, request_version, fence)
            reviewer_bytes = self._resolve_agent(context, reviewer_agent_ref, plan, request, "reviewer")
            if self.schema_version == 17:
                with self.methods.guard(context, plan.requirement.method_ref) as declaration:
                    with self.factory.begin(context.scope, "read") as uow:
                        submission, binding, author_ref = self._declared_report_facts(
                            uow, context, plan, declaration)
                    if (author_agent_ref is not None
                            and canonical_bytes(author_agent_ref) != canonical_bytes(author_ref)):
                        raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                    # The current Work declaration still returns a historical Unit
                    # author. Never relabel that identity as an Agent assignment.
                    if author_ref.get("schemaVersion") != "agent-instance/1":
                        raise ApplicationError("AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                    author_bytes = self._resolve_agent(context, author_ref, plan, request, "author")
                    if self._same_agent(reviewer_agent_ref, author_ref):
                        raise ApplicationError("UNTRUSTED_REVIEWER")
                    roles = tuple(sorted(plan.reviewer_requirements))
                    assignment = ReviewerAssignment(context.scope, str(uuid4()), review_id,
                        plan.plan_digest, request.version, request.fence,
                        plan.requirement.method_ref, reviewer_bytes, author_bytes,
                        roles, principal_id, epoch, context.received_at)

                    def insert_bound(uow):
                        current_plan = uow.reviews.get_plan(review_id)
                        current_request = uow.reviews.get_request(review_id)
                        current = self._declared_report_facts(uow, context, plan, declaration)
                        if (current_plan.plan_digest != plan.plan_digest
                                or current_plan.requirement.digest != plan.requirement.digest
                                or current_request.state != "requested"
                                or current_request.version != request.version
                                or current_request.fence != request.fence
                                or current[0].ref != submission.ref or current[1] != binding
                                or canonical_bytes(current[2]) != canonical_bytes(author_ref)):
                            raise ApplicationError("METHOD_SUBJECT_BINDING_MISMATCH")
                        return {"assignment_ref": asdict(
                            uow.reviewer_assignments.insert(assignment))}

                    return self._run(context, ASSIGN_REVIEWER, parameters, insert_bound)
            snapshot = guards.enter_context(self.methods.guard_method(context, plan.requirement.method_ref))
            constraint = self._identity_constraint(plan, snapshot)
            resolved_author = None
            from ...contracts.review_authorship import (AGENT_SOURCE_BOUND_POLICY, NATIVE_DIFFERENT_AGENT,
                resolve_plan_authorship, authorship_mode, AgentReviewAuthorship)
            origin = (resolve_plan_authorship(self.authorship_source,context,plan)
                      if constraint==AGENT_SOURCE_BOUND_POLICY else None)
            if constraint is not None and constraint not in (NATIVE_DIFFERENT_AGENT, AGENT_SOURCE_BOUND_POLICY):
                raise ApplicationError("AGENT_REVIEW_IDENTITY_CONSTRAINT_REQUIRED")
            needs_native_author = constraint is not None and (
                origin is None or authorship_mode(constraint,origin)=='different_original_agent')
            if needs_native_author:
                if origin is None and self.author_agent_resolver is None:
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                if origin is not None and type(origin) is not AgentReviewAuthorship:
                    raise ApplicationError("AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                selected_author = origin.author_agent_ref if origin is not None else self.author_agent_resolver(context, plan)
                if author_agent_ref is not None and canonical_bytes(author_agent_ref) != canonical_bytes(selected_author):
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                resolved_author = self._resolve_agent(context, selected_author, plan, request, "author")
                reviewer = reviewer_agent_ref
                if self._same_agent(reviewer, selected_author):
                    raise ApplicationError("UNTRUSTED_REVIEWER")
            elif author_agent_ref is not None:
                raise ApplicationError("INVALID_INPUT")
            roles = tuple(sorted(plan.reviewer_requirements))
            assignment = ReviewerAssignment(context.scope, str(uuid4()), review_id,
                plan.plan_digest, request.version, request.fence, plan.requirement.method_ref,
                reviewer_bytes, resolved_author, roles, principal_id, epoch, context.received_at)
            return self._run(context, ASSIGN_REVIEWER, parameters, lambda uow: {
                "assignment_ref": asdict(uow.reviewer_assignments.insert(assignment))})

    def revoke_reviewer(self, context, *, assignment_ref, expected_control_version, reason):
        issuer_guard = self._authorize(context, REVOKE_REVIEWER)
        if (type(assignment_ref) is not ReviewerAssignmentRef
                or assignment_ref.scope != context.scope or type(expected_control_version) is not int
                or expected_control_version < 0 or type(reason) is not str or not reason):
            raise ApplicationError("INVALID_INPUT")
        parameters = {"assignment_ref": asdict(assignment_ref),
            "expected_control_version": expected_control_version, "reason": reason}
        with ExitStack() as guards:
            caller = guards.enter_context(issuer_guard)
            if (getattr(caller, "principal_id", None) != context.principal_id
                    or type(getattr(caller, "credential_epoch", None)) is not int):
                raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
            replay = self._replay(context, REVOKE_REVIEWER, parameters)
            if replay is not None:
                return replay
            with self.factory.begin(context.scope, "read") as uow:
                assignment = uow.reviewer_assignments.get(assignment_ref)
                _, current = uow.reviewer_assignments.active_for_review(assignment.review_id)
            if current.ref != assignment_ref:
                raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")
            if self.schema_version == 17:
                with self.methods.guard(context, assignment.method_ref) as declaration:
                    with self.factory.begin(context.scope, "read") as uow:
                        plan = uow.reviews.get_plan(assignment.review_id)
                        self._declared_report_facts(uow, context, plan, declaration)

                    def revoke_bound(uow):
                        current_assignment = uow.reviewer_assignments.get(assignment_ref)
                        _, current_control = uow.reviewer_assignments.active_for_review(
                            current_assignment.review_id)
                        current_plan = uow.reviews.get_plan(current_assignment.review_id)
                        self._declared_report_facts(uow, context, current_plan, declaration)
                        if (current_assignment != assignment or current_control.ref != assignment_ref
                                or current_plan.plan_digest != assignment.plan_digest):
                            raise ApplicationError("REVIEWER_ASSIGNMENT_CHANGED")
                        return {"control": asdict(uow.reviewer_assignments.revoke(
                            assignment_ref, expected_version=expected_control_version,
                            revoked_at=context.received_at, reason=reason, event_id=str(uuid4())))}

                    return self._run(context, REVOKE_REVIEWER, parameters, revoke_bound)
            guards.enter_context(self.methods.guard_method(context, assignment.method_ref))
            return self._run(context, REVOKE_REVIEWER, parameters, lambda uow: {
                "control": asdict(uow.reviewer_assignments.revoke(assignment_ref,
                    expected_version=expected_control_version, revoked_at=context.received_at,
                    reason=reason, event_id=str(uuid4())))})


__all__ = ["ReviewerAssignmentUseCases", "ASSIGN_REVIEWER", "REVOKE_REVIEWER",
           "command_input_schema", "decode_command_input"]
