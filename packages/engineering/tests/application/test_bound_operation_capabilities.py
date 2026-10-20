"""Selected-owner descriptor projection; descriptors never confer permission."""
from types import SimpleNamespace
from pathlib import Path
import pytest

from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings
from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.review_bindings import SQLiteReviewBindings
from ordessa_engineering.domain.common.models.identity import Scope


def _factory(tmp_path, name):
    library = EngineeringLibrary.create(
        (tmp_path / f"{name}.sqlite").resolve(), library_id=name, schema_version=14)
    return library, SQLiteUoWFactory(library)


def _port(factory=None, access=None, **guards):
    values = dict(guards)
    if factory is not None:
        values["factory"] = factory
    if access is not None:
        values["access"] = access
    return SimpleNamespace(**values)


def _service(factory, access, **ports):
    return EngineeringService(factory, access, **ports)


def _ids(service):
    return {item.capability_id for item in service.bound_operation_capabilities().capabilities}


def _review(factory, *, response_source=None, **source_ports):
    method_control = SQLiteMethodControl(factory, SQLiteSnapshotStore(factory.library))
    bindings = SQLiteReviewBindings(factory, method_control,
        scope=Scope("bound-ops", "project"), proposal_ref=None, phases=None)
    return EngineeringReviewAdmission(factory, method_control, bindings, response_source, **source_ports)


def _full_service(factory, access):
    blobs = SimpleNamespace(authority_id=factory.authority_id)
    # Shape peers exercise projection only; they are never runtime authority
    # or evidence that the full method has production reviewer sources.
    response_source = _port(factory,
        verify_response=lambda *_: None, guard_trust=lambda *_: None)
    source_materials = _port(factory, read=lambda *_: None)
    method_guard = _port(factory, guard=lambda *_: None,
        read_resource=lambda *_: None, preparation_roles=lambda *_: ("design",))
    source_review_bindings = _port(resolve_source_plan=lambda *_: None)
    review = _review(factory, response_source=response_source,
        source_materials=source_materials, method_guard=method_guard,
        source_review_bindings=source_review_bindings)
    conversation = _port(guard_intent=lambda *_: None, guard_evidence=lambda *_: None)
    proposal_control = _port(guard_control=lambda *_args, **_kwargs: None)
    acceptance = _port(factory, guard_intent=lambda *_: None)
    submission_source = _port(guard_submission=lambda *_: None)
    records = SimpleNamespace(
        query_acp_turn=lambda *_args, **_kwargs: None,
        acp_turn_query_digest=lambda *_args, **_kwargs: None,
        authority_id=factory.authority_id)
    report_source = _port(factory,
        methods=SimpleNamespace(factory=factory), blobs=blobs,
        bindings=_port(factory, guard_report_binding=lambda *_: None),
        guard_report=lambda *_: None)
    method_control = SimpleNamespace(factory=factory)
    work_source = _port(factory, access,
        guard_start=lambda *_: None,
        guard_inputs=lambda *_: None,
        guard_condition=lambda *_: None,
        guard_step_completion=lambda *_: None)
    bindings = MethodRunBindings(factory, method_control, work_source, lambda: object())
    dispatch = _port(factory, access, execute=lambda *_: None)
    return _service(factory, access,
        proposal_control_admission=proposal_control,
        source_materials=source_materials, method_guard=method_guard,
        source_review_bindings=source_review_bindings,
        review_admission=review, blobs=blobs,
        conversation_admission=conversation,
        acceptance_admission=acceptance, submission_source=submission_source,
        current_wait_bindings=bindings,
        submission_report_source=report_source,
        execution_records=records,
        execution_query_factory=lambda *_: object(),
        execution_dispatch=dispatch)


