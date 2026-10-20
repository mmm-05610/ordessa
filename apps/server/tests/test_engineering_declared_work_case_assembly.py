"""The declared-Work case assembly binds the original review/report owners.

Controlled peers only: no Server runtime, no Unit, no model, no database. Every
value below is an original-owner shaped object, and the assertions are about
*identity* - this assembly may not substitute an owner, invent a reviewer or
default a Profile revision.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.profiles import ProfileRevisionRef
from decision_runtime.definitions.models import PolicyRef
from decision_runtime.definitions.ports import DecisionServices, ReadContext
from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as DomainScope
from ordessa_engineering.adapters.declared_implementation_review import (
    DeclaredImplementationReviewBindings,
)
from ordessa_engineering.adapters.native_records import DeclaredUnitReviewRuntime
from ordessa_engineering.adapters.native_records.declared_reviewer import (
    DeclaredUnitReviewerSource,
)
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.orchestration.declared_implementation_results import (
    DeclaredImplementationResults,
)
from ordessa_engineering.application.usecases.changes.declared_report import (
    DeclaredWorkReportSource,
)
from ordessa_engineering.application.usecases.reviews.admission import (
    EngineeringReviewAdmission,
)
from ordessa_engineering.application.usecases.reviews.assignments import (
    ReviewerAssignmentUseCases,
)
from ordessa_server.composition.engineering_declared_work_case_assembly import (
    DeclaredWorkCasePorts,
    apply_declared_work_case_ports,
    build_declared_work_case_ports,
    verify_reviewer_before_use,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_system_access_bindings.engineering_wire import (
    EngineeringApplicationPorts, EngineeringWireBinding,
)

from .test_selected_unit_shutdown import _build_selected_runtime

SCOPE = Scope('realm-a', 'project-a')            # wire scope, used by the access owner
REVIEWER = ActorRef('source-reviewer', 'service', 'explicit-host-selection')
REVIEWER_SCOPE = DomainScope('realm-a', 'project-a')   # what DecisionReviewerSource holds
CALLER = SimpleNamespace(principal_id='principal-a')
SELECTION = (REVIEWER, ('reviewer',), 1)


class _Factory:
    """Original UoW factory shape; assembly must never begin a transaction."""

    authority_id = 'authority-a'

    def __init__(self):
        self.library = SimpleNamespace(schema_version=17)

    def begin(self, *_args, **_kwargs):
        raise AssertionError('assembly must not open a transaction')


class _Access:
    """Original access shape; no capability is checked during assembly."""

    def __init__(self, factory):
        self.factory = factory
        self.current = object()

    def current_context(self):
        return self.current

    def require(self, *_args, **_kwargs):
        raise AssertionError('assembly must not require a capability')

    @contextmanager
    def guard_current_capability(self, *_args, **_kwargs):
        raise AssertionError('assembly must not enter a capability guard')
        yield  # pragma: no cover


class _QueryFactory:
    """Original dispatch query shape is callable; assembly must not call it."""

    def __call__(self, *_args, **_kwargs):
        raise AssertionError('assembly must not query a native turn')


class _Owner:
    """Original Unit owner shape: records, profile service, fixed permission."""

    def __init__(self, factory, revision):
        self.factory = factory
        self.records = SimpleNamespace(
            resolve_unit_reference=lambda *_a, **_k: None,
            query_acp_turn=lambda *_a, **_k: None,
        )
        self.profile_service = SimpleNamespace(get_revision=lambda *_a, **_k: None)
        self.permission = SimpleNamespace(
            profile_revision=revision, scope=SCOPE, principal_scope='principal-scope-a')
        self.admission = SimpleNamespace(environment_namespace='environment-a')

    def authorization(self):
        return object()

    def authorize_acp_turn_query(self, *_args, **_kwargs):
        raise AssertionError('assembly must not query a native turn')


def _reviewer_source(factory, blobs, method_control, source_materials, source_review_bindings,
                     *, scope=REVIEWER_SCOPE, roles=('reviewer',), principal_id='principal-a',
                     reviewer=REVIEWER, trust_version=1):
    """A real DecisionReviewerSource over controlled decision ports.

    No provider call happens: the decision ports are inert peers, but the object
    is built by the real constructor so its graph identity, caller/scope and
    fixed selection are the ones the assembly must verify.
    """
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
        factory, blobs, method_control, source_materials, source_review_bindings,
        scope=scope, principal_id=principal_id, reviewer=reviewer,
        roles=roles, services=services, trust_version=trust_version)


def _revision():
    return ProfileRevisionRef(
        'environment-a', 'profile-a', 1,
        'sha256:8952563ddf0d56373feea9ca761df634d303ffa00e9157b3bc59d88726c7ae95')


def _peers(tmp_path):
    factory = _Factory()
    access = _Access(factory)
    owner = _Owner(factory, _revision())
    method_control = SimpleNamespace(
        factory=factory,
        guard=lambda *_a, **_k: None,
        resource_ref=lambda *_a, **_k: None,
        read_resource=lambda *_a, **_k: None,
    )
    blobs = SimpleNamespace(
        authority_id=factory.authority_id,
        library=factory.library,
        read_verified=lambda *_a, **_k: b'',
        put_verified=lambda *_a, **_k: None,
    )
    source_materials = SimpleNamespace(factory=factory)
    source_review_bindings = SimpleNamespace(factory=factory)
    reviewer_source = _reviewer_source(
        factory, blobs, method_control, source_materials, source_review_bindings)
    allowed = tmp_path / 'allowed-report.txt'
    allowed.write_text('reviewed path\n', encoding='utf-8')
    return {
        'factory': factory,
        'access': access,
        'wire_scope': SCOPE,
        'owner': owner,
        'method_control': method_control,
        'blobs': blobs,
        'source_materials': source_materials,
        'source_review_bindings': source_review_bindings,
        'reviewer_source': reviewer_source,
        'review_paths': (str(allowed),),
    }


def _build(peers, **overrides):
    values = dict(peers)
    values.setdefault('caller', CALLER)
    values.setdefault('expected_selection', SELECTION)
    values.update(overrides)
    return build_declared_work_case_ports(**values)


def test_case_ports_bind_the_original_review_and_report_owners(tmp_path):
    peers = _peers(tmp_path)
    ports = _build(peers)

    assert type(ports) is DeclaredWorkCasePorts
    assert type(ports.review_plan_factory) is DeclaredImplementationReviewBindings
    assert ports.review_plan_factory.factory is peers['factory']
    assert ports.review_plan_factory.expected_profile_ref is \
        peers['owner'].permission.profile_revision
    assert type(ports.review_runtime) is DeclaredUnitReviewRuntime
    assert ports.review_run.__self__ is ports.review_runtime
    assert type(ports.review_admission) is EngineeringReviewAdmission
    # The admission must use the *same* plan producer, which is also the
    # declared-submission binding port; a second object would not be checked.
    assert ports.review_admission.bindings is ports.review_plan_factory
    assert type(ports.review_admission.source) is DeclaredUnitReviewerSource
    assert ports.review_admission.source.records is peers['owner'].records
    assert type(ports.reviewer_assignments) is ReviewerAssignmentUseCases
    assert ports.reviewer_assignments.factory is peers['factory']
    assert type(ports.submission_report_source) is DeclaredWorkReportSource
    assert ports.submission_report_source.factory is peers['factory']
    assert ports.submission_report_source.methods is peers['method_control']


def test_case_ports_make_the_declared_result_steps_runnable(tmp_path):
    """`runnable` is the real gate that maps review/report/judgement steps."""
    peers = _peers(tmp_path)
    ports = _build(peers)
    results = DeclaredImplementationResults(
        peers['factory'], method_guard=peers['method_control'], blobs=peers['blobs'],
        plan_factory=ports.review_plan_factory, review_run=ports.review_run,
        review_admission=ports.review_admission, dispatch=lambda *_a: None)
    assert results.runnable is True

    # Without the runner the same composition must stay explicitly closed.
    closed = DeclaredImplementationResults(
        peers['factory'], method_guard=peers['method_control'], blobs=peers['blobs'],
        plan_factory=ports.review_plan_factory, review_run=None,
        review_admission=ports.review_admission, dispatch=lambda *_a: None)
    assert closed.runnable is False


def test_applying_ports_keeps_dispatch_and_leaves_generation_unset(tmp_path):
    peers = _peers(tmp_path)
    ports = _build(peers)

    def binder(service):  # the caller keeps the real bind_engineering_native_dispatch
        return ('binder', service)

    query_factory = _QueryFactory()
    applied = apply_declared_work_case_ports(
        EngineeringApplicationPorts(blobs=peers['blobs']), case_ports=ports,
        execution_records=peers['owner'].records,
        execution_query_factory=query_factory,
        execution_dispatch_binder=binder)
    assert applied.review_run is ports.review_run
    assert applied.review_plan_factory is ports.review_plan_factory
    assert applied.review_admission is ports.review_admission
    assert applied.reviewer_assignments is ports.reviewer_assignments
    assert applied.submission_report_source is ports.submission_report_source
    assert applied.execution_records is peers['owner'].records
    assert applied.execution_query_factory is query_factory
    assert applied.execution_dispatch_binder is binder
    assert applied.declared_generation_binder is None


def test_missing_reviewer_source_refuses_instead_of_guessing(tmp_path):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, reviewer_source=None)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE'


def test_guessed_reviewer_actor_is_refused(tmp_path):
    """An ActorRef (or a lookalike) is not the base assembly's reviewer owner."""
    peers = _peers(tmp_path)
    for stand_in in ('jev-real-source-reviewer', object(), REVIEWER,
                     SimpleNamespace(verify_response=lambda *_a, **_k: None,
                                     guard_trust=lambda *_a, **_k: None)):
        with pytest.raises(ApplicationError) as refused:
            _build(peers, reviewer_source=stand_in)
        assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE'


