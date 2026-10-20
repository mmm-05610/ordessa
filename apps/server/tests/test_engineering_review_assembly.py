"""Fail-closed owner selection checks for review-port assembly."""
import pytest
from dataclasses import replace

from ordessa_engineering.application.api import ApplicationError
from ordessa_server.composition.engineering_review_assembly import (
    build_engineering_review_ports,
)


def _callbacks():
    return {
        "author_unit_resolver": lambda *_args: None,
        "invocation_resolver": lambda *_args, **_kwargs: None,
        "unit_query_factory": lambda *_args, **_kwargs: None,
    }


def test_review_assembly_refuses_non_original_unit_owner_before_any_binding():
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        build_engineering_review_ports(
            object(), object(), object(), unit_owner=object(),
            method_control=object(), blobs=object(), proposal_ref=object(),
            phases=(), **_callbacks(),
        )


@pytest.mark.parametrize("missing", [
    "author_unit_resolver", "invocation_resolver", "unit_query_factory",
])
def test_review_assembly_requires_each_original_identity_or_query_producer(missing):
    callbacks = _callbacks()
    callbacks[missing] = None
    with pytest.raises(ApplicationError, match="UNIT_REVIEW_SOURCE_AUTHORITY_UNAVAILABLE"):
        build_engineering_review_ports(
            object(), object(), object(), unit_owner=object(),
            method_control=object(), blobs=object(), proposal_ref=object(),
            phases=(), **callbacks,
        )


