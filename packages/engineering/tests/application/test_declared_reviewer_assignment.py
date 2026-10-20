"""Schema-17 reviewer assignment binds reviewers to a declared Work report.

All SQLite records are in the existing temporary EngineeringLibrary. Unit
identity queries are labeled controlled peers and never call a native Unit.
"""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.assembly import build_reviewer_assignment_usecases
from ordessa_engineering.application.usecases.reviews.assignments import (
    ASSIGN_REVIEWER, REVOKE_REVIEWER, ReviewerAssignmentUseCases,
)
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy, CheckKey, CheckPolicy, CriterionSetRef, ReviewPlan,
    ReviewRequirement,
)
from ordessa_engineering.domain.reviews.refs import SubmissionRef
from ordessa_engineering.domain.reviews.targets import Target, TargetSet
from ordessa_engineering.domain.reviews.assignments import ReviewerAssignmentRef

from test_real_source_chain import NOW, SCOPE, context
from test_work_package_report_v2 import (
    _grant_ref, _install_controlled_capture, _prepare_report, _report_value,
)
from test_work_package_dispatch_v2 import dispatch_fixture


class _ControlledRecords:
    """Return a controlled public-ref echo, without native UnitRecords."""

    def __init__(self):
        self.calls = []
        self.substitute = None

    def resolve_unit_reference(self, ref, invocation, *, input_digest):
        assert invocation.facts["purpose"] in {"reviewer", "author"}
        assert input_digest.startswith("controlled-unit-query:")
        self.calls.append((dict(ref), invocation.facts["purpose"], input_digest))
        value = dict(ref)
        if self.substitute is not None:
            value.update(self.substitute)
        return SimpleNamespace(public_ref=sealed_mapping(value))


class _Issuer:
    """Controlled current-capability guard; request attribution is not proof."""

    def __init__(self, expected_scope):
        self.expected_scope = expected_scope
        self.calls = []

    def require(self, context, capability):
        assert capability in {ASSIGN_REVIEWER, REVOKE_REVIEWER}
        assert context.scope == self.expected_scope
        self.calls.append((context.request_id, capability))

    @contextmanager
    def guard_current_capability(self, context, scope, capability):
        assert scope == self.expected_scope
        assert capability in {ASSIGN_REVIEWER, REVOKE_REVIEWER}
        yield SimpleNamespace(principal_id=context.principal_id, credential_epoch=7)


class _AuthorIdentityResolver:
    """Controlled same-authority identity lookup, not an execution query."""

    def __init__(self, factory, access, records, *, substitute=None):
        self.factory, self.access, self.records = factory, access, records
        self.calls = []
        self.substitute = substitute
        self.failure = False

    def __call__(self, context, ref, plan, request):
        self.calls.append((context, dict(ref), plan, request))
        if self.failure:
            raise RuntimeError('controlled identity source unavailable')
        value = dict(ref)
        if self.substitute is not None:
            value.update(self.substitute)
        return value


def _unit_query(_context, unit_ref, _plan, _request, *, purpose):
    return SimpleNamespace(facts={"purpose": purpose}), "controlled-unit-query:" + unit_ref["unitId"]


def _seed_plan(factory, method_control, method_ref, submission_ref, review_id):
    ctx = context("seed-declared-review-" + review_id)
    with method_control.guard(ctx, method_ref):
        criterion = method_control.resource_ref(ctx, method_ref, "implementation-review-criteria")
    target = Target("primary", submission_ref)
    key = CheckKey(target, "implementation-report")
    requirement = ReviewRequirement(
        scope=SCOPE,
        requirement_id="declared-report-" + review_id,
        requirement_version=1,
        purpose="acceptance",
        expected_targets=TargetSet((target,)),
        method_ref=method_ref,
        criterion_set_ref=CriterionSetRef("declared-report-review", 1, Digest("sha256", "a" * 64)),
        required_check_keys=(key,),
        eligible_reviewer_roles=("reviewer",),
        phase_key="review",
        schema_version=2,
        method_resource_refs=(criterion,),
    )
    plan = ReviewPlan(review_id, requirement, (CheckPolicy(key, True, True),),
        AggregationPolicy(), ("reviewer",))
    with factory.begin(SCOPE) as uow:
        uow.reviews.create_plan(plan)
        uow.commit()
    return plan


