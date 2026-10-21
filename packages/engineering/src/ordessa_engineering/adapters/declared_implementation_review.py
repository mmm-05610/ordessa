"""Bind schema-17 implementation reviews to the original Work and method.

This adapter produces one human judgment over the complete frozen method
criterion. It does not parse that text into policy, authenticate a reviewer,
or grant permission to implement or accept a package.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
from collections.abc import Mapping

from ordessa_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_infrastructure.encoding import canonical_bytes

from ..application.contracts.errors import ApplicationError
from ..application.contracts.reviewer_admission import SourceReviewBinding
from ..application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, WorkBinding, decode_work_binding,
)
from ..application.usecases.changes.declared_report import resolve_declared_report_binding
from ..domain.approvals.implementation import WorkPackageAuthorizationIntent
from ..domain.artifacts.method_binding import ExactMethodResourceRef
from ..domain.changes.submission import Submission
from ..domain.packages.models import ImplementationPackage, PreparedPackagePayload
from ..domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan,
    ReviewRequirement, Target, TargetSet,
)
from ..domain.reviews.refs import SubmissionRef
from ..methods.definitions.models import (
    CheckDefinition, CriterionDefinition, DispositionSpec, ResourceRef,
    ReductionSpec, StandardDefinition, freeze_value,
)


_CRITERIA_ID = "implementation-review-criteria"
_CRITERION_ID = "implementation-review"
_CHECK_CAPABILITY = "engineering.reviewer.unit"
_CHECK_VERSION = "1"


def _definition_matches_method(definition, method_ref):
    """Compare the declaration owner's wire identity with the domain pin."""
    declared = getattr(definition, "method_ref", None)
    digest = getattr(declared, "snapshot_digest", None)
    digest = digest.hex if hasattr(digest, "hex") else digest
    return (getattr(declared, "method_id", None) == method_ref.method_id
            and getattr(declared, "release_version", None) == method_ref.release_version
            and getattr(declared, "schema_version", None) == method_ref.schema_version
            and digest == method_ref.snapshot_digest.hex)