def test_empty_reviewer_shell_is_refused(tmp_path):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, reviewer_source=object.__new__(DecisionReviewerSource))
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE'


def test_reviewer_built_over_another_graph_is_refused(tmp_path):
    peers = _peers(tmp_path)
    other_factory = _Factory()
    other_blobs = SimpleNamespace(authority_id=other_factory.authority_id,
                                  library=other_factory.library,
                                  read_verified=lambda *_a, **_k: b'',
                                  put_verified=lambda *_a, **_k: None)
    other_control = SimpleNamespace(
        factory=other_factory, guard=lambda *_a, **_k: None,
        resource_ref=lambda *_a, **_k: None, read_resource=lambda *_a, **_k: None)
    foreign = _reviewer_source(
        other_factory, other_blobs, other_control,
        SimpleNamespace(factory=other_factory), SimpleNamespace(factory=other_factory))
    with pytest.raises(ApplicationError) as refused:
        _build(peers, reviewer_source=foreign)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_GRAPH_MISMATCH'


def test_reviewer_scope_is_reverified(tmp_path):
    peers = _peers(tmp_path)
    wrong_scope = _reviewer_source(
        peers['factory'], peers['blobs'], peers['method_control'],
        peers['source_materials'], peers['source_review_bindings'],
        scope=DomainScope('realm-a', 'other-project'))
    with pytest.raises(ApplicationError) as refused:
        _build(peers, reviewer_source=wrong_scope)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_SCOPE_MISMATCH'


