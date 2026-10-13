"""Original-library Unit reviewer assignment and revocation commands."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
import hashlib
from uuid import uuid4

from ordessa_infrastructure.encoding import canonical_bytes

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
_UNIT_REF = {"type": "object", "required": ["environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"],
    "properties": {"environmentNamespace": {"type": "string", "minLength": 1},
        "unitId": {"type": "string", "minLength": 1},
        "ownerProviderRef": {"type": "object"}, "sourceRevision": {"type": "string", "minLength": 1}},
    "additionalProperties": False}


def command_input_schema(operation):
    if operation == ASSIGN_REVIEWER:
        required = ["review_id", "expected_plan_digest", "request_version", "fence", "reviewer_unit_ref"]
        properties = {"review_id": {"type": "string", "minLength": 1},
            "expected_plan_digest": _DIGEST,
            "request_version": {"type": "integer", "minimum": 0, "maximum": (1 << 53) - 1},
            "fence": {"type": "integer", "minimum": 1, "maximum": (1 << 53) - 1},
            "reviewer_unit_ref": _UNIT_REF, "author_unit_ref": _UNIT_REF}
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
        "$id": f"urn:ordessa:engineering:operations:{operation}:input:1",
        "type": "object", "required": required, "properties": properties,
        "additionalProperties": False}


def decode_command_input(operation, value):
    """Decode the public wire form to the exact original domain values."""
    try:
        if type(value) is not dict:
            raise ValueError
        if operation == ASSIGN_REVIEWER:
            allowed = {"review_id", "expected_plan_digest", "request_version", "fence",
                       "reviewer_unit_ref", "author_unit_ref"}
            required = allowed - {"author_unit_ref"}
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
    """Persist reviewed Unit roles in the selected original SQLite owner.

    `issuer_access` is the same EngineeringCommandAccess selected by the
    Application. Its current-capability guard supplies authenticated principal
    and credential epoch; CommandContext attribution is never used as proof.
    """

    def __init__(self, factory, method_control, records,
                 *, expected_access, expected_scope, unit_query_factory,
                 author_unit_resolver=None):
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
                or not callable(getattr(method_control, "guard_method", None))
                or not callable(getattr(records, "resolve_unit_reference", None))
                or not callable(unit_query_factory)
                or (author_unit_resolver is not None and not callable(author_unit_resolver))):
            raise ApplicationError("REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE")
        library = getattr(factory, "library", None)
        if getattr(library, "schema_version", None) != 15:
            raise ApplicationError("REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED")
        self.factory, self.access, self.methods = factory, expected_access, method_control
        self.records, self.unit_query_factory = records, unit_query_factory
        self.author_unit_resolver = author_unit_resolver
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
    def _unit_ref(value):
        if (type(value) is not dict or set(value) != {
                "environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
                or any(type(value.get(k)) is not str or not value[k]
                       for k in ("environmentNamespace", "unitId", "sourceRevision"))
                or type(value.get("ownerProviderRef")) is not dict):
            raise ApplicationError("INVALID_INPUT")
        raw = canonical_bytes(value)
        if len(raw) > 8192:
            raise ApplicationError("INVALID_INPUT")
        return raw

    def _resolve_unit(self, context, ref, plan, request, purpose):
        raw = self._unit_ref(ref)
        try:
            invocation, input_digest = self.unit_query_factory(
                context, ref, plan, request, purpose=purpose)
            if type(input_digest) is not str or not input_digest:
                raise ApplicationError("UNIT_REVIEW_AUTHORITY_UNAVAILABLE")
            unit = self.records.resolve_unit_reference(ref, invocation, input_digest=input_digest)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("UNIT_REVIEW_AUTHORITY_UNAVAILABLE") from exc
        if canonical_bytes(unit.public_ref) != raw:
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
        if constraint is not None and constraint != "original_author_unit_identity_must_differ_from_original_reviewer_unit_identity":
            raise ApplicationError("UNIT_REVIEW_IDENTITY_CONSTRAINT_UNSUPPORTED")
        return constraint

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
            interface_version="1")

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
                        request_version, fence, reviewer_unit_ref, author_unit_ref=None):
        issuer_guard = self._authorize(context, ASSIGN_REVIEWER)
        parameters = {"review_id": review_id, "expected_plan_digest": asdict(expected_plan_digest)
            if type(expected_plan_digest) is Digest else expected_plan_digest,
            "request_version": request_version, "fence": fence,
            "reviewer_unit_ref": reviewer_unit_ref}
        if author_unit_ref is not None:
            parameters["author_unit_ref"] = author_unit_ref
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
            reviewer_bytes = self._resolve_unit(context, reviewer_unit_ref, plan, request, "reviewer")
            snapshot = guards.enter_context(self.methods.guard_method(context, plan.requirement.method_ref))
            constraint = self._identity_constraint(plan, snapshot)
            resolved_author = None
            if constraint is not None:
                if self.author_unit_resolver is None:
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                selected_author = self.author_unit_resolver(context, plan)
                if author_unit_ref is not None and canonical_bytes(author_unit_ref) != canonical_bytes(selected_author):
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                resolved_author = self._resolve_unit(context, selected_author, plan, request, "author")
                reviewer = reviewer_unit_ref
                if (reviewer["environmentNamespace"], reviewer["unitId"]) == (
                        selected_author["environmentNamespace"], selected_author["unitId"]):
                    raise ApplicationError("UNTRUSTED_REVIEWER")
            elif author_unit_ref is not None:
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
            guards.enter_context(self.methods.guard_method(context, assignment.method_ref))
            return self._run(context, REVOKE_REVIEWER, parameters, lambda uow: {
                "control": asdict(uow.reviewer_assignments.revoke(assignment_ref,
                    expected_version=expected_control_version, revoked_at=context.received_at,
                    reason=reason, event_id=str(uuid4())))})


__all__ = ["ReviewerAssignmentUseCases", "ASSIGN_REVIEWER", "REVOKE_REVIEWER",
           "command_input_schema", "decode_command_input"]
