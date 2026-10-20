"""Original report/acceptance source assembly identity checks; no data effects."""
from types import SimpleNamespace

from ordessa_units.bindings.profile_admission import UnitProfileAdmission
import pytest

from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.review_sources import (
    ConfiguredReviewPhase,
    SQLiteMethodUnitReportBindings,
    SQLiteReviewBindings,
)
from ordessa_engineering.adapters.submission_sources import SQLiteSubmissionSource
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.usecases.changes.acceptance_closure import (
    SubmissionAcceptanceIntentAdmission,
)
from ordessa_engineering.application.usecases.changes.report_source import MethodUnitReportSource
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_server.composition.engineering_submission_assembly import (
    attach_method_unit_submission_ports,
)
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts


def _graph(tmp_path, *, phase_key="selected-report-phase"):
    import time
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_execution_agents.harness.providers.registry import (
        HarnessDefinitionDeclaration, HarnessDefinitionDescriptor,
        HarnessInstallationObservation,
    )
    from ordessa_execution_agents.profiles import ProfileService
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.pi_selection import PiExecutionPorts, PiExecutionSelection
    from ordessa_server.composition.product_runtime import build_product_runtime
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.assembly import UnitRunPermission

    product_root = tmp_path / "product"
    fingerprint = ProtectedFingerprintHmac(
        {"controlled": b"controlled-fingerprint-value-32!!"}, active_key_id="controlled")
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(product_root)
    try:
        context = setup.unit_runtime.context
        definition = {"environmentNamespace": context.environment_namespace,
                      "definitionId": "pi", "revision": "1"}
        profiles = ProfileService(UnitProfileAdmission(context))
        profile = profiles.create(profile_id="report-selected-profile", name="Selected report profile",
            content={"schemaVersion": "1", "harnessDefinitionRef": definition,
                "declarations": [{"declarationId": "selected-model",
                    "configurationKind": "assets.model-provider", "schemaVersion": "1",
                    "action": "value", "requirement": "required",
                    "payload": {"provider": "opencode", "model": "step-5-preview-free",
                        "protocol": "openai-chat", "endpoint": "https://opencode.ai/zen/v1"}}]},
            request=profiles.request_key("create-report-selected-profile"))
        revision = profiles.get_revision(profile.current_revision)
    finally:
        setup.stop()
    local_root = tmp_path / "local"
    local_root.mkdir()
    environments = EnvironmentManager(store=SQLiteEnvironmentStore(tmp_path / "environments.sqlite"),
        providers={"local": LocalEnvironmentResourceProvider(default_root=str(local_root))})
    instance = environments.register("local", str(local_root))
    descriptor = HarnessDefinitionDescriptor("pi", definition, "sha256:" + "a" * 64,
        "acp/v1", "controlled", "controlled", ("prepare", "start", "stop", "release"))
    declaration = HarnessDefinitionDeclaration(descriptor,
        lambda *_args: HarnessInstallationObservation(
            state="present", native_version=True, version_verified="controlled",
            evidence_ref="controlled-installation"))
    selection = PiExecutionSelection("agent", revision.ref, instance.identity, "local", "none", True,
        "selected-model", "opencode", "step-5-preview-free", "/bin/true", "a" * 64,
        "/bin/true", str(tmp_path / "unused-env-path"))

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        scope = Scope(selection.profile_revision.environment_namespace, "report-assembly-test")
        actions = frozenset({"prepare", "start", "interaction", "stop", "release"})
        authority.replace_grants((AccessGrant(
            scope, tuple("execution.units." + action for action in sorted(actions))),))
        principal = authority.authenticate("Bearer " + runtime.token)
        return UnitRunPermission(access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(local_root),
            actions=actions, expires_at=time.time() + 600)

    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
        ("step-5-preview-free",), None, acp_turn_opt_in=True,
        effect_write_guard_factory=lambda *_args: None)
    runtime = build_product_runtime(product_root, pi_selection=selection, pi_ports=ports)
    library = EngineeringLibrary.create(
        (tmp_path / "submission-assembly.sqlite").resolve(),
        library_id="submission-assembly-test", schema_version=15)
    factory = SQLiteUoWFactory(library)
    methods = SQLiteMethodControl(factory, SQLiteSnapshotStore(library))
    blobs = SQLiteBlobStore(library)
    unit_owner = runtime.unit_execution_owner
    wire_scope = unit_owner.permission.scope
    owner_scope = EngineeringCommandAccess.owner_scope(wire_scope)
    review_bindings = SQLiteReviewBindings(
        factory, methods, scope=owner_scope,
        proposal_ref=ProposalRef(wire_scope.realm_id, wire_scope.project_id, "change", "proposal",
            Digest("sha256", "a" * 64)),
        phases=(ConfiguredReviewPhase(
            phase_key, ("reviewer",), workflow_node_id=phase_key),),
    )
    records = unit_owner.records
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_server.composition.engineering_work_assembly import original_dispatch_query_factory
    query_factory = original_dispatch_query_factory(
        unit_owner, records=records,
        request_factory=lambda _binding: RequestKey(
            unit_owner.admission.environment_namespace,
            unit_owner.permission.principal_scope,
            "report-assembly-selected-request"))
    access = EngineeringCommandAccess(runtime.wire.identity_authority)
    from ordessa_server.composition.engineering_work_assembly import build_engineering_work_bindings
    method_runs = build_engineering_work_bindings(
        factory, access, wire_scope, method_control=methods, blobs=blobs,
        review_bindings=review_bindings, records=records,
        execution_query_factory=query_factory)
    base_ports = EngineeringApplicationPorts(blobs=blobs, current_wait_bindings=method_runs)
    return (runtime, library, factory, methods, blobs, review_bindings,
        records, query_factory, method_runs, base_ports)