def test_reviewer_must_be_the_host_callers_reviewer(tmp_path):
    peers = _peers(tmp_path)
    other_principal = _reviewer_source(
        peers['factory'], peers['blobs'], peers['method_control'],
        peers['source_materials'], peers['source_review_bindings'], principal_id='someone-else')
    with pytest.raises(ApplicationError) as refused:
        _build(peers, reviewer_source=other_principal)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_PRINCIPAL_MISMATCH'

    with pytest.raises(ApplicationError) as refused:
        _build(peers, caller=SimpleNamespace(principal_id=''))
    assert refused.value.code == 'DECLARED_WORK_CASE_CALLER_UNAVAILABLE'


@pytest.mark.parametrize('selection', [
    (ActorRef('another-reviewer', 'service', 'other'), ('reviewer',), 1),
    (REVIEWER, ('reviewer', 'approver'), 1),
    (REVIEWER, ('reviewer',), 2),
])
def test_reviewer_selection_must_be_the_handoff_selection(tmp_path, selection):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, expected_selection=selection)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_SELECTION_MISMATCH'


def _command_context(principal_id='principal-a'):
    return CommandContext(
        scope=REVIEWER_SCOPE, principal_id=principal_id,
        authenticated_actor=ActorRef('agent', 'agent', principal_id),
        request_id='req-1', received_at='2026-10-17T14:00:00.000000Z', trace_id='trace-1')