def test_selected_original_owner_builds_real_review_service_graph(tmp_path):
    """Bind actual records/library/service; absent persisted business inputs remain refusals."""
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.review_sources import ConfiguredReviewPhase
    from ordessa_engineering.adapters.review_sources import ConfiguredMaterialSubmission
    from ordessa_engineering.application.api import bound_review_check_capabilities
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.commands import CommandKey
    from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.changes.refs import ProposalRef
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as EngineeringScope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.engineering_review_assembly import build_engineering_review_ports
    from ordessa_system_access_bindings.engineering_wire import EngineeringWireBinding
    from test_selected_unit_shutdown import _build_selected_runtime

    runtime, _environment = _build_selected_runtime(tmp_path)
    library = EngineeringLibrary.create(
        (tmp_path / "review.sqlite").resolve(), library_id="review-assembly", schema_version=15)
    try:
        unit_owner = runtime.unit_execution_owner
        scope = unit_owner.permission.scope
        factory = SQLiteUoWFactory(library)
        method_control = SQLiteMethodControl(factory, SQLiteSnapshotStore(library))
        blobs = SQLiteBlobStore(library)
        proposal_ref = ProposalRef(
            scope.realm_id, scope.project_id, "selected-change", "selected-proposal",
            Digest("sha256", "a" * 64))
        phases = (ConfiguredReviewPhase(
            "review", ("reviewer",), workflow_node_id="review"),)
        material_submissions = (ConfiguredMaterialSubmission(
            ArtifactRevisionRef(scope.realm_id, scope.project_id,
                "configured-material", "revision-1", Digest("sha256", "c" * 64)),
            CommandKey(scope.realm_id, "material-author", "material-create-request")),)

        def no_author_submission(_context, _plan):
            raise ApplicationError("SUBMISSION_AUTHOR_SOURCE_UNAVAILABLE")

        def no_review_invocation(_context, _plan, _request, *, prompt_binding):
            raise ApplicationError("UNIT_REVIEW_SOURCE_UNAVAILABLE")

        def no_unit_query(_context, _unit_ref, _plan, _request, *, purpose):
            raise ApplicationError("UNIT_REVIEW_AUTHORITY_UNAVAILABLE")

        observed = {}

        def ports_factory(actual_factory, access, actual_scope):
            observed["access"] = access
            observed["ports"] = build_engineering_review_ports(
                actual_factory, access, actual_scope,
                unit_owner=unit_owner,
                method_control=method_control,
                blobs=blobs,
                proposal_ref=proposal_ref,
                phases=phases,
                author_unit_resolver=no_author_submission,
                invocation_resolver=no_review_invocation,
                unit_query_factory=no_unit_query,
                material_submissions=material_submissions,
            )
            async def selected_review_run(context, plan, request):
                raise ApplicationError("TEST_REVIEW_RUN_NOT_INVOKED")

            def selected_plan_factory(context, binding, *, review_id, baseline, candidate):
                raise ApplicationError("TEST_REVIEW_PLAN_NOT_INVOKED")

            observed["ports"] = replace(observed["ports"],
                review_run=selected_review_run,
                review_plan_factory=selected_plan_factory)
            return observed["ports"]

        binding = EngineeringWireBinding(
            factory, runtime.wire.identity_authority, scope=scope,
            application_ports_factory=ports_factory)
        ports = observed["ports"]
        records = unit_owner.records
        assert ports.blobs is blobs
        assert ports.review_admission.factory is factory
        assert ports.review_admission.methods is method_control
        assert ports.review_admission.bindings.factory is factory
        assert ports.reviewer_assignments.factory is factory
        assert ports.reviewer_assignments.access is binding.access
        assert ports.reviewer_assignments.records is records
        assert ports.reviewer_assignments.expected_scope is scope
        assert ports.reviewer_assignments.unit_query_factory is no_unit_query
        assert binding.service._review_change_steps.runnable is True
        assert binding.service._review_change_steps.review_run is ports.review_run
        assert binding.service._review_change_steps.plan_factory is ports.review_plan_factory
        assert ports.reviewer_assignments.author_unit_resolver is no_author_submission
        authorship_source = ports.reviewer_assignments.authorship_source
        assert authorship_source.factory is factory
        assert authorship_source.methods is method_control
        assert authorship_source.review_bindings is ports.review_admission.bindings
        assert authorship_source.material_submissions == material_submissions
        unit_check = ports.review_admission.source.sources["decision"].source
        assert unit_check.bindings.authorship_source is authorship_source
        assert unit_check.authority.authorship_source is authorship_source
        assert unit_check.authority.assignments.authorship_source is authorship_source

        check_caps = bound_review_check_capabilities(
            ports.review_admission, expected_factory=factory,
            expected_access=binding.access, expected_scope=scope)
        assert len(check_caps.capabilities) == 5
        assert {item.capability_id for item in check_caps.capabilities} == {
            "ordessa.sources.integrity", "ordessa.claims.coverage",
            "ordessa.schema.validate", "ordessa.submission.binding",
            "ordessa.decision.evaluate",
        }
        service_caps = binding.service.bound_operation_capabilities()
        operations = {item.capability_id for item in service_caps.capabilities}
        assert {
            "engineering.reviews.request", "engineering.reviews.record",
            "engineering.reviews.assign_reviewer", "engineering.reviews.revoke_reviewer",
        } <= operations

        # Typed selected references do not stand in for persisted Work. The
        # original method-control/Proposal reader refuses before producing any
        # bindings because this fresh library has no published/selected method.
        assert ports.review_admission.bindings.proposal_ref is proposal_ref
        context = CommandContext(
            EngineeringScope(scope.realm_id, scope.project_id),
            "selected-review-test-principal",
            ActorRef("selected-review-test-principal", "service", "test-owner"),
            "missing-selected-method", "2026-10-12T00:00:00.000000Z", "review-test")
        method_ref = MethodRef(
            "selected-test-method", "1.0.0", 1, Digest("sha256", "b" * 64))
        with pytest.raises(ApplicationError, match="METHOD_CONTROL_UNAVAILABLE"):
            ports.review_admission.bindings.resolve_bindings(context, method_ref, "review")
    finally:
        library.close()
        if runtime.stop_state == "idle":
            runtime.stop()
