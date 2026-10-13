"""UnitReviewerAuthority backed by original Engineering and Unit records."""
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
from ..application.contracts.unit_review import UnitReviewBinding
from ..domain.common.models.refs import BlobRef
from ..domain.reviews.models import ReviewPlan, ReviewRequestState


_CAPABILITY = "engineering.reviews.assign_reviewer"
_IDENTITY_CONSTRAINT = "original_author_unit_identity_must_differ_from_original_reviewer_unit_identity"


class SQLiteUnitReviewerAuthority:
    """Authenticate assigned reviewer/author Unit refs and fence role through COMMIT.

    This verifies an original UnitRecords invocation and exact immutable method
    and request bindings. It does not invoke a model or make a review decision.
    """

    def __init__(self, factory, *, expected_access, expected_scope, assignments,
                 method_control, unit_records, unit_query_factory,
                 author_unit_resolver=None):
        same_assignment_owner = (
            getattr(assignments, "factory", None) is factory
            and getattr(assignments, "access", None) is expected_access
            and getattr(assignments, "methods", None) is method_control
            and getattr(assignments, "records", None) is unit_records
            and getattr(assignments, "unit_query_factory", None) is unit_query_factory
            and getattr(assignments, "author_unit_resolver", None) is author_unit_resolver
            and getattr(assignments, "expected_scope", None) is expected_scope)
        if (factory is None or getattr(method_control, "factory", None) is not factory
                or not same_assignment_owner
                or expected_access is None
                or not callable(getattr(expected_access, "guard_current_capability", None))
                or not callable(getattr(method_control, "guard_method", None))
                or not callable(getattr(unit_records, "resolve_unit_reference", None))
                or not callable(unit_query_factory)
                or (author_unit_resolver is not None and not callable(author_unit_resolver))
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
        self.records, self.unit_query_factory = unit_records, unit_query_factory
        self.author_unit_resolver = author_unit_resolver

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
        if constraint not in (None, _IDENTITY_CONSTRAINT):
            raise ApplicationError("UNIT_REVIEW_IDENTITY_CONSTRAINT_UNSUPPORTED")
        return constraint

    @staticmethod
    def _unit_bytes(ref):
        if (type(ref) is not dict or set(ref) != {
                "environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
                or type(ref.get("ownerProviderRef")) is not dict
                or any(type(ref.get(key)) is not str or not ref[key]
                       for key in ("environmentNamespace", "unitId", "sourceRevision"))):
            raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")
        return canonical_bytes(ref)

    def _read_original_unit(self, context, ref, plan, request, purpose):
        raw = self._unit_bytes(ref)
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

    @contextmanager
    def guard_unit_reviewer(self, context, plan, request, binding, raw_response_ref,
                            observation_digest, *, expected=None):
        if (type(plan) is not ReviewPlan or type(request) is not ReviewRequestState
                or type(binding) is not UnitReviewBinding or type(raw_response_ref) is not BlobRef
                or request.state not in {"requested", "recorded"}
                or context.scope != plan.scope or request.scope != plan.scope
                or request.review_id != plan.review_id or binding.plan_digest != plan.plan_digest
                or binding.request_version != request.version or binding.request_fence != request.fence
                or binding.unit_ref is None or type(raw_response_ref.digest) is not Digest
                or type(observation_digest) is not Digest):
            raise ApplicationError("REVIEW_REQUEST_CHANGED")
        constraints = binding.reviewer_identity_constraints
        if (type(constraints) is not dict
                or set(constraints) != {"identity_constraint", "authorUnitRef", "reviewerUnitRef"}
                or constraints["reviewerUnitRef"] != binding.unit_ref
                or constraints["identity_constraint"] not in (None, _IDENTITY_CONSTRAINT)
            or ((constraints["identity_constraint"] == _IDENTITY_CONSTRAINT)
                    != (constraints["authorUnitRef"] is not None))):
            raise ApplicationError("UNIT_REVIEW_IDENTITY_CONSTRAINT_UNAVAILABLE")
        reviewer_bytes = self._unit_bytes(binding.unit_ref)
        author_bytes = (None if constraints["authorUnitRef"] is None
                        else self._unit_bytes(constraints["authorUnitRef"]))
        if (author_bytes is not None and
                (binding.unit_ref["environmentNamespace"], binding.unit_ref["unitId"]) == (
                    constraints["authorUnitRef"]["environmentNamespace"],
                    constraints["authorUnitRef"]["unitId"])):
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
            if declared_constraint is not None:
                if self.author_unit_resolver is None:
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
                selected_author = self.author_unit_resolver(context, plan)
                if self._unit_bytes(selected_author) != canonical_bytes(constraints["authorUnitRef"]):
                    raise ApplicationError("UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE")
            with self.factory.begin(context.scope, "read") as uow:
                assignment, control = uow.reviewer_assignments.active_for_review(plan.review_id)
            if (assignment.plan_digest != plan.plan_digest
                    or assignment.request_version != request.version
                    or assignment.fence != request.fence
                    or assignment.method_ref != plan.requirement.method_ref
                    or assignment.roles != tuple(sorted(plan.reviewer_requirements))
                    or assignment.reviewer_unit_ref_bytes != reviewer_bytes
                    or assignment.author_unit_ref_bytes != author_bytes
                    or control.state != "active"
                    or assignment.issuer_principal_id != principal_id
                    or assignment.issuer_credential_epoch != credential_epoch):
                raise ApplicationError("UNTRUSTED_REVIEWER")
            # Authenticated original UnitRecords queries are required for both
            # sides; stored refs and caller-supplied identity fields are not proof.
            if (self._read_original_unit(context, binding.unit_ref, plan, request, "reviewer")
                    != assignment.reviewer_unit_ref_bytes
                    or ((None if author_bytes is None else self._read_original_unit(
                        context, constraints["authorUnitRef"], plan, request, "author"))
                        != assignment.author_unit_ref_bytes)):
                raise ApplicationError("UNTRUSTED_REVIEWER")
            guards.enter_context(self.factory.guard_read_set(ReadSet(context.scope, (
                ReadVersion("unit_reviewer_assignment", assignment.assignment_id, control.version),))))
            actor = ActorRef(record_digest("unit-reviewer-actor", {
                "unit_ref": assignment.reviewer_unit_ref,
                "assignment": asdict(assignment.ref)}).hex, "agent", "ordessa-unit-records")
            evidence = VerifiedReviewerEvidence(
                context.scope, actor, assignment.roles,
                "ordessa.unit-reviewer-assignment", "1", control.version,
                plan.request_digest, raw_response_ref.digest, observation_digest,
                record_digest("unit-reviewer-capability", {
                    "assignment_ref": asdict(assignment.ref), "control_version": control.version,
                    "issuer_principal_id": principal_id,
                    "issuer_credential_epoch": credential_epoch,
                    "method_ref": asdict(assignment.method_ref),
                    "reviewer_unit_ref": assignment.reviewer_unit_ref,
                    "author_unit_ref": assignment.author_unit_ref,
                }))
            if expected is not None and evidence != expected:
                raise ApplicationError("UNTRUSTED_REVIEWER")
            yield evidence


__all__ = ["SQLiteUnitReviewerAuthority"]