def test_reviewer_guard_accepts_the_active_owner_and_refuses_the_closed_one(tmp_path):
    """Real CommandContext, no stand-in types: active passes, closed refuses."""
    peers = _peers(tmp_path)
    reviewer = peers['reviewer_source']
    assert verify_reviewer_before_use(reviewer, _command_context()) is True

    reviewer.close()
    with pytest.raises(ApplicationError) as refused:
        verify_reviewer_before_use(reviewer, _command_context())
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_UNTRUSTED'


def test_reviewer_profile_revision_must_be_the_frozen_original(tmp_path):
    peers = _peers(tmp_path)
    peers['owner'].permission.profile_revision = {'profileId': 'guessed'}
    with pytest.raises(ApplicationError) as refused:
        _build(peers)
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEWER_PROFILE_UNAVAILABLE'


def test_scope_must_match_the_original_permission(tmp_path):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, wire_scope=SimpleNamespace(realm_id='realm-a', project_id='other'))
    assert refused.value.code == 'DECLARED_WORK_CASE_SCOPE_MISMATCH'


def test_review_paths_must_be_real_absolute_paths(tmp_path):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, review_paths=('relative/report.txt',))
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEW_PATHS_INVALID'

    link = tmp_path / 'linked-report.txt'
    real = tmp_path / 'allowed-report.txt'
    link.symlink_to(real)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, review_paths=(str(link),))
    assert refused.value.code == 'DECLARED_WORK_CASE_REVIEW_PATHS_INVALID'


def test_foreign_factory_is_refused(tmp_path):
    peers = _peers(tmp_path)
    with pytest.raises(ApplicationError) as refused:
        _build(peers, source_materials=SimpleNamespace(factory=object()))
    assert refused.value.code == 'DECLARED_WORK_CASE_SOURCE_UNAVAILABLE'


def test_owner_without_records_is_refused(tmp_path):
    peers = _peers(tmp_path)
    peers['owner'].records = None
    with pytest.raises(ApplicationError) as refused:
        _build(peers)
    assert refused.value.code == 'DECLARED_WORK_CASE_OWNER_UNAVAILABLE'


