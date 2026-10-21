"""Joint acceptance: the case assembly and the real dispatch binder on one graph.

This is the single test that drives DSH-1's ``assemble_declared_work_case`` the
way the entry does, over a *product* runtime whose owner carries the ACP opt-in
and the deferred effect-write factory (``_make_runtime(..., defer_effect_write_guard_factory=True)``),
a real schema-17 Blob/Method owner and a real ``ProjectSourceMaterials``.

It asserts the positive shape the review asked for:

* the implementation binder attaches the generation handles, the dispatch owner
  and the *same* review runtime as the effect-write factory;
* ``before_review`` is the review runtime's own hook, and it refuses at the
  delivery gate before any Unit exists;
* an owner without the ACP opt-in is refused (the negative case).

No model, transport, Unit or real database write happens here.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_decision.definitions.models import PolicyRef
from ordessa_decision.definitions.ports import DecisionServices, ReadContext
from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef
from ordessa_engineering.domain.artifacts.models import MethodContent, MethodRef
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.models import ChangeSet
from ordessa_engineering.domain.changes.refs import ProposalRef
from ordessa_engineering.domain.changes.submission import (
    ExecutionRecordRef, Submission, SubmissionCoverage,
)
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
    EngineeringLibrary,
)
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.domain.artifacts.provenance import (
    SourceLocator, SourceRef, VersionCapture,
)
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as DomainScope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_wire import (
    EngineeringApplicationPorts, EngineeringWireBinding,
)

from .test_selected_unit_shutdown import _build_selected_runtime

# ``test_engineering_native_dispatch_assembly`` imports its sibling fixture by
# its top-level name; make the tests directory importable the same way here.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engineering_native_dispatch_assembly import _make_runtime  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
ENTRY_PATH = REPO / 'tooling/checks/server_product/run_declared_work_case.py'
REVIEWER = ActorRef('source-reviewer', 'service', 'explicit-host-selection')
SELECTION = (REVIEWER, ('reviewer',), 1)


def _entry():
    spec = importlib.util.spec_from_file_location('run_declared_work_case', ENTRY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def _source_materials(factory, scope, root: Path):
    ref = SourceRef(
        source_id='joint-source', kind='document',
        locator=SourceLocator(kind='document', provider='project-files',
                              document_id='allowed-report.txt'),
        capture=VersionCapture('1', Digest('sha256', 'c' * 64)),
        captured_at='2026-10-17T13:00:00.000000Z',
        captured_by=ActorRef('agent', 'agent', 'principal-a'),
        media_type='text.plain', byte_length=14)
    return ProjectSourceMaterials(factory, scope=DomainScope(scope.realm_id, scope.project_id),
                                  root=str(root), source_mappings=((ref, 'allowed-report.txt'),))


def _reviewer_source(factory, blobs, controls, materials, bindings, *, scope, principal_id):
    services = DecisionServices(
        read=None, candidate_source=None, proposal_source=None, validator=None,
        decision_provider=SimpleNamespace(binding_ref='jev-source/1',
                                          settings_digest='sha256:' + 'a' * 64),
        evidence=SimpleNamespace(durable=True), policy={},
        read_context=ReadContext(authority=object(), scope_ref='scope-a'),
        policy_refs=(PolicyRef('ordessa.product.v1.source-review', '1',
                               'sha256:' + 'b' * 64),),
        mode='real')
    return DecisionReviewerSource(
        factory, blobs, controls, materials, bindings,
        scope=scope, principal_id=principal_id, reviewer=REVIEWER,
        roles=('reviewer',), services=services)


def _seed_submission(factory, scope, actor, *, submission_id='submission-a'):
    """Register one legal schema-2 report submission through the real owner.

    Fields are the minimum the domain itself accepts (no relaxed validation):
    one proposal coverage entry, one rendered report body, no execution facts.
    """
    digest = Digest('sha256', 'a' * 64)
    method_ref = MethodRef('method-a', '2.7.2', 2, digest)
    exact = ExactMethodResourceRef(method_ref, 'report.json', digest, 'report-schema')
    raw = ('{"statement":"joint fixture report","submission":"%s"}' % submission_id).encode()
    body = BlobRef(Digest('sha256', hashlib.sha256(raw).hexdigest()), len(raw),
                   'application/json', 'report-body-' + submission_id)
    content = MethodContent(exact, raw, rendered_body_ref=body)
    proposal = ProposalRef(scope.realm_id, scope.project_id, 'change-a', 'proposal-a', digest)
    approval = ApprovalRef(scope.realm_id, scope.project_id, 'approval-a', digest)
    package = ImplementationPackageRef(scope.realm_id, scope.project_id, 'package-a', digest)
    execution = ExecutionRecordRef('env-a', 'unit-a', canonical_bytes({'provider': 'joint'}),
                                   'rev-1', 'op-a', digest, body)
    record = Submission(
        scope, submission_id, '2026-10-17T14:00:00.000000Z', actor,
        ChangeSet((proposal,)), (approval,), package, execution,
        (), (), (), (), (body,), (), (),
        (SubmissionCoverage(proposal, (body,), (), (), 'implemented'),), (),
        method_content=content, schema_version=2)
    with factory.begin(scope) as uow:
        ref = uow.submissions.create(record)
        uow.commit()
    return ref


def _context(realm_id, project_id, principal_id, request_id='joint-1'):
    return CommandContext(
        scope=DomainScope(realm_id, project_id), principal_id=principal_id,
        authenticated_actor=ActorRef('agent', 'agent', principal_id),
        request_id=request_id, received_at='2026-10-17T14:00:00.000000Z',
        trace_id='joint-trace-1')


def _graph(tmp_path, runtime):
    """One base holder over a real schema-17 library, as the entry builds it."""
    library = EngineeringLibrary.create(
        (tmp_path / 'joint-case.sqlite').resolve(),
        library_id='joint-case', schema_version=17)
    factory = SQLiteUoWFactory(library)
    snapshots = SQLiteSnapshotStore(library)
    controls = SQLiteMethodControl(factory, snapshots)
    blobs = SQLiteBlobStore(library)
    bindings = SimpleNamespace(factory=factory)
    permission = runtime.unit_execution_owner.permission
    scope = Scope(permission.scope.realm_id, permission.scope.project_id)
    caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
    root = tmp_path / 'materials'
    root.mkdir(exist_ok=True)
    (root / 'allowed-report.txt').write_text('reviewed path\n', encoding='utf-8')
    materials = _source_materials(factory, scope, root)
    reviewer = _reviewer_source(
        factory, blobs, controls, materials, bindings,
        scope=DomainScope(scope.realm_id, scope.project_id),
        principal_id=caller.principal_id)
    holder = {
        'factory': factory, 'access': EngineeringCommandAccess(runtime.wire.identity_authority),
        'controls': controls, 'blobs': blobs, 'materials': materials,
        'bindings': bindings, 'reviewer': reviewer, 'caller': caller,
    }
    return library, factory, blobs, holder, scope, caller, materials


def test_joint_acceptance_positive_same_graph_binder_and_hook_order(tmp_path):
    entry = _entry()
    runtime = _make_runtime(tmp_path / 'joint', defer_effect_write_guard_factory=True)
    library = None
    materials = None
    try:
        library, factory, blobs, base_holder, scope, caller, materials = _graph(
            tmp_path, runtime)
        domain_scope = DomainScope(scope.realm_id, scope.project_id)
        unit_owner = runtime.unit_execution_owner
        delivered, work_scope_calls, captured = [], [], {}

        def work_scope(context, package_ref, unit_ref, scopes):
            import contextlib
            work_scope_calls.append((package_ref, unit_ref))
            return contextlib.nullcontext()

        frozen_scope = SimpleNamespace(review_id=None, work_scope=work_scope)

        def prompt_parameters(*_args, **_kwargs):
            raise AssertionError('assembly must not resolve native prompt parameters')

        def deliver(plan, report):
            delivered.append((plan.review_id, report.submission_id))
            return {'submission_ref': {'submission_id': report.submission_id}}

        def ports_factory(actual_factory, actual_access, actual_scope):
            assert actual_factory is factory
            holder = dict(base_holder, factory=actual_factory, access=actual_access)
            assembly = entry.assemble_declared_work_case(
                runtime=runtime, holder=holder, scope=actual_scope, caller=caller,
                frozen_scope=frozen_scope, expected_selection=SELECTION,
                prompt_parameters=prompt_parameters,
                review_paths=(str(tmp_path / 'materials' / 'allowed-report.txt'),),
                deliver=deliver)
            captured['assembly'] = assembly
            return assembly.applier(EngineeringApplicationPorts(blobs=blobs))

        units_before = runtime.units.list()
        binding = EngineeringWireBinding(
            factory, runtime.wire.identity_authority, scope=scope,
            application_ports_factory=ports_factory)
        assembly = captured['assembly']
        case_ports = assembly.case_ports

        # Positive shape: the real binder bound over the same graph, and the
        # review runtime is the effect-write factory it handed off.
        assert binding.execution_dispatch.factory is factory
        assert binding.execution_dispatch.access is binding.access
        assert binding.execution_dispatch.records is unit_owner.records
        assert binding.execution_dispatch.blobs is blobs
        assert binding.service.declared_generation_ready is True
        assert binding.service._implementation_results.runnable is True
        assert unit_owner.effect_write_guard_factory is case_ports.review_runtime
        assert case_ports.review_run.__self__ is case_ports.review_runtime
        assert case_ports.review_runtime.before_review is assembly.before_review
        assert 'independently-review-report' in binding.service._work_step_capabilities()
        unit_owner.ensure_unit_creation_ready()
        assert delivered == []          # assembling never delivers a report
        assert units_before == ()

        # Ordering on a *registered* report: resolve in the same UoW, deliver it,
        # then fix the review id. The reviewer bootstrap still never starts.
        actor = ActorRef('agent', 'agent', caller.principal_id)
        submission_ref = _seed_submission(factory, domain_scope, actor)
        context = _context(scope.realm_id, scope.project_id, caller.principal_id)
        plan = SimpleNamespace(review_id='registered-review',
                               requirement=SimpleNamespace(expected_targets=SimpleNamespace(
                                   targets=(SimpleNamespace(ref=submission_ref),))))
        request = SimpleNamespace(version=1, fence=1)
        assert frozen_scope.review_id is None
        assembly.before_review(context, plan, request)
        assert delivered == [('registered-review', submission_ref.submission_id)]
        assert frozen_scope.review_id == 'registered-review'
        assert runtime.units.list() == units_before == ()
        assert work_scope_calls == []
    finally:
        if materials is not None:
            materials.close()
        if library is not None:
            library.close()
        runtime.stop()


def test_joint_acceptance_hook_refuses_without_a_registered_report(tmp_path):
    """Negative: no registered submission -> delivery refusal, no review id."""
    entry = _entry()
    runtime = _make_runtime(tmp_path / 'joint-negative', defer_effect_write_guard_factory=True)
    library = None
    materials = None
    try:
        library, factory, blobs, base_holder, scope, caller, materials = _graph(
            tmp_path, runtime)
        delivered, captured = [], {}

        def deliver(plan, report):
            delivered.append(plan.review_id)
            return {'submission_ref': {'submission_id': report.submission_id}}

        def prompt_parameters(*_args, **_kwargs):
            raise AssertionError('assembly must not resolve native prompt parameters')

        frozen_scope = SimpleNamespace(review_id=None,
                                       work_scope=lambda *a: __import__('contextlib').nullcontext())

        def ports_factory(actual_factory, actual_access, actual_scope):
            holder = dict(base_holder, factory=actual_factory, access=actual_access)
            assembly = entry.assemble_declared_work_case(
                runtime=runtime, holder=holder, scope=actual_scope, caller=caller,
                frozen_scope=frozen_scope, expected_selection=SELECTION,
                prompt_parameters=prompt_parameters,
                review_paths=(str(tmp_path / 'materials' / 'allowed-report.txt'),),
                deliver=deliver)
            captured['assembly'] = assembly
            return assembly.applier(EngineeringApplicationPorts(blobs=blobs))

        units_before = runtime.units.list()
        EngineeringWireBinding(factory, runtime.wire.identity_authority, scope=scope,
                               application_ports_factory=ports_factory)
        context = _context(scope.realm_id, scope.project_id, caller.principal_id)
        plan = SimpleNamespace(review_id='absent-review',
                               requirement=SimpleNamespace(expected_targets=SimpleNamespace(
                                   targets=(SimpleNamespace(ref=object()),))))
        with pytest.raises(entry.PreparationRefusal) as refused:
            captured['assembly'].before_review(context, plan, SimpleNamespace(version=1, fence=1))
        assert refused.value.code == entry.CASE_REPORT_DELIVERY_REFUSED
        assert delivered == [] and frozen_scope.review_id is None
        assert runtime.units.list() == units_before == ()
    finally:
        if materials is not None:
            materials.close()
        if library is not None:
            library.close()
        runtime.stop()


def test_joint_acceptance_owner_without_acp_opt_in_is_refused(tmp_path):
    """Negative: the zero-model harness owner must not be accepted as canonical."""
    from ordessa_server.composition.engineering_native_dispatch_assembly import (
        _OriginalUnitDispatchExecution,
    )
    runtime, _environment = _build_selected_runtime(tmp_path)
    try:
        assert runtime.unit_execution_owner.acp_turn_opt_in is False
        assert runtime.unit_execution_owner.effect_write_guard_factory is None
        with pytest.raises(Exception) as refused:
            _OriginalUnitDispatchExecution(
                runtime.unit_execution_owner, None, runtime.unit_execution_owner.records,
                SimpleNamespace(read_verified=lambda *a, **k: b'',
                                put_verified=lambda *a, **k: None),
                lambda *a, **k: None, None)
        assert getattr(refused.value, 'code', None) == 'DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE'
    finally:
        runtime.stop()