def test_assembly_uses_original_report_and_acceptance_builders_on_same_graph(tmp_path):
    runtime, library, factory, methods, blobs, review_bindings, records, query_factory, method_runs, base_ports = _graph(tmp_path)
    try:
        result = attach_method_unit_submission_ports(
            base_ports, factory=factory, method_control=methods, blobs=blobs,
            review_bindings=review_bindings, method_runs=method_runs,
            phase_key="selected-report-phase",
            execution_records=records, execution_query_factory=query_factory)

        report = result.submission_report_source
        acceptance = result.acceptance_admission
        assert type(report) is MethodUnitReportSource
        assert type(report.bindings) is SQLiteMethodUnitReportBindings
        assert report.factory is factory
        assert report.methods is methods
        assert report.blobs is blobs
        assert report.bindings.factory is factory
        assert report.bindings.methods is methods
        assert report.bindings.phase_key == "selected-report-phase"
        assert type(acceptance) is SubmissionAcceptanceIntentAdmission
        assert acceptance.factory is factory
        assert acceptance.methods is methods
        assert acceptance.bindings is review_bindings
        assert callable(acceptance.bindings.resolve_acceptance_submission)
        assert type(result.submission_source) is SQLiteSubmissionSource
        assert result.submission_source.factory is factory
        assert result.submission_source.method_runs is method_runs
        assert result.submission_source.report_source is report
        assert result.submission_source.records is records
        assert result.submission_source.blobs is blobs
        assert result.submission_source.execution_query_factory is query_factory
        assert result.blobs is blobs
        assert result.current_wait_bindings is method_runs
        assert result.review_admission is None
        assert result.execution_records is records
        assert result.execution_query_factory is query_factory
        assert records.acp_turn_available is True
        assert records.journal.acp_turn_opt_in is True
        assert callable(query_factory)
        rebound = attach_method_unit_submission_ports(
            result, factory=factory, method_control=methods, blobs=blobs,
            review_bindings=review_bindings, method_runs=method_runs,
            phase_key="selected-report-phase", execution_records=records,
            execution_query_factory=query_factory)
        assert rebound.submission_report_source is report
        assert rebound.acceptance_admission is acceptance
        assert rebound.submission_source is result.submission_source
    finally:
        library.close()
        if runtime.stop_state == "idle":
            runtime.stop()


@pytest.mark.parametrize("change", ["phase_type", "foreign_method_control", "foreign_blobs", "foreign_method_runs"])
def test_assembly_rejects_invalid_or_foreign_owner_inputs_before_binding(tmp_path, change):
    runtime, library, factory, methods, blobs, review_bindings, records, query_factory, method_runs, base_ports = _graph(tmp_path)
    try:
        kwargs = {}
        if change == "phase_type":
            kwargs["phase_key"] = True
        elif change == "foreign_method_control":
            kwargs["method_control"] = SimpleNamespace(factory=factory)
        elif change == "foreign_method_runs":
            kwargs["method_runs"] = SimpleNamespace(factory=factory, methods=methods)
        else:
            kwargs["blobs"] = SimpleNamespace(authority_id=factory.authority_id)
        inputs = dict(factory=factory, method_control=methods, blobs=blobs,
            review_bindings=review_bindings, method_runs=method_runs,
            phase_key="selected-report-phase",
            execution_records=records, execution_query_factory=query_factory)
        inputs.update(kwargs)
        with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_AUTHORITY_MISMATCH"):
            attach_method_unit_submission_ports(base_ports, **inputs)
    finally:
        library.close()
        if runtime.stop_state == "idle":
            runtime.stop()


def test_assembly_rejects_conflicting_prebound_records_identity(tmp_path):
    runtime, library, factory, methods, blobs, review_bindings, records, query_factory, method_runs, base_ports = _graph(tmp_path)
    foreign = EngineeringApplicationPorts(
        blobs=blobs,
        execution_records=object(), execution_query_factory=query_factory)
    try:
        with pytest.raises(ApplicationError, match="SUBMISSION_REPORT_AUTHORITY_MISMATCH"):
            attach_method_unit_submission_ports(
                foreign, factory=factory, method_control=methods, blobs=blobs,
                review_bindings=review_bindings, method_runs=method_runs,
                phase_key="selected-report-phase",
                execution_records=records, execution_query_factory=query_factory)
    finally:
        library.close()
        if runtime.stop_state == "idle":
            runtime.stop()