def _assignment_owner(fixture):
    issuer = _Issuer(SCOPE)
    records = _ControlledRecords()
    author_identity_resolver = _AuthorIdentityResolver(
        fixture["factory"], issuer, records)
    owner = build_reviewer_assignment_usecases(
        fixture["factory"], method_control=fixture["env"].controls, records=records,
        expected_access=issuer,
        expected_scope=SCOPE, unit_query_factory=_unit_query,
        author_identity_resolver=author_identity_resolver,
    )
    return owner, records, issuer


def _assign(owner, plan, reviewer, request_id, *, author=None):
    ctx = context(request_id)
    return owner.assign_reviewer(
        ctx, review_id=plan.review_id, expected_plan_digest=plan.plan_digest,
        request_version=0, fence=1, reviewer_unit_ref=reviewer,
        author_unit_ref=author,
    )


def _ref_from_result(result):
    value = result.result["assignment_ref"]
    return ReviewerAssignmentRef(
        SCOPE, value["assignment_id"], Digest(value["digest"]["algorithm"], value["digest"]["hex"])
    )


def test_author_identity_resolver_is_bound_and_does_not_replace_reviewer_query(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        issuer, records = _Issuer(SCOPE), _ControlledRecords()
        resolver = _AuthorIdentityResolver(fixture["factory"], issuer, records)
        owner = build_reviewer_assignment_usecases(
            fixture["factory"], method_control=fixture["env"].controls,
            records=records, expected_access=issuer, expected_scope=SCOPE,
            unit_query_factory=_unit_query, author_identity_resolver=resolver)
        author = {'environmentNamespace': 'env-a', 'unitId': 'author-a',
                  'ownerProviderRef': {'provider': 'owner-a'}, 'sourceRevision': 'rev-1'}
        context_value, plan, request = context('author-identity-resolve'), object(), object()
        assert owner._resolve_unit(context_value, author, plan, request, 'author') == canonical_bytes(author)
        assert len(resolver.calls) == 1 and records.calls == []

        reviewer = {**author, 'unitId': 'reviewer-a'}
        assert owner._resolve_unit(context_value, reviewer, plan, request, 'reviewer') == canonical_bytes(reviewer)
        assert len(resolver.calls) == 1
        assert [purpose for _ref, purpose, _digest in records.calls] == ['reviewer']

        resolver.substitute = {'sourceRevision': 'replaced-revision'}
        with pytest.raises(ApplicationError, match='UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE'):
            owner._resolve_unit(context_value, author, plan, request, 'author')
        assert len(records.calls) == 1
        resolver.substitute = None
        resolver.failure = True
        with pytest.raises(ApplicationError, match='UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE'):
            owner._resolve_unit(context_value, author, plan, request, 'author')
        assert len(records.calls) == 1

        for field, value in (('factory', object()), ('access', object()),
                             ('records', object())):
            unbound = _AuthorIdentityResolver(fixture['factory'], issuer, records)
            setattr(unbound, field, value)
            with pytest.raises(ApplicationError, match='REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE'):
                build_reviewer_assignment_usecases(
                    fixture['factory'], method_control=fixture['env'].controls,
                    records=records, expected_access=issuer, expected_scope=SCOPE,
                    unit_query_factory=_unit_query, author_identity_resolver=unbound)


def test_author_identity_resolver_is_not_enabled_on_schema15():
    factory = SimpleNamespace(begin=lambda *_args, **_kwargs: None,
                              library=SimpleNamespace(schema_version=15))
    access, records = _Issuer(SCOPE), _ControlledRecords()
    methods = SimpleNamespace(factory=factory, guard_method=lambda *_args: None)
    resolver = _AuthorIdentityResolver(factory, access, records)
    with pytest.raises(ApplicationError, match='REVIEWER_ASSIGNMENT_SOURCE_UNAVAILABLE'):
        ReviewerAssignmentUseCases(
            factory, methods, records, expected_access=access, expected_scope=SCOPE,
            unit_query_factory=_unit_query, author_identity_resolver=resolver)


def test_schema17_assignment_uses_declared_report_author_and_preserves_replay_revoke(tmp_path, monkeypatch):
    with dispatch_fixture(tmp_path, monkeypatch) as fixture:
        fixture["grant_ref"] = _grant_ref(fixture)
        with fixture["factory"].begin(SCOPE, "read") as uow:
            package = uow.implementation.resolve_package(fixture["package_ref"])
        environment_ref = dict(fixture["authorization"].scope_by_action)["edit_repository"].environment_refs[0]
        report_value = _report_value(package, environment_ref)
        _install_controlled_capture(fixture, report_value=report_value)
        submission, _report_blob, _capture = _prepare_report(fixture, report_value=report_value)
        recorded = asyncio.run(fixture["service"].execute(
            "engineering.submissions.record_report",
            {"record": __import__(
                "ordessa_engineering.domain.changes.submission_codec",
                fromlist=["submission_projection"],
            ).submission_projection(submission)},
            context("declared-review-report-record"),
        ))
        assert recorded.status == "completed"

        owner, records, issuer = _assignment_owner(fixture)
        valid_plan = _seed_plan(fixture["factory"], fixture["env"].controls,
            fixture["env"].method, submission.ref, "declared-report-valid")
        with fixture["factory"].begin(SCOPE, "read") as uow:
            binding = __import__(
                "ordessa_engineering.application.usecases.changes.declared_report",
                fromlist=["resolve_declared_report_binding"],
            ).resolve_declared_report_binding(uow, uow.submissions.resolve(submission.ref))

        # The declaration must retain the exact disposition consumer and its
        # complete report/review/package/profile/method bindings. These two
        # variants alter only the published declaration DTO used by the
        # resolver; the frozen method and stored report remain untouched.
        declaration_context = context("declared-review-declaration-rejections")
        with fixture["env"].controls.guard(
                declaration_context, fixture["env"].method) as declaration:
            action = next(item for item in declaration.actions
                          if item.action_id == binding.work["action_id"])
            disposition = next(item for item in action.steps
                               if item.name == "resolve-one-operation-disposition")
            renamed_disposition = replace(
                disposition, name="unrelated-operation-disposition")
            renamed_action = replace(
                action,
                steps=tuple(renamed_disposition if item is disposition else item
                            for item in action.steps),
            )
            wrong_consumer_declaration = replace(
                declaration,
                actions=tuple(renamed_action if item is action else item
                              for item in declaration.actions),
            )

            independence = next(item for item in disposition.admission
                                if item.kind == "reviewer_independent")
            incomplete_gate = replace(
                independence,
                inputs=tuple(name for name in independence.inputs if name != "report"),
            )
            incomplete_disposition = replace(
                disposition,
                admission=tuple(incomplete_gate if item is independence else item
                                for item in disposition.admission),
            )
            incomplete_action = replace(
                action,
                steps=tuple(incomplete_disposition if item is disposition else item
                            for item in action.steps),
            )
            missing_report_binding_declaration = replace(
                declaration,
                actions=tuple(incomplete_action if item is action else item
                              for item in declaration.actions),
            )
            with fixture["factory"].begin(SCOPE, "read") as uow:
                with pytest.raises(ApplicationError, match="METHOD_PHASE_BINDING_MISMATCH"):
                    ReviewerAssignmentUseCases._declared_report_facts(
                        uow, declaration_context, valid_plan,
                        wrong_consumer_declaration)
            with fixture["factory"].begin(SCOPE, "read") as uow:
                with pytest.raises(ApplicationError, match="METHOD_PHASE_BINDING_MISMATCH"):
                    ReviewerAssignmentUseCases._declared_report_facts(
                        uow, declaration_context, valid_plan,
                        missing_report_binding_declaration)

        author = __import__("ordessa_infrastructure.encoding", fromlist=["decode_json"]).decode_json(
            binding.unit_ref_bytes)
        reviewer = {**author, "unitId": "controlled-independent-reviewer"}

        same_unit_new_revision = {**author, "sourceRevision": "different-revision"}
        with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
            _assign(owner, valid_plan, same_unit_new_revision, "declared-review-same-unit")

        wrong_author = {**author, "unitId": "unrelated-author"}
        with pytest.raises(ApplicationError, match="UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE"):
            _assign(owner, valid_plan, reviewer, "declared-review-wrong-author", author=wrong_author)

        for field, changed in (("environmentNamespace", "another-environment"),
                               ("unitId", "another-unit"),
                               ("sourceRevision", "another-revision"),
                               ("ownerProviderRef", {"providerId": "another-owner"})):
            records.substitute = {field: changed}
            with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
                _assign(owner, valid_plan, reviewer, "declared-review-replaced-" + field)
        records.substitute = None
        with fixture["factory"].begin(SCOPE, "read") as uow:
            with pytest.raises(ApplicationError):
                uow.reviewer_assignments.active_for_review(valid_plan.review_id)

        resolver = owner.author_identity_resolver
        resolver_calls_before_positive = len(resolver.calls)
        calls_before_positive = len(records.calls)
        result = _assign(owner, valid_plan, reviewer, "declared-review-assignment")
        assert result.status == "completed"
        ref = _ref_from_result(result)
        calls_after_first = tuple(records.calls[calls_before_positive:])
        assert [purpose for _unit, purpose, _digest in calls_after_first] == ["reviewer"]
        resolver_calls_after_first = tuple(resolver.calls[resolver_calls_before_positive:])
        assert len(resolver_calls_after_first) == 1
        assert resolver_calls_after_first[0][1] == author
        all_calls_after_first = tuple(records.calls)
        all_author_calls_after_first = tuple(resolver.calls)
        stored = owner.assign_reviewer(
            context("declared-review-assignment"), review_id=valid_plan.review_id,
            expected_plan_digest=valid_plan.plan_digest, request_version=0, fence=1,
            reviewer_unit_ref=reviewer)
        assert stored.result_bytes == result.result_bytes
        assert tuple(records.calls) == all_calls_after_first
        assert tuple(resolver.calls) == all_author_calls_after_first
        with fixture["factory"].begin(SCOPE, "read") as uow:
            assignment, control = uow.reviewer_assignments.active_for_review(valid_plan.review_id)
        assert assignment.ref == ref
        assert assignment.author_unit_ref == author
        assert control.state == "active"
        assert assignment.issuer_principal_id == context("declared-review-assignment").principal_id
        assert assignment.issuer_credential_epoch == 7

        revoke_ctx = context("declared-review-revoke")
        revoked = owner.revoke_reviewer(revoke_ctx, assignment_ref=ref,
            expected_control_version=0, reason="controlled revocation")
        assert revoked.status == "completed"
        event_count = fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_unit_reviewer_assignment_events").fetchone()[0]
        revoke_replay = owner.revoke_reviewer(revoke_ctx, assignment_ref=ref,
            expected_control_version=0, reason="controlled revocation")
        assert revoke_replay.result_bytes == revoked.result_bytes
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_unit_reviewer_assignment_events").fetchone()[0] == event_count == 1
        assert tuple(records.calls) == all_calls_after_first
        assert issuer.calls.count(("declared-review-assignment", ASSIGN_REVIEWER)) == 2
        assert issuer.calls.count(("declared-review-revoke", REVOKE_REVIEWER)) == 2

        missing_ref = SubmissionRef(SCOPE.realm_id, SCOPE.project_id,
            "missing-declared-report", Digest("sha256", "f" * 64))
        with pytest.raises(ApplicationError):
            _seed_plan(fixture["factory"], fixture["env"].controls,
                fixture["env"].method, missing_ref, "declared-report-wrong-target")
        with fixture["factory"].begin(SCOPE, "read") as uow:
            with pytest.raises(ApplicationError):
                uow.reviewer_assignments.active_for_review("declared-report-wrong-target")
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_unit_reviewer_assignments WHERE review_id=?",
            ("declared-report-wrong-target",)).fetchone()[0] == 0
        assert fixture["env"].library._connection.execute(
            "SELECT COUNT(*) FROM eng_unit_reviewer_assignments").fetchone()[0] == 1
