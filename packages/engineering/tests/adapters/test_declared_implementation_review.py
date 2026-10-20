"""Direct contract checks for the declared implementation review adapter."""
from types import SimpleNamespace
import importlib
from pathlib import Path
import asyncio

import pytest

from ordessa_execution_agents.profiles import ProfileRevisionRef, encode_revision_ref
from ordessa_engineering.adapters.declared_implementation_review import (
    DeclaredImplementationReviewBindings,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import WorkBinding
from ordessa_engineering.application.orchestration.declared_implementation_results import (
    DeclaredImplementationResults,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodId, MethodRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.refs import SubmissionId, SubmissionRef


class _MethodGuard:
    def __init__(self, factory):
        self.factory = factory

    def guard(self, *_args, **_kwargs):
        raise AssertionError("plan construction is not part of this profile-only test")

    def resource_ref(self, *_args, **_kwargs):
        raise AssertionError("plan construction is not part of this profile-only test")

    def read_resource(self, *_args, **_kwargs):
        raise AssertionError("plan construction is not part of this profile-only test")


class _Profiles:
    def __init__(self, revision):
        self.revision = revision
        self.reads = []

    def get_revision(self, ref):
        self.reads.append(ref)
        return self.revision


def _adapter():
    factory = object()
    ref = ProfileRevisionRef("review-environment", "reviewer", 3, "sha256:" + "a" * 64)
    profiles = _Profiles(SimpleNamespace(ref=ref))
    adapter = DeclaredImplementationReviewBindings(
        factory, _MethodGuard(factory), profiles, ref)
    return adapter, ref, profiles


def test_requirement_identity_matches_the_declared_results_owner():
    scope = Scope("realm", "project")
    method = MethodRef(MethodId("method"), "2.7.2", 2, Digest("sha256", "b" * 64))
    work = WorkBinding("work", scope, method, 4, ())
    submission = SubmissionRef("realm", "project", SubmissionId("submission"),
                               Digest("sha256", "c" * 64))
    adapter, profile_ref, _profiles = _adapter()
    profile = encode_revision_ref(profile_ref)

    assert adapter.requirement_id(work, submission, profile) == (
        DeclaredImplementationResults.requirement_id(work, submission, profile))
    assert adapter.requirement_id(work, submission, profile) != (
        adapter.requirement_id(WorkBinding("work", scope, method, 5, ()),
                               submission, profile))


def test_fixed_profile_ref_is_rechecked_and_caller_substitution_rejected():
    adapter, ref, profiles = _adapter()

    assert adapter._reviewer_profile(encode_revision_ref(ref)) == encode_revision_ref(ref)
    assert profiles.reads == [ref]

    substitute = encode_revision_ref(ProfileRevisionRef(
        ref.environment_namespace, ref.profile_id, ref.revision + 1, "sha256:" + "d" * 64))
    with pytest.raises(ApplicationError, match="SUBMISSION_REVIEW_BINDING_MISMATCH"):
        adapter._reviewer_profile(substitute)
    assert profiles.reads == [ref]


def test_profile_revision_read_must_return_the_exact_immutable_ref():
    adapter, ref, profiles = _adapter()
    profiles.revision = SimpleNamespace(ref=ProfileRevisionRef(
        ref.environment_namespace, ref.profile_id, ref.revision + 1,
        "sha256:" + "d" * 64))

    with pytest.raises(ApplicationError, match="SUBMISSION_REVIEW_BINDING_MISMATCH"):
        adapter._reviewer_profile(encode_revision_ref(ref))
    assert profiles.reads == [ref]


def test_real_schema17_fixture_builds_and_resolves_the_production_plan(tmp_path, monkeypatch):
    flow = importlib.import_module("test_declared_implementation_results")
    dispatch_module = importlib.import_module("test_work_package_dispatch_v2")
    profile_fixture = importlib.import_module("test_native_profile_selection_phase2")
    from ordessa_engineering.domain.approvals.scope import EnvironmentRef

    profile_root = tmp_path / "profile-owner"
    profile_root.mkdir()
    with profile_fixture._profile_owner(profile_root) as (profiles, descriptor, _policy):
        created = profiles.create(
            profile_id="implementation-reviewer", name="Implementation Reviewer",
            content=profile_fixture._content(descriptor, "declared-implementation-review"),
            request=profiles.request_key("create-implementation-reviewer"),
        )
        profile_ref = created.current_revision
        grant_environment = EnvironmentRef(
            profile_ref.environment_namespace, profile_ref.profile_id,
            Digest("sha256", profile_ref.digest.removeprefix("sha256:")),
        )
        monkeypatch.setattr(dispatch_module, "ENVIRONMENT", grant_environment)

        class _Bindings:
            def __init__(self, factory, source_bindings, reviewer_adapter):
                self.factory = factory
                self.source_bindings = source_bindings
                self.reviewer_adapter = reviewer_adapter
                self.resolutions = []

            def resolve_source_plan(self, *args, **kwargs):
                return self.source_bindings.resolve_source_plan(*args, **kwargs)

            def resolve_declared_submission_plan(self, *args, **kwargs):
                result = self.reviewer_adapter.resolve_declared_submission_plan(*args, **kwargs)
                self.resolutions.append(result)
                return result

        engineering_root = tmp_path / "engineering"
        engineering_root.mkdir()
        with dispatch_module.dispatch_fixture(engineering_root, monkeypatch) as fixture:
            fixture, parameters, request_context, _submissions, _reviews = flow._prepare_flow(
                fixture, "pass", "production-implementation-review-plan")
            reviewer_adapter = DeclaredImplementationReviewBindings(
                fixture["factory"], fixture["env"].controls, profiles, profile_ref)
            bindings = _Bindings(fixture["factory"], fixture["env"].bindings,
                                 reviewer_adapter)
            fixture["service"]._review_admission.bindings = bindings
            fixture["service"]._implementation_results.plans = reviewer_adapter
            fixture["review_source"].bindings = bindings

            method_context = flow.context("read-pinned-review-criteria")
            with fixture["env"].controls.guard(method_context, fixture["env"].method):
                criteria_ref = fixture["env"].controls.resource_ref(
                    method_context, fixture["env"].method,
                    "implementation-review-criteria")
                expected_criteria = fixture["env"].controls.read_resource(
                    method_context, criteria_ref).decode("utf-8")

            result = asyncio.run(fixture["service"].execute(
                "engineering.work.invoke", parameters, request_context))
            assert result.status == "completed"
            assert result.result["method_result"]["disposition"] == "accepted"
            assert fixture["service"]._implementation_results.plans is reviewer_adapter
            # The production flow resolves the declaration independently at
            # request, record, and disposition/trust boundaries. Keep all of
            # those guards active and require each to reconstruct the same
            # complete plan and standard.
            assert len(bindings.resolutions) == 4
            selected = bindings.resolutions[0]
            assert all(binding == selected for binding in bindings.resolutions)
            assert selected.plan.requirement.method_ref == fixture["env"].method
            assert selected.plan.requirement.phase_key == "review"
            assert selected.standard.criteria[0].statement == expected_criteria
            assert selected.plan.requirement.criterion_set_ref.digest.hex == (
                criteria_ref.resource_digest.hex)
            assert len(selected.plan.requirement.required_check_keys) == 1
            assert selected.plan.requirement.required_check_keys[0].criterion_id == (
                "implementation-review")