def test_bound_operation_descriptors_require_selected_original_routes(tmp_path):
    library, factory = _factory(tmp_path, "bound-ops")
    access = _port(require=lambda *_: None)
    try:
        service = _full_service(factory, access)
        # A callable dispatch shape alone cannot advertise the declared Work
        # route. This projection-only peer must explicitly report readiness;
        # the real owner's property verifies its original selection/scope ports.
        assert "engineering.executions.dispatch" not in _ids(service)
        service._execution_dispatch.declared_implementation_ready = True
        expected = {item.capability_id for item in command_capabilities().capabilities}
        # This explicit schema14 composition has no reviewer-assignment owner.
        assignment_ops = {"engineering.reviews.assign_reviewer", "engineering.reviews.revoke_reviewer"}
        expected -= assignment_ops
        expected.add("engineering.executions.dispatch")
        # Withdrawn compiled create/advance routes are never advertised, and the
        # declarative Work route needs a method guard that can read a released
        # declaration - which this composition does not provide.
        expected -= {"engineering.work.start", "engineering.work.invoke",
                     "engineering.work.bind_inputs",
                     "engineering.work.record_command_step",
                     "engineering.work.record_dispatch_step",
                     "engineering.runs.resume", "engineering.runs.cancel"}
        actual = service.bound_operation_capabilities()
        actual_ids = tuple(item.capability_id for item in actual.capabilities)
        assert set(actual_ids) == expected
        assert not assignment_ops & set(actual_ids)
        assert actual_ids == tuple(sorted(actual_ids))
        assert actual.trust_class == "host"
        dispatch = next(item for item in owner_capabilities()
                        if item.capability_id == "engineering.executions.dispatch")
        assert next(item for item in actual.capabilities
                    if item.capability_id == dispatch.capability_id) == dispatch
        assert all(item in command_capabilities().capabilities
                   for item in actual.capabilities
                   if item.capability_id != "engineering.executions.dispatch")
    finally:
        library.close()


def test_missing_and_wrong_nonnull_sources_do_not_promote_descriptors(tmp_path):
    library, factory = _factory(tmp_path, "bound-ops-negative")
    other_library, other_factory = _factory(tmp_path, "bound-ops-foreign")
    access = _port(require=lambda *_: None)
    try:
        bare = _service(factory, access)
        assert _ids(bare) == {
            "engineering.artifacts.create",
            "engineering.artifacts.append_revision",
        }
        assert not {"engineering.proposals.create", "engineering.proposals.associate_review",
                    "engineering.packages.freeze"} & _ids(bare)
        assert _ids(_service(factory, None)) == set()
        assert _ids(_service(factory, object())) == set()

        # The source-change owner now refuses a foreign/malformed review
        # authority during assembly, before it can expose any descriptors.
        with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_MISMATCH"):
            _service(factory, access, review_admission=object(), blobs=object())

        malformed_ports = _service(factory, access,
            proposal_control_admission=_port(other_factory, access,
                guard_control=lambda *_: None),
            conversation_admission=_port(other_factory, access,
                guard_intent=lambda *_: None, guard_evidence=lambda *_: None),
            review_admission=_review(factory),
            submission_report_source=_port(other_factory, access,
                guard_report=lambda *_: None),
            execution_records=object(), execution_query_factory=lambda *_: object(),
            current_wait_bindings=object())
        ids = _ids(malformed_ports)
        assert "engineering.proposals.withdraw" not in ids
        assert "engineering.proposals.supersede" not in ids
        assert not ({"engineering.approvals.prepare_intent",
                     "engineering.changes.apply",
                     "engineering.packages.freeze"} & ids)
        assert "engineering.submissions.record_report" not in ids
        assert "engineering.work.bind_inputs" not in ids
        assert not ({"engineering.work.start", "engineering.work.record_command_step",
                     "engineering.work.record_dispatch_step", "engineering.runs.resume",
                     "engineering.executions.dispatch"} & ids)

        # A syntactically valid WorkBindings object cannot retain a foreign
        # source authority; the source is checked again at projection time.
        foreign_work = MethodRunBindings(factory, SimpleNamespace(factory=factory),
            _port(other_factory, access,
                guard_start=lambda *_: None,
                guard_condition=lambda *_: None,
                guard_step_completion=lambda *_: None), lambda: object())
        service = _service(factory, access, current_wait_bindings=foreign_work)
        assert not ({"engineering.work.start", "engineering.work.record_command_step",
                     "engineering.runs.resume"} & _ids(service))

        # Constructor validation is not the sole fence; the projection also
        # rechecks a selected dispatch route if its binding changes later.
        service = _full_service(factory, access)
        service._execution_dispatch = _port(other_factory, access, execute=lambda *_: None)
        assert "engineering.executions.dispatch" not in _ids(service)
        assert "engineering.work.record_dispatch_step" not in _ids(service)
    finally:
        other_library.close()
        library.close()


