"""Exact intent routing to existing owners; underlying guards stay authoritative."""
from contextlib import contextmanager
from dataclasses import replace

import pytest

from ordessa_engineering.application.assembly import (
    build_intent_admission_router, build_change_intent_admission,
    build_implementation_intent_admission, build_submission_acceptance_admission,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.changes.apply import ChangeIntentAdmission
from ordessa_engineering.application.usecases.packages.authorization import ImplementationIntentAdmission
from ordessa_engineering.application.usecases.changes.acceptance_closure import SubmissionAcceptanceIntentAdmission
from submission_wait_business_fixture import build_submission_wait_fixture
from test_change_intent_admission import env, ready
from test_method_control_admission import context
from test_method_report_bindings80 import _authorization_intent


def test_router_delegation_with_explicit_guard_spies(env, tmp_path):
    change_intent, bindings = ready(env)
    implementation_fixture = build_submission_wait_fixture(tmp_path / "implementation")
    acceptance_fixture = build_submission_wait_fixture(tmp_path / "acceptance", report_phase=True)
    factory = env[2]
    methods = env[4]
    change = ChangeIntentAdmission(factory, methods, bindings)
    implementation = ImplementationIntentAdmission(factory, methods, bindings)
    acceptance = SubmissionAcceptanceIntentAdmission(factory, methods, bindings)
    router = build_intent_admission_router(
        factory, change=change, implementation=implementation, acceptance=acceptance)
    implementation_intent = implementation_fixture["grant"].intent
    acceptance_intent = _authorization_intent(acceptance_fixture)
    cases = ((change, change_intent),
             (implementation, implementation_intent),
             (acceptance, acceptance_intent))
    calls = []
    try:
        for index, (owner, intent) in enumerate(cases):
            marker = object()

            @contextmanager
            def selected_guard(actual_context, actual_intent, *, _owner=owner,
                               _marker=marker):
                calls.append(("enter", _owner, actual_context, actual_intent))
                try:
                    yield _marker
                finally:
                    calls.append(("exit", _owner, actual_context, actual_intent))

            owner.guard_intent = selected_guard
            selected_context = context(f"router-{index}")
            with router.guard_intent(selected_context, intent) as selected:
                assert selected is marker
                with factory.begin(selected_context.scope) as uow:
                    uow.commit()
                assert calls[-1] == ("enter", owner, selected_context, intent)
            assert calls[-1] == ("exit", owner, selected_context, intent)

        assert [(entry[1], entry[3]) for entry in calls if entry[0] == "enter"] == list(cases)
        with pytest.raises(ApplicationError, match="INTENT_OWNER_UNAVAILABLE"):
            with router.guard_intent(context("unknown"), object()):
                pass
    finally:
        implementation_fixture["library"].close()
        acceptance_fixture["library"].close()


def test_router_runs_each_original_strict_guard_and_preserves_commit_boundary(env, tmp_path):
    change_intent, change_bindings = ready(env)
    change_factory, change_methods = env[2], env[4]
    change_owners = (
        build_change_intent_admission(change_factory, method_control=change_methods, bindings=change_bindings),
        build_implementation_intent_admission(change_factory, method_control=change_methods, bindings=change_bindings),
        build_submission_acceptance_admission(change_factory, method_control=change_methods, bindings=change_bindings),
    )

    implementation_fixture = build_submission_wait_fixture(tmp_path / "real-implementation")
    acceptance_fixture = build_submission_wait_fixture(tmp_path / "real-acceptance", report_phase=True)
    implementation_intent = replace(
        implementation_fixture["grant"].intent, supporting_review_refs=())

    def owners_for(e):
        factory, methods, bindings = e["factory"], e["controls"], e["bindings"]
        return (
            build_change_intent_admission(factory, method_control=methods, bindings=bindings),
            build_implementation_intent_admission(factory, method_control=methods, bindings=bindings),
            build_submission_acceptance_admission(factory, method_control=methods, bindings=bindings),
        )

    cases = (
        (change_owners, change_factory, context("real-change"), change_intent,
         None, "METHOD_REQUIREMENTS_CHANGED"),
        (owners_for(implementation_fixture), implementation_fixture["factory"],
         implementation_fixture["context"], implementation_intent,
         None, "METHOD_REQUIREMENTS_CHANGED"),
        (owners_for(acceptance_fixture), acceptance_fixture["factory"],
         acceptance_fixture["context"], _authorization_intent(acceptance_fixture),
         acceptance_fixture["submission"].ref, "CONSENT_BINDING_MISMATCH"),
    )
    try:
        for owners, factory, actual_context, intent, expected_submission_ref, refusal in cases:
            router = build_intent_admission_router(
                factory, change=owners[0], implementation=owners[1], acceptance=owners[2])
            with router.guard_intent(actual_context, intent) as admitted:
                if expected_submission_ref is None:
                    assert admitted is None
                else:
                    assert admitted.submission.ref == expected_submission_ref
                    assert admitted.package.ref == acceptance_fixture["package"].ref
                with factory.begin(actual_context.scope) as uow:
                    uow.commit()

            requirement = intent.required_review_requirements[0]
            altered_requirement = replace(
                requirement, requirement_version=requirement.requirement_version + 1)
            altered = replace(
                intent,
                required_review_requirements=(altered_requirement,
                    *intent.required_review_requirements[1:]),
            )
            with pytest.raises(ApplicationError, match=refusal):
                with router.guard_intent(actual_context, altered):
                    pass

        implementation_router = build_intent_admission_router(
            implementation_fixture["factory"],
            change=owners_for(implementation_fixture)[0],
            implementation=owners_for(implementation_fixture)[1],
            acceptance=owners_for(implementation_fixture)[2],
        )
        with pytest.raises(ApplicationError, match="NOT_FOUND"):
            with implementation_router.guard_intent(
                    implementation_fixture["context"], implementation_fixture["grant"].intent):
                pass
    finally:
        implementation_fixture["library"].close()
        acceptance_fixture["library"].close()


def test_router_rejects_wrong_owner_type_factory_and_method_control(env):
    _, _, factory, _, methods = env
    _, bindings = ready(env)
    good = (
        ChangeIntentAdmission(factory, methods, bindings),
        ImplementationIntentAdmission(factory, methods, bindings),
        SubmissionAcceptanceIntentAdmission(factory, methods, bindings),
    )
    with pytest.raises(ApplicationError, match="INTENT_ADMISSION_OWNER_UNAVAILABLE"):
        build_intent_admission_router(factory, change=object(),
            implementation=good[1], acceptance=good[2])

    class OtherMethodControl:
        def __init__(self, selected_factory):
            self.factory = selected_factory

    foreign = ChangeIntentAdmission(object_factory := object(),
        OtherMethodControl(object_factory), bindings)
    with pytest.raises(ApplicationError, match="INTENT_ADMISSION_AUTHORITY_MISMATCH"):
        build_intent_admission_router(factory, change=foreign,
            implementation=good[1], acceptance=good[2])

    good[2].methods = OtherMethodControl(factory)
    with pytest.raises(ApplicationError, match="INTENT_ADMISSION_METHOD_AUTHORITY_MISMATCH"):
        build_intent_admission_router(factory, change=good[0],
            implementation=good[1], acceptance=good[2])