class DeclaredImplementationReviewBindings:
    """Original-library plan producer and declared-submission binding port.

    ``expected_reviewer_profile_ref`` must be the immutable revision selected
    by the product's original Unit owner. The adapter always rereads it through
    the original ProfileService; no caller plan or current profile head selects
    a revision.
    """

    def __init__(self, factory, method_guard, profiles, expected_reviewer_profile_ref):
        if (factory is None or getattr(method_guard, "factory", None) is not factory
                or not callable(getattr(method_guard, "guard", None))
                or not callable(getattr(method_guard, "resource_ref", None))
                or not callable(getattr(method_guard, "read_resource", None))
                or not callable(getattr(profiles, "get_revision", None))
                or type(expected_reviewer_profile_ref) is not ProfileRevisionRef):
            raise ApplicationError("IMPLEMENTATION_REVIEW_AUTHORITY_UNAVAILABLE")
        self.factory = factory
        self.methods = method_guard
        self.profiles = profiles
        self.expected_profile_ref = expected_reviewer_profile_ref

    @staticmethod
    def requirement_id(work, submission_ref, reviewer_profile):
        digest = hashlib.sha256(canonical_bytes({
            "work_id": work.work_id,
            "revision": work.revision,
            "method_ref": asdict(work.method_ref),
            "submission_ref": asdict(submission_ref),
            "reviewer_profile": reviewer_profile,
        })).hexdigest()
        return "implementation-review-" + digest[:40]

    def _reviewer_profile(self, supplied):
        expected = encode_revision_ref(self.expected_profile_ref)
        if type(supplied) is not dict or supplied != expected:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        revision = self.profiles.get_revision(self.expected_profile_ref)
        if getattr(revision, "ref", None) != self.expected_profile_ref:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        return expected

    def _persisted_binding(self, context, work, submission, package):
        if (type(work) is not WorkBinding or type(submission) is not Submission
                or type(submission.ref) is not SubmissionRef
                or type(package) is not ImplementationPackage
                or type(package.payload) is not PreparedPackagePayload
                or context.scope != work.scope or submission.scope != work.scope
                or package.scope != work.scope):
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        with self.factory.begin(context.scope, "read") as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND,
                                         WORK_STABLE_ID_PREFIX + work.work_id)
            if head is None or head.revision != work.revision:
                raise ApplicationError("WORK_REVISION_STALE")
            current_work = decode_work_binding(uow.workflow.read(head))
            if current_work != work or current_work.method_ref != package.payload.method_ref:
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            if uow.submissions.resolve(submission.ref) != submission:
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            binding = resolve_declared_report_binding(uow, submission)
            if (binding.work.get("work_id") != work.work_id
                    or binding.work.get("action_id") != "incremental.implement-package"
                    or binding.package_ref != package.ref
                    or uow.implementation.resolve_package(package.ref) != package):
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            grant = uow.authorization.get_grant(binding.approval_ref)
            if type(grant.intent) is not WorkPackageAuthorizationIntent:
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            auth = grant.intent.authorization
            env_refs = tuple(env for _, scope in auth.scope_by_action
                             for env in scope.environment_refs)
            expected = self.expected_profile_ref
            if not any(env.environment_id == expected.environment_namespace
                       and env.profile_id == expected.profile_id
                       and env.profile_digest.hex == expected.digest.removeprefix("sha256:")
                       for env in env_refs):
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            return current_work, binding

    @staticmethod
    def _action_step(definition, work, step_id=None):
        if (getattr(definition, "schema_version", None) != 2
                or not _definition_matches_method(definition, work.method_ref)):
            raise ApplicationError("METHOD_PIN_MISMATCH")
        actions = tuple(action for action in definition.actions
                        if action.action_id == "incremental.implement-package")
        if len(actions) != 1:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        steps = tuple(step for step in actions[0].steps
                      if (step_id is None or step.step_id == step_id)
                      and step.name == "independently-review-report"
                      and step.kind == "invoke")
        if len(steps) != 1:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        return actions[0], steps[0]

    def _build(self, context, work, submission, package, *, review_id,
               requirement_id, step_id, definition, supplied_resources=None):
        if (type(package.payload) is not PreparedPackagePayload
                or package.payload.method_ref != work.method_ref
                or submission.package_ref != package.ref):
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        action, step = self._action_step(definition, work, step_id)
        exact_resources = tuple(self.methods.resource_ref(
            context, work.method_ref, resource.resource_id)
            for resource in definition.resources)
        if (not exact_resources or any(type(ref) is not ExactMethodResourceRef
                                       or ref.method_ref != work.method_ref
                                       for ref in exact_resources)):
            raise ApplicationError("METHOD_RESOURCE_MISMATCH")
        refs_by_id = {ref.resource_id: ref for ref in exact_resources}
        criterion_ref = refs_by_id.get(_CRITERIA_ID)
        if criterion_ref is None:
            raise ApplicationError("METHOD_RESOURCE_MISMATCH")

        # Verify every resource input of this frozen step against original
        # guarded bytes. These bytes stay full and unparsed; only the criteria
        # resource is carried into this holistic method criterion.
        resource_inputs = tuple(item for item in step.inputs
                                if item.source_kind == "resource")
        if not resource_inputs or not any(item.source_name == _CRITERIA_ID
                                          for item in resource_inputs):
            raise ApplicationError("METHOD_RESOURCE_MISMATCH")
        if supplied_resources is not None and not isinstance(supplied_resources, Mapping):
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        criteria_bytes = None
        for item in resource_inputs:
            ref = refs_by_id.get(item.source_name)
            if ref is None:
                raise ApplicationError("METHOD_RESOURCE_MISMATCH")
            raw = self.methods.read_resource(context, ref)
            if type(raw) is not bytes or not raw:
                raise ApplicationError("METHOD_RESOURCE_MISMATCH")
            if supplied_resources is not None and supplied_resources.get(item.name) != raw:
                raise ApplicationError("METHOD_RESOURCE_MISMATCH")
            if item.source_name == _CRITERIA_ID:
                criteria_bytes = raw
        try:
            criterion_text = criteria_bytes.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            raise ApplicationError("METHOD_RESOURCE_MISMATCH") from None

        target = Target("primary", submission.ref)
        check_key = CheckKey(target, _CRITERION_ID)
        criterion = CriterionDefinition(
            criterion_id=_CRITERION_ID,
            statement=criterion_text,
            checks=(CheckDefinition(
                capability_id=_CHECK_CAPABILITY,
                interface_version=_CHECK_VERSION,
                bindings=freeze_value({"method_resource_id": _CRITERIA_ID}),
            ),),
            policy=DispositionSpec(satisfied="pass", violated="block",
                                   insufficient="insufficient", unknown="insufficient"),
        )
        standard = StandardDefinition(
            schema_version=1,
            standard_id=_CRITERIA_ID,
            revision="1",
            criteria=(criterion,),
            reduction=ReductionSpec(required_criteria="all_applicable",
                                    empty_applicable_set="error",
                                    priority=("block", "manual", "pass")),
            resource_ref=ResourceRef(_CRITERIA_ID,
                                     criterion_ref.resource_digest.hex, "criteria"),
            purpose="acceptance",
        )
        requirement = ReviewRequirement(
            scope=context.scope,
            requirement_id=requirement_id,
            requirement_version=1,
            purpose="acceptance",
            expected_targets=TargetSet((target,)),
            method_ref=work.method_ref,
            criterion_set_ref=CriterionSetRef(
                _CRITERIA_ID, 1, criterion_ref.resource_digest),
            required_check_keys=(check_key,),
            eligible_reviewer_roles=("reviewer",),
            phase_key=step_id,
            schema_version=2,
            method_resource_refs=exact_resources,
        )
        plan = ReviewPlan(review_id, requirement,
                          (CheckPolicy(check_key, True, True),),
                          AggregationPolicy(), ("reviewer",))
        return SourceReviewBinding(plan, standard)

    def implementation_plan(self, context, work, *, review_id, submission, package,
                            reviewer_profile_ref, requirement_id, resources):
        profile = self._reviewer_profile(reviewer_profile_ref)
        persisted_work, _binding = self._persisted_binding(
            context, work, submission, package)
        expected_id = self.requirement_id(persisted_work, submission.ref, profile)
        if requirement_id != expected_id:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        with self.methods.guard(context, persisted_work.method_ref) as definition:
            _action, review_step = self._action_step(definition, persisted_work)
            return self._build(context, persisted_work, submission, package,
                review_id=review_id, requirement_id=expected_id,
                step_id=review_step.step_id, definition=definition,
                supplied_resources=resources).plan

    def resolve_declared_submission_plan(self, context, plan, definition):
        if type(plan) is not ReviewPlan:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        targets = plan.requirement.expected_targets.targets
        if (len(targets) != 1 or targets[0].role != "primary"
                or type(targets[0].ref) is not SubmissionRef):
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        self._reviewer_profile(encode_revision_ref(self.expected_profile_ref))
        with self.factory.begin(context.scope, "read") as uow:
            submission = uow.submissions.resolve(targets[0].ref)
            binding = resolve_declared_report_binding(uow, submission)
            work_id = binding.work.get("work_id")
            if type(work_id) is not str or not work_id:
                raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND,
                                         WORK_STABLE_ID_PREFIX + work_id)
            if head is None:
                raise ApplicationError("WORK_NOT_FOUND")
            work = decode_work_binding(uow.workflow.read(head))
            package = uow.implementation.resolve_package(binding.package_ref)
        persisted_work, checked_binding = self._persisted_binding(
            context, work, submission, package)
        if checked_binding != binding:
            raise ApplicationError("SUBMISSION_REVIEW_BINDING_MISMATCH")
        profile = encode_revision_ref(self.expected_profile_ref)
        expected_id = self.requirement_id(persisted_work, submission.ref, profile)
        expected = self._build(context, persisted_work, submission, package,
            review_id=plan.review_id, requirement_id=expected_id,
            step_id=plan.requirement.phase_key, definition=definition)
        if expected.plan != plan:
            raise ApplicationError("METHOD_REVIEW_PLAN_CHANGED")
        return expected