def test_unbound_original_reader_does_not_advertise_missing_response_sources(tmp_path):
    library, factory = _factory(tmp_path, "review-bootstrap-capabilities")
    access = _port(require=lambda *_: None)
    try:
        review = _review(factory)
        service = _service(factory, access, review_admission=review,
            blobs=SimpleNamespace(authority_id=factory.authority_id),
            conversation_admission=_port(
                guard_intent=lambda *_: None, guard_evidence=lambda *_: None))
        ids = _ids(service)
        assert "engineering.reviews.request" in ids
        assert "engineering.reviews.record" not in ids
        assert not any(name.startswith("engineering.approvals.") for name in ids)
        assert "engineering.changes.apply" not in ids
        assert "engineering.packages.freeze" not in ids
        # Merely having a non-null binding object is not an original reader.
        for bindings in (None, object(), _port(object(), resolve_bindings=lambda *_: None)):
            review.bindings = bindings
            assert "engineering.reviews.request" not in _ids(service)
    finally:
        library.close()


def test_fixed_method_still_refuses_when_only_request_owner_is_initialized(tmp_path):
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.methods import load_method, compile_method
    from ordessa_engineering.methods.definitions.models import MethodSource

    library, factory = _factory(tmp_path, "fixed-method-bootstrap")
    try:
        service = _service(factory, _port(require=lambda *_: None),
            review_admission=_review(factory))
        source = MethodSource(Path(__file__).resolve().parents[4]
            / "methods/incremental-engineering/candidates/2.6.0")
        loaded = load_method(source, FileResourceReader())
        assert loaded.ok, loaded.error
        compiled = compile_method(loaded.value,
            service.bound_operation_capabilities(), "bootstrap-test/1")
        assert not compiled.ok
        assert compiled.error.code == "UNKNOWN_CAPABILITY"
        # The historical schema-1 candidate's first missing route is now the
        # retired fresh-v1 Proposal writer; missing response authority remains
        # independently visible rather than being hidden by that earlier gap.
        assert compiled.error.pointer == "/requires/2"
        assert "engineering.proposals.create" in compiled.error.message
        assert "engineering.reviews.record" not in _ids(service)
    finally:
        library.close()


def test_original_work_owner_can_be_composed_before_subject_selection(tmp_path):
    from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.registry import load_registry
    from ordessa_engineering.application.assembly.method_runs import build_method_run_bindings

    library, factory = _factory(tmp_path, "original-work-bootstrap")
    try:
        access = _port(require=lambda *_: None)
        review = _review(factory)
        blobs = SQLiteBlobStore(library)
        source = SQLitePersistedMethodWorkSource(factory, review.methods,
            blobs=blobs, review_bindings=review.bindings)
        bindings = build_method_run_bindings(factory, method_control=review.methods,
            work_condition_source=source, registry_loader=load_registry)
        service = _service(factory, access, review_admission=review, blobs=blobs,
            current_wait_bindings=bindings)
        assert source.review_bindings is review.bindings
        assert bindings.registry_loader is load_registry
        assert review.bindings.proposal_ref is None
        assert "engineering.reviews.request" in _ids(service)
        # Declarative Work is advertised only when a declaration-reading method
        # guard is composed; this composition has none, so it stays unavailable.
        assert "engineering.work.start" not in _ids(service)
        assert not {"engineering.work.bind_inputs", "engineering.work.record_command_step",
                    "engineering.work.record_dispatch_step", "engineering.runs.resume",
                    "engineering.runs.cancel"} & _ids(service)
        # Source association never supplies missing native dispatch or results.
        assert "engineering.executions.dispatch" not in _ids(service)
        assert "engineering.reviews.record" not in _ids(service)
    finally:
        library.close()