def test_real_owner_and_temp_library_accept_the_case_ports(tmp_path):
    """The operator's own seam: real LocalUnitOwner, real schema-17 library.

    This reproduces the reviewed failure (``REVIEW_SOURCE_AUTHORITY_MISMATCH``)
    against the *product* ports factory rather than a loose peer: the M1 ports
    must be accepted by ``EngineeringWireBinding`` with the real owner, and the
    resulting service must report the declared result steps as runnable.
    """
    runtime, _environment = _build_selected_runtime(tmp_path)
    try:
        library = EngineeringLibrary.create(
            (tmp_path / 'declared-work-case.sqlite').resolve(),
            library_id='declared-work-case', schema_version=17)
        try:
            factory = SQLiteUoWFactory(library)
            permission = runtime.unit_execution_owner.permission
            scope = Scope(permission.scope.realm_id, permission.scope.project_id)
            # The library and the Unit owner are real; the Method/Blob owners
            # are identity-bound peers (their internal tables are not what this
            # seam test exercises).
            controls = SimpleNamespace(
                factory=factory, guard=lambda *_a, **_k: None,
                resource_ref=lambda *_a, **_k: None,
                read_resource=lambda *_a, **_k: None)
            blobs = SimpleNamespace(
                authority_id=factory.authority_id, library=factory.library,
                read_verified=lambda *_a, **_k: b'',
                put_verified=lambda *_a, **_k: None)
            materials = SimpleNamespace(factory=factory)
            bindings = SimpleNamespace(factory=factory)
            allowed = tmp_path / 'allowed-report.txt'
            allowed.write_text('reviewed path\n', encoding='utf-8')
            reviewer = _reviewer_source(
                factory, blobs, controls, materials, bindings,
                scope=DomainScope(scope.realm_id, scope.project_id))
            # The ports must be built with the *binding's own access instance*:
            # EngineeringService refuses reviewer assignments from another one.
            def ports_factory(actual_factory, actual_access, actual_scope):
                assert actual_factory is factory
                assert type(actual_access) is EngineeringCommandAccess
                case = build_declared_work_case_ports(
                    factory=actual_factory, access=actual_access, wire_scope=actual_scope,
                    caller=CALLER, owner=runtime.unit_execution_owner,
                    method_control=controls, blobs=blobs,
                    source_materials=materials, source_review_bindings=bindings,
                    reviewer_source=reviewer, expected_selection=SELECTION,
                    review_paths=(str(allowed),))
                # A real build starts from the base ports (they carry the Blob
                # owner); M1 replaces only this case's review/report values.
                return apply_declared_work_case_ports(
                    EngineeringApplicationPorts(blobs=blobs), case_ports=case,
                    execution_records=runtime.unit_execution_owner.records,
                    execution_query_factory=_QueryFactory(),
                    execution_dispatch_binder=None)

            binding = EngineeringWireBinding(factory, runtime.wire.identity_authority,
                                             scope=scope,
                                             application_ports_factory=ports_factory)
            assert binding.service._implementation_results.runnable is True
            mapped = binding.service._work_step_capabilities()
            assert 'independently-review-report' in mapped
            assert 'resolve-one-operation-disposition' in mapped
            assert 'record-operation-result' in mapped
        finally:
            library.close()
    finally:
        runtime.stop()


def test_apply_refuses_another_graphs_records_or_blobs(tmp_path):
    peers = _peers(tmp_path)
    ports = _build(peers)

    class _QueryFactory:
        def __call__(self, *_args, **_kwargs):
            return None

    with pytest.raises(ApplicationError) as refused:
        apply_declared_work_case_ports(
            EngineeringApplicationPorts(blobs=peers['blobs']), case_ports=ports,
            execution_records=SimpleNamespace(), execution_query_factory=_QueryFactory(),
            execution_dispatch_binder=None)
    assert refused.value.code == 'DECLARED_WORK_CASE_RECORDS_GRAPH_MISMATCH'

    with pytest.raises(ApplicationError) as refused:
        apply_declared_work_case_ports(
            EngineeringApplicationPorts(blobs=SimpleNamespace(authority_id='other')),
            case_ports=ports, execution_records=peers['owner'].records,
            execution_query_factory=_QueryFactory(), execution_dispatch_binder=None)
    assert refused.value.code == 'DECLARED_WORK_CASE_BLOB_GRAPH_MISMATCH'


def test_apply_requires_typed_case_ports_and_a_dispatch_binder(tmp_path):
    peers = _peers(tmp_path)
    ports = _build(peers)
    with pytest.raises(ApplicationError):
        apply_declared_work_case_ports(
            EngineeringApplicationPorts(), case_ports=object(),
            execution_records=peers['owner'].records,
            execution_query_factory=_QueryFactory(), execution_dispatch_binder=object())
    with pytest.raises(ApplicationError) as refused:
        apply_declared_work_case_ports(
            EngineeringApplicationPorts(), case_ports=ports,
            execution_records=None, execution_query_factory=_QueryFactory(),
            execution_dispatch_binder=object())
    assert refused.value.code == 'DECLARED_WORK_CASE_DISPATCH_UNAVAILABLE'
