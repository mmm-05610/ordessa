"""Source-level identity checks for the selected original Unit graph.

These controlled tests do not create a Unit or execute an ACP/model operation.
"""
from dataclasses import replace

import pytest

from ordessa_engineering.application.api import ApplicationError
from ordessa_server.composition.engineering_native_dispatch_assembly import (
    _OriginalUnitDispatchExecution, bind_engineering_native_generation,
)
from ordessa_engineering.application.api import EngineeringService
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_units.public import AgentOwnerUnavailable, unit_services

from test_pi_execution_selection import selection_inputs


class _NotExecutedEffectGuardFactory:
    """Identity fixture only; dispatch and ACP effects are never invoked."""

    def __call__(self, *args, **kwargs):
        raise AssertionError("test must not create an effect guard")

    def guard_effect_handoff(self, *args, **kwargs):
        raise AssertionError("test must not enter an effect handoff")


class _NotExecutedBlobs:
    def read_verified(self, *args, **kwargs):
        raise AssertionError("test must not read a blob")

    def put_verified(self, *args, **kwargs):
        raise AssertionError("test must not write a blob")


def _make_runtime(base, *, acp_turn_opt_in=False, defer_effect_write_guard_factory=False,
                  configured_effect_write_guard_factory=True):
    base.mkdir(parents=True, exist_ok=True)
    selection, ports, _, _, root = selection_inputs.__wrapped__(base)
    if defer_effect_write_guard_factory:
        ports = replace(
            ports,
            acp_turn_opt_in=True,
            defer_effect_write_guard_factory=True,
        )
    elif acp_turn_opt_in and configured_effect_write_guard_factory:
        ports = replace(
            ports,
            acp_turn_opt_in=True,
            effect_write_guard_factory=_NotExecutedEffectGuardFactory(),
        )
    return build_product_runtime(root, pi_selection=selection, pi_ports=ports)


def _execution(owner, services, records, effect_factory=None):
    return _OriginalUnitDispatchExecution(
        owner,
        services,
        records,
        _NotExecutedBlobs(),
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("test must not issue an ACP query")
        ),
        effect_factory,
    )


def test_selected_runtime_uses_facade_and_original_low_level_manager(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path / "selected", acp_turn_opt_in=True)
    try:
        owner = runtime.unit_execution_owner
        context = runtime.unit_runtime.context
        services = unit_services(context)
        records = owner.records
        effect_factory = owner.effect_write_guard_factory

        assert runtime.units is owner.manager
        assert services.unit_manager is context.owner_ports.unit_manager
        assert services.unit_manager is not owner.manager
        assert records is context.owner_ports.unit_manager.records

        # The adapter reads this exact object from the original owner; callers
        # need not provide a premature factory argument.
        execution = _execution(owner, services, records)
        assert execution.owner is owner
        assert execution.services is services
        assert execution.records is records

        # The method must resolve through the selected public facade. The
        # controlled lookup refuses before native Unit access or authorization.
        requested = {}
        unit_ref = {"environmentNamespace": context.environment_namespace,
                    "unitId": "not-created-by-this-test"}

        def refuse_lookup(value):
            requested["ref"] = value
            raise LookupError("controlled missing Unit")

        monkeypatch.setattr(owner.manager, "get", refuse_lookup)
        with pytest.raises(ApplicationError, match="DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE"):
            execution._native(unit_ref)
        assert requested["ref"] is unit_ref
    finally:
        runtime.stop()


def test_dispatch_execution_rejects_a_foreign_original_low_level_manager(tmp_path):
    selected = _make_runtime(tmp_path / "selected", acp_turn_opt_in=True)
    foreign = _make_runtime(tmp_path / "foreign", acp_turn_opt_in=True)
    try:
        owner = selected.unit_execution_owner
        services = unit_services(foreign.unit_runtime.context)
        assert services.unit_manager is foreign.unit_runtime.context.owner_ports.unit_manager
        assert services.unit_manager is not owner.admission.owner_ports.unit_manager

        with pytest.raises(ApplicationError, match="DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE"):
            _execution(
                owner,
                services,
                owner.records,
                owner.effect_write_guard_factory,
            )
    finally:
        foreign.stop()
        selected.stop()


def test_factoryless_owner_is_accepted_only_while_original_finalizer_is_pending(tmp_path):
    deferred = _make_runtime(
        tmp_path / "deferred", defer_effect_write_guard_factory=True,
    )
    ordinary = _make_runtime(
        tmp_path / "ordinary", acp_turn_opt_in=True,
        configured_effect_write_guard_factory=False,
    )
    try:
        owner = deferred.unit_execution_owner
        services = unit_services(deferred.unit_runtime.context)
        records = owner.records
        assert owner.effect_write_guard_factory is None

        with pytest.raises(AgentOwnerUnavailable):
            owner.ensure_unit_creation_ready()
        execution = _execution(owner, services, records)
        assert execution.deferred_effect_write_guard_factory is True
        with pytest.raises(ApplicationError, match="DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE"):
            execution._current_effect_write_guard_factory()

        # This is a controlled identity callback: its guard method is never
        # called and it does not prove canonical Engineering construction.
        factory = _NotExecutedEffectGuardFactory()
        assert owner.bind_effect_write_guard_factory(factory) is True
        execution.finalize_effect_write_guard_factory(factory)
        assert execution._current_effect_write_guard_factory() is factory

        ordinary_owner = ordinary.unit_execution_owner
        with pytest.raises(ApplicationError, match="DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE"):
            _execution(
                ordinary_owner,
                unit_services(ordinary.unit_runtime.context),
                ordinary_owner.records,
            )
    finally:
        ordinary.stop()
        deferred.stop()


class _GenerationAccess:
    def handoff_effect_write(self, *args, **kwargs):
        raise AssertionError("binding must not enter an effect handoff")

    def consume_effect_write(self, *args, **kwargs):
        raise AssertionError("binding must not consume an effect write")


class _GenerationBlobs:
    authority_id = "generation-test-authority"

    def read_verified(self, *args, **kwargs):
        raise AssertionError("binding must not read a blob")

    def put_verified(self, *args, **kwargs):
        raise AssertionError("binding must not write a blob")


def _generation_service(*, attach=True):
    service = object.__new__(EngineeringService)
    service._factory = type("Factory", (), {"authority_id": _GenerationBlobs.authority_id})()
    service._access = _GenerationAccess()
    service._source_materials = type("SourceMaterials", (), {
        "factory": service._factory,
        "read": lambda *args, **kwargs: b"source",
    })()
    service._review_admission = type("ReviewAdmission", (), {
        "guard_plan": lambda *args, **kwargs: None,
        "guard_trust": lambda *args, **kwargs: None,
    })()
    service._method_guard = object()
    if not attach:
        service.attach_declared_generation_handles = lambda **_kwargs: None
    return service


def test_declared_generation_binds_original_unit_transport_without_method_run_owner(tmp_path):
    runtime = _make_runtime(
        tmp_path / "generation", defer_effect_write_guard_factory=True,
    )
    try:
        owner = runtime.unit_execution_owner
        context = runtime.unit_runtime.context
        services = unit_services(context)
        blobs = _GenerationBlobs()
        service = _generation_service()
        declared = bind_engineering_native_generation(
            service, runtime, services=services, records=owner.records,
            blobs=blobs, query_factory=lambda *args, **kwargs: None,
        )
        assert declared is service.declared_generation_dispatch
        assert service.declared_generation_ready is True
        assert declared.execution.records is owner.records
        assert declared.blobs is blobs
        assert runtime.unit_execution_owner.effect_write_guard_factory is not None
        assert getattr(service, "_execution_dispatch", None) is None
    finally:
        runtime.stop()


def test_declared_generation_refuses_when_service_did_not_retain_generation_owner(tmp_path):
    runtime = _make_runtime(
        tmp_path / "generation-missing-owner", defer_effect_write_guard_factory=True,
    )
    try:
        owner = runtime.unit_execution_owner
        context = runtime.unit_runtime.context
        service = _generation_service(attach=False)
        with pytest.raises(ApplicationError, match="WORK_ACTION_GENERATION_OWNER_UNAVAILABLE"):
            bind_engineering_native_generation(
                service, runtime, services=unit_services(context), records=owner.records,
                blobs=_GenerationBlobs(), query_factory=lambda *args, **kwargs: None,
            )
        assert service.declared_generation_ready is False
        assert owner.effect_write_guard_factory is None
    finally:
        runtime.stop()


# These two cases exercise the composition cut with the original SQLite journal.
# The labelled Unit stand-in counts creates; it starts no process or ACP peer.
def _bootstrap_resolver_fixture(tmp_path, *, refuse_start=False):
    import sqlite3
    from contextlib import contextmanager
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.dispatch_identity import UNIT_BOOTSTRAP_OPERATION
    from ordessa_engineering.application.contracts.work_context import WorkBinding
    from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import DeclaredGenerationDispatch
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_agents.profiles import ProfileRevisionRef
    from ordessa_server.composition.engineering_native_dispatch_assembly import _generation_unit_resolver

    scope = Scope('resolver-bootstrap-realm', 'resolver-bootstrap-project')
    path = (tmp_path / 'bootstrap.sqlite').resolve()
    library = EngineeringLibrary.create(path, library_id='resolver-bootstrap', schema_version=17)
    profile = ProfileRevisionRef(scope.realm_id, 'profile', 1, 'sha256:' + 'a' * 64)
    permission = SimpleNamespace(profile_revision=profile, identity='sha256:' + 'b' * 64)
    unit_ref = {'environmentNamespace': scope.realm_id, 'unitId': 'controlled-unit',
                'ownerProviderRef': {'providerId': 'controlled'}, 'sourceRevision': '1'}
    unit = SimpleNamespace(identity=unit_ref, snapshot=lambda: {'state': 'confirmed'})
    creates = []

    class Access:
        def require(self, context, operation):
            assert context.scope == scope and operation == 'engineering.executions.dispatch'

        @contextmanager
        def guard_unit_bootstrap(self, context, *, permission):
            self.require(context, 'engineering.executions.dispatch')
            yield permission

    class Manager:
        def create(self, spec, authorization):
            # A different connection must already see the durable fence before
            # the composition enters even this stand-in for the native effect.
            with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as reader:
                assert reader.execute('SELECT state FROM eng_commands WHERE operation=?',
                                      (UNIT_BOOTSTRAP_OPERATION,)).fetchall() == [('pending',)]
            creates.append(spec)
            if refuse_start:
                raise RuntimeError('controlled unresolved Unit start')
            return unit

        def get(self, ref):
            assert ref == unit_ref
            return unit

    owner = SimpleNamespace(permission=permission,
        profile_service=SimpleNamespace(get=lambda _id: SimpleNamespace(archived_at=None),
                                        get_revision=lambda _ref: SimpleNamespace(ref=profile)),
        manager=Manager(), spec=object(), authorization=lambda: object())
    blobs, execution = object(), object()
    dispatch = DeclaredGenerationDispatch(SQLiteUoWFactory(library), Access(),
        blobs=blobs, execution=execution, review_admission=None, method_guard=None)
    service = SimpleNamespace(declared_generation_dispatch=dispatch)
    resolve = _generation_unit_resolver(owner, service, execution, blobs)
    binding = WorkBinding('resolver-work', scope,
        MethodRef('method', '2.7.2', 2, Digest('sha256', 'c' * 64)), 1)
    context = CommandContext(scope, 'principal', ActorRef('principal', 'service', 'controlled'),
                             'first-dispatch', '2026-10-15T10:00:00.000000Z', 'trace')
    return SimpleNamespace(library=library, path=path, dispatch=dispatch, creates=creates,
                           resolve=resolve, context=context, binding=binding, profile=profile)


def test_bootstrap_start_failure_is_fenced_before_create_across_request_and_reopen(tmp_path):
    from dataclasses import replace
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    case = _bootstrap_resolver_fixture(tmp_path, refuse_start=True)
    try:
        with pytest.raises(ApplicationError, match='WORK_ACTION_GENERATION_UNIT_UNAVAILABLE'):
            case.resolve(case.context, case.binding, case.profile)
        with pytest.raises(ApplicationError, match='WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED'):
            case.resolve(replace(case.context, request_id='other-dispatch'), case.binding, case.profile)
        assert len(case.creates) == 1
        case.library.close()
        case.library = EngineeringLibrary.open(case.path, library_id='resolver-bootstrap')
        case.dispatch.factory = SQLiteUoWFactory(case.library)
        with pytest.raises(ApplicationError, match='WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED'):
            case.resolve(replace(case.context, request_id='cold-dispatch'), case.binding, case.profile)
        assert len(case.creates) == 1
    finally:
        case.library.close()


def test_bootstrap_completion_reuses_the_original_unit_without_creating_again(tmp_path):
    case = _bootstrap_resolver_fixture(tmp_path)
    try:
        first = case.resolve(case.context, case.binding, case.profile)
        assert case.resolve(case.context, case.binding, case.profile) == first
        assert len(case.creates) == 1
    finally:
        case.library.close()


# A declared Work step already recorded under the explicit historical folded key
# (its row written before the key fix) must resolve to its own original Unit
# without a second reserve, a second Unit or a re-send. Two candidate rows are a
# named ambiguity, and a schema below 17 must fail closed rather than create a
# Unit. Every historical row here is planted at the SQL layer with its own
# original bytes: the new `reserve` correctly refuses a historical key, so using
# it would hide the very read path under test.
_GENERATION_ACTION = "incremental.prepare-packages"
_GENERATION_STEP = "draft"


def _historical_generation_binding(scope, work_id, dispatch_key, unit_ref):
    """A schema-2 generation binding naming one declared Work step and its Unit.

    Its bytes are the *original* record under `dispatch_key`: a fresh `reserve`
    refuses a historical folded key on purpose, so the row is planted with these
    exact bytes instead of being minted through the write path.
    """
    from dataclasses import asdict
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.changes.dispatch import DispatchBinding
    from ordessa_engineering.domain.changes.refs import ProposalRef
    from ordessa_engineering.domain.common.models.refs import BlobRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.refs import ReviewRef
    from ordessa_infrastructure.encoding import canonical_bytes

    subject_ref = {
        "review_ref": asdict(ReviewRef(scope.realm_id, scope.project_id, "review-1",
                                       Digest("sha256", "d" * 64))),
        "change_ref": asdict(ProposalRef(scope.realm_id, scope.project_id, "change-1",
                                         "proposal-1", Digest("sha256", "f" * 64))),
        "method_ref": asdict(MethodRef("ordessa.incremental-engineering", "2.7.2", 1,
                                       Digest("sha256", "b" * 64))),
        "inputs_digest": asdict(Digest("sha256", "e" * 64)),
    }
    return DispatchBinding(
        scope, dispatch_key, _GENERATION_STEP, 1, 1, None, None, None, None,
        (("generate_package", "instance-1"),), canonical_bytes(unit_ref), "operation-1",
        BlobRef(Digest("sha256", "c" * 64), 10, "application/json", "prompt-object"),
        Digest("sha256", "d" * 64), "q" * 64, ("submission",),
        binding_version=2,
        work={"work_id": work_id, "action_id": _GENERATION_ACTION,
              "step_id": _GENERATION_STEP, "dispatch_key": dispatch_key},
        subject={"subject_kind": "reviewed_change", "subject_ref": subject_ref})


def _seed_work_dispatch_row(repository, *, dispatch_key, step_id, attempt,
                            binding_bytes, operation_ref, completed=True):
    """Plant one declared-Work row exactly as the pre-fix writer left it.

    The row is inserted with its own original bytes; nothing re-encodes or
    re-derives the binding and no `reserve` is used (which would refuse a
    historical key). When `completed` the phase is advanced through the
    relation's own CAS so the attempt reads back the way the resolver reads it.
    """
    import hashlib
    from dataclasses import asdict
    from ordessa_infrastructure.encoding import canonical_bytes

    scope = repository.access.scope
    digest_hex = hashlib.sha256(binding_bytes).hexdigest()
    scope_json = canonical_bytes(asdict(scope)).decode("utf-8")
    marker = canonical_bytes({"dispatch": "reserved", "binding_digest": digest_hex,
                              "operation_ref": operation_ref}).decode("utf-8")
    repository.access.execute(
        "INSERT INTO work_step_log (dispatch_key,ordinal,step_id,operation,attempt,status,"
        "receipt_ref_json,dispatch_scope_json,binding_digest,binding_bytes,"
        "execution_operation_ref,dispatch_phase,dispatch_version,dispatch_fence,"
        "result_blob_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (dispatch_key, 0, step_id, "engineering.execution.dispatch", attempt, "reserved",
         marker, scope_json, digest_hex, binding_bytes, operation_ref, "reserved", 0, 1, None))
    if completed:
        repository.transition(dispatch_key, step_id, attempt, scope,
                              expected_version=0, fence=1, phase="possibly_written")
        repository.transition(dispatch_key, step_id, attempt, scope,
                              expected_version=1, fence=1, phase="completed")


def _seeded_work_dispatch_fixture(tmp_path, *, schema_version=None, work_id=None):
    """The resolver fixture whose declared-Work rows are seeded at the SQL layer.

    The labelled Unit stand-in counts creates (its start is the file's own effect
    witness) and the original command journal witnesses any bootstrap reserve.
    """
    from contextlib import contextmanager
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.dispatch_schema import (
        WORK_DISPATCH_SCHEMA_VERSION)
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import (
        EngineeringLibrary)
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.dispatch_identity import (
        UNIT_BOOTSTRAP_OPERATION, unit_bootstrap_operation_id)
    from ordessa_engineering.application.contracts.work_context import WorkBinding
    from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
        DeclaredGenerationDispatch)
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_agents.profiles import ProfileRevisionRef
    from ordessa_server.composition.engineering_native_dispatch_assembly import (
        _generation_unit_resolver)

    version = WORK_DISPATCH_SCHEMA_VERSION if schema_version is None else schema_version
    work_id = ("w" * 480) if work_id is None else work_id
    scope = Scope("resolver-historical-realm", "resolver-historical-project")
    path = (tmp_path / "seeded.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id="resolver-historical",
                                        schema_version=version)
    profile = ProfileRevisionRef(scope.realm_id, "profile", 1, "sha256:" + "a" * 64)
    permission = SimpleNamespace(profile_revision=profile, identity="sha256:" + "b" * 64)
    unit_ref = {"environmentNamespace": scope.realm_id, "unitId": "seeded-unit",
                "ownerProviderRef": {"providerId": "controlled"}, "sourceRevision": "1"}
    creates = []

    class Access:
        def require(self, context, operation):
            assert context.scope == scope and operation == "engineering.executions.dispatch"

        @contextmanager
        def guard_unit_bootstrap(self, context, *, permission):
            self.require(context, "engineering.executions.dispatch")
            yield permission

    class Manager:
        def __init__(self):
            self.unit = SimpleNamespace(identity=unit_ref,
                                        snapshot=lambda: {"state": "confirmed"})

        def create(self, spec, authorization):
            creates.append(spec)
            return self.unit

        def get(self, ref):
            return self.unit

    owner = SimpleNamespace(permission=permission,
        profile_service=SimpleNamespace(get=lambda _id: SimpleNamespace(archived_at=None),
                                        get_revision=lambda _ref: SimpleNamespace(ref=profile)),
        manager=Manager(), spec=object(), authorization=lambda: object())
    blobs, execution = object(), object()
    dispatch = DeclaredGenerationDispatch(SQLiteUoWFactory(library), Access(),
        blobs=blobs, execution=execution, review_admission=None, method_guard=None)
    service = SimpleNamespace(declared_generation_dispatch=dispatch)
    resolve = _generation_unit_resolver(owner, service, execution, blobs)
    binding = WorkBinding(work_id, scope,
        MethodRef("method", "2.7.2", 2, Digest("sha256", "c" * 64)), 1)
    context = CommandContext(scope, "principal", ActorRef("principal", "service", "controlled"),
                             "seeded-dispatch", "2026-10-15T10:00:00.000000Z", "trace")

    def seed(rows):
        with SQLiteUoWFactory(library).begin(scope) as uow:
            for row in rows:
                _seed_work_dispatch_row(uow.work_dispatch, **row)
            uow.commit()

    def bootstrap_reservation():
        with SQLiteUoWFactory(library).begin(scope, "read") as uow:
            return uow.commands.find_operation(
                scope, unit_bootstrap_operation_id(scope, work_id),
                operation=UNIT_BOOTSTRAP_OPERATION)

    def stored_row(dispatch_key):
        with SQLiteUoWFactory(library).begin(scope, "read") as uow:
            return uow.work_dispatch.get(dispatch_key, _GENERATION_STEP, 1, scope)

    def dispatch_rows():
        """How many declared-Work dispatch rows exist: a second reserve would add one."""
        with SQLiteUoWFactory(library).begin(scope, "read") as uow:
            return uow.work_dispatch.access.execute(
                "SELECT COUNT(*) FROM work_step_log").fetchone()[0]

    return SimpleNamespace(library=library, path=path, scope=scope, work_id=work_id,
                           unit_ref=unit_ref, creates=creates, resolve=resolve,
                           context=context, binding=binding, profile=profile,
                           seed=seed, bootstrap_reservation=bootstrap_reservation,
                           stored_row=stored_row, dispatch_rows=dispatch_rows)


def test_historical_folded_key_row_resolves_without_second_reserve_or_unit(tmp_path):
    from ordessa_engineering.application.contracts.dispatch_identity import (
        work_dispatch_key_candidates)
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch

    case = _seeded_work_dispatch_fixture(tmp_path)
    try:
        current, historical = work_dispatch_key_candidates(
            case.work_id, _GENERATION_ACTION, _GENERATION_STEP)
        assert historical != current
        raw = encode_dispatch(_historical_generation_binding(
            case.scope, case.work_id, historical, case.unit_ref))
        case.seed([{"dispatch_key": historical, "step_id": _GENERATION_STEP, "attempt": 1,
                    "binding_bytes": raw, "operation_ref": "historical-operation-1"}])

        assert case.resolve(case.context, case.binding, case.profile) == case.unit_ref

        # The original row keeps its own key and its own bytes: nothing was re-minted.
        stored = case.stored_row(historical)
        assert stored["run_id"] == historical
        assert stored["binding_bytes"] == raw
        # No second reserve, no Unit, no native effect: the file's own witnesses.
        assert case.bootstrap_reservation() is None
        assert case.creates == []
        assert case.dispatch_rows() == 1
    finally:
        case.library.close()


def test_current_and_historical_rows_together_require_named_reconciliation(tmp_path):
    from ordessa_engineering.application.contracts.dispatch_identity import (
        work_dispatch_key_candidates)
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch

    case = _seeded_work_dispatch_fixture(tmp_path)
    try:
        current, historical = work_dispatch_key_candidates(
            case.work_id, _GENERATION_ACTION, _GENERATION_STEP)
        case.seed([
            {"dispatch_key": historical, "step_id": _GENERATION_STEP, "attempt": 1,
             "operation_ref": "historical-operation-2",
             "binding_bytes": encode_dispatch(_historical_generation_binding(
                 case.scope, case.work_id, historical, case.unit_ref))},
            {"dispatch_key": current, "step_id": _GENERATION_STEP, "attempt": 1,
             "operation_ref": "current-operation-2",
             "binding_bytes": encode_dispatch(_historical_generation_binding(
                 case.scope, case.work_id, current, case.unit_ref))},
        ])

        with pytest.raises(ApplicationError,
                           match="WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED"):
            case.resolve(case.context, case.binding, case.profile)

        # A named refusal, not a guessed row and not a fresh Unit.
        assert case.bootstrap_reservation() is None
        assert case.creates == []
        assert case.dispatch_rows() == 2
    finally:
        case.library.close()


def test_schema_below_17_fails_closed_without_creating_a_unit(tmp_path):
    case = _seeded_work_dispatch_fixture(tmp_path, schema_version=16)
    try:
        with pytest.raises(ApplicationError, match="WORK_DISPATCH_SCHEMA_REQUIRED"):
            case.resolve(case.context, case.binding, case.profile)
        # The closed path must never fall through to a new Unit.
        assert case.creates == []
    finally:
        case.library.close()


@pytest.fixture
def implementation_selection():
    """Typed Work/Grant bounds with labelled live-owner stand-ins; no Unit starts."""
    from types import SimpleNamespace
    from ordessa_engineering.application.contracts.commands import CommandContext
    from ordessa_engineering.application.contracts.work_context import WorkBinding
    from ordessa_engineering.domain.approvals.implementation import ActionBudgetSlot, WorkPackageAuthorization
    from ordessa_engineering.domain.approvals.scope import ActionScope, EnvironmentRef
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.identity import ActorRef, Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
    from ordessa_agents.profiles import ProfileRevisionRef, encode_revision_ref
    from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
    from ordessa_server.composition.engineering_native_dispatch_assembly import _implementation_unit_resolver

    scope = Scope('selection-environment', 'selection-project')
    profile = ProfileRevisionRef(scope.realm_id, 'profile', 1, 'sha256:' + 'a' * 64)
    environment = EnvironmentRef(scope.realm_id, profile.profile_id, Digest('sha256', 'a' * 64))
    method = MethodRef('method', '2.7.2', 1, Digest('sha256', 'b' * 64))
    work = WorkBinding('implementation-work', scope, method, 1)
    bounds = ActionScope(scope.project_id, (), (environment,), (), (), 'intent')
    grant_subject = WorkPackageAuthorization(scope, 'intent', work.work_id, 1,
        Digest('sha256', 'c' * 64), 'incremental.implement-package', 'implement',
        ImplementationPackageRef(scope.realm_id, scope.project_id, 'package', Digest('sha256', 'd' * 64)),
        method, ('run_checks',), (('run_checks', bounds),), (ActionBudgetSlot('run_checks', 1),),
        'Controlled selector fixture, no human grant.',
        '2026-10-16T00:00:00.000000Z', '2026-10-17T00:00:00.000000Z')
    context = CommandContext(scope, 'principal', ActorRef('principal', 'service', 'controlled'),
        'selection', '2026-10-16T12:00:00.000000Z', 'selection')
    unit_ref = {'environmentNamespace': scope.realm_id, 'unitId': 'existing',
        'ownerProviderRef': {'providerId': 'controlled'}, 'sourceRevision': '1'}
    state = {'identity': unit_ref, 'state': 'confirmed', 'definition': {
        'agentId': 'selected-agent', 'profileRevision': encode_revision_ref(profile),
        'environmentReference': {'environmentId': 'selected-environment'}}}
    unit = SimpleNamespace(identity=unit_ref, snapshot=lambda: sealed_mapping(state))
    calls = []
    candidates = [unit]
    current_profile = SimpleNamespace(archived_at=None)

    class Manager:
        def list(self):
            calls.append('list')
            return tuple(candidates)

        def get(self, ref):
            calls.append('get')
            assert ref == unit_ref
            return unit

        def create(self, *args):
            pytest.fail('implementation selection must never create/start a Unit')

    class Access:
        def require(self, actual_context, operation):
            assert actual_context is context and operation == 'engineering.executions.dispatch'
            calls.append('access')

    authorization = object()
    def native_unit(selected, selected_authorization):
        assert selected is unit and selected_authorization is authorization
        calls.append('original-permission')
        return object()

    owner = SimpleNamespace(permission=SimpleNamespace(scope=scope, profile_revision=profile,
        agent_id='selected-agent', environment_identity='selected-environment'), manager=Manager(),
        profile_service=SimpleNamespace(get=lambda _id: current_profile,
            get_revision=lambda _ref: SimpleNamespace(ref=profile)),
        authorization=lambda: authorization, native_unit=native_unit)
    return SimpleNamespace(resolve=_implementation_unit_resolver(owner, Access()), context=context,
        work=work, profile=profile, grant_subject=grant_subject, owner=owner, unit=unit,
        state=state, candidates=candidates, current_profile=current_profile, calls=calls)


def test_implementation_selector_reuses_original_public_manager_and_permission(implementation_selection):
    case = implementation_selection
    assert case.resolve(case.context, case.work, case.profile, case.grant_subject) == case.unit.identity
    assert case.calls == ['access', 'list', 'get', 'original-permission']


def test_implementation_selector_accepts_sealed_exact_profile_ref(implementation_selection):
    from ordessa_agents.profiles import encode_revision_ref
    from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
    case = implementation_selection
    assert case.resolve(case.context, case.work, sealed_mapping(encode_revision_ref(case.profile)),
                        case.grant_subject) == case.unit.identity


@pytest.mark.parametrize('refusal', ['foreign-revision', 'extra-field', 'foreign-work'])
def test_implementation_selector_rejects_substituted_input_before_inventory(implementation_selection, refusal):
    from ordessa_agents.profiles import encode_revision_ref
    case = implementation_selection
    profile, work = encode_revision_ref(case.profile), case.work
    expected = 'WORK_ACTION_IMPLEMENTATION_PROFILE_UNAVAILABLE'
    if refusal == 'foreign-revision':
        profile['manifestRevision'] += 1
    elif refusal == 'extra-field':
        profile['caller_permission'] = True
    else:
        work = replace(work, work_id='foreign-work')
        expected = 'WORK_ACTION_IMPLEMENTATION_UNIT_BINDING_INVALID'
    with pytest.raises(ApplicationError, match=expected):
        case.resolve(case.context, work, profile, case.grant_subject)
    assert case.calls == ['access']


@pytest.mark.parametrize('refusal', ['absent', 'ambiguous', 'stopped', 'agent', 'environment',
                                  'profile', 'archived', 'scope', 'permission', 'changed-handle'])
def test_implementation_selector_refuses_without_creating_or_substituting(implementation_selection, refusal):
    from ordessa_agents.profiles import encode_revision_ref
    case = implementation_selection
    subject = case.grant_subject
    expected = 'WORK_ACTION_IMPLEMENTATION_UNIT_UNAVAILABLE'
    if refusal == 'absent':
        case.candidates.clear()
    elif refusal == 'ambiguous':
        case.candidates.append(case.unit)
        expected = 'WORK_ACTION_IMPLEMENTATION_UNIT_AMBIGUOUS'
    elif refusal == 'stopped':
        case.state['state'] = 'stopped'
    elif refusal == 'agent':
        case.state['definition']['agentId'] = 'foreign-agent'
    elif refusal == 'environment':
        case.state['definition']['environmentReference'] = {'environmentId': 'foreign-environment'}
    elif refusal == 'profile':
        case.state['definition']['profileRevision'] = encode_revision_ref(replace(case.profile, revision=2))
    elif refusal == 'archived':
        case.current_profile.archived_at = '2026-10-16T11:00:00.000000Z'
        expected = 'WORK_ACTION_IMPLEMENTATION_PROFILE_UNAVAILABLE'
    elif refusal == 'scope':
        action, bounds = subject.scope_by_action[0]
        subject = replace(subject, scope_by_action=((action, replace(bounds, environment_refs=())),))
        expected = 'ACTION_SCOPE_NOT_AUTHORIZED'
    elif refusal == 'permission':
        def refuse(*args):
            raise RuntimeError('controlled original permission revocation')
        case.owner.native_unit = refuse
    elif refusal == 'changed-handle':
        case.owner.manager.get = lambda ref: object()
    with pytest.raises(ApplicationError, match=expected):
        case.resolve(case.context, case.work, case.profile, subject)
    if refusal != 'permission':
        assert 'original-permission' not in case.calls


def test_native_dispatch_composition_attaches_existing_unit_resolver(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ordessa_server.composition import engineering_native_dispatch_assembly as assembly
    runtime = _make_runtime(tmp_path / 'implementation-binding', acp_turn_opt_in=True)
    try:
        owner = runtime.unit_execution_owner
        service = _generation_service()
        selection = SimpleNamespace(work_scope_ready=False)
        captured = {}
        # Identity-only binder spy; no approval/dispatch success is claimed.
        def bind(actual_service, **kwargs):
            assert actual_service is service
            captured.update(kwargs)
            return SimpleNamespace(unit_ref_resolver=kwargs['unit_ref_resolver'])
        monkeypatch.setattr(assembly, 'bind_execution_dispatch', bind)
        monkeypatch.setattr(owner.manager, 'create', lambda *args: pytest.fail('binding must not create Unit'))
        canonical = assembly.bind_engineering_native_dispatch(service, runtime,
            services=unit_services(runtime.unit_runtime.context), records=owner.records,
            blobs=_GenerationBlobs(), query_factory=lambda *args: None, selection=selection,
            source_snapshots=None, history_sources=None)
        assert callable(canonical.unit_ref_resolver)
        assert captured['selection'] is selection
        assert selection.work_scope_ready is False
        assert owner.manager.list() == ()
    finally:
        runtime.stop()


def test_failure_diagnostic_does_not_require_a_live_effect_factory(tmp_path, monkeypatch):
    """Bounded failure facts must survive an unavailable owner factory.

    The extractor is a pure function over the recorded binding and the
    exception; reading it may not construct another live execution, and the
    access/blob path that persists UNKNOWN is untouched here (nothing is
    written).
    """
    from ordessa_engineering.adapters.native_records import recorded_dispatch
    from ordessa_engineering.domain.common.models.identity import Scope

    runtime = _make_runtime(tmp_path / "diagnostic", acp_turn_opt_in=True)
    try:
        owner = runtime.unit_execution_owner
        context = runtime.unit_runtime.context
        services = unit_services(context)
        records = owner.records
        execution = _execution(owner, services, records)
        scope = Scope("diagnostic-realm", "diagnostic-project")
        unit_ref = {"environmentNamespace": scope.realm_id, "unitId": "diagnostic-unit",
                    "ownerProviderRef": {"provider": "controlled-test-only"},
                    "sourceRevision": "1"}
        from ordessa_engineering.application.contracts.dispatch_identity import (
            work_dispatch_key)
        dispatch_key = work_dispatch_key("diagnostic-work", _GENERATION_ACTION,
                                         _GENERATION_STEP)
        binding = _historical_generation_binding(scope, "diagnostic-work",
                                                 dispatch_key, unit_ref)

        captured = []
        extract = recorded_dispatch.failure_diagnostic

        def spy(binding, error, stage):
            captured.append((binding, error, stage))
            return extract(binding, error, stage)

        monkeypatch.setattr(recorded_dispatch, "failure_diagnostic", spy)
        primary = OSError("private-test-exception-text")
        with monkeypatch.context() as patch:
            # The original owner no longer serves the factory this execution was
            # bound with: the old delegation constructed a fresh execution here
            # and raised DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE, discarding
            # the evidence the exception already carried.
            patch.setattr(type(owner), "effect_write_guard_factory",
                          property(lambda self: None))
            with pytest.raises(ApplicationError,
                               match="DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE"):
                execution._current_effect_write_guard_factory()

            diagnostic = execution.failure_diagnostic(binding, primary, "native_send")
        assert captured == [(binding, primary, "native_send")]
        data = diagnostic.to_dict()
        assert data["stage"] == "native_send"
        assert data["native_write"] is None
        assert data["recording_failure"] is None
        assert data["exception_chain"][0]["type"] == "builtins.OSError"
        assert "private-test-exception-text" not in diagnostic.encoded.decode()
    finally:
        runtime.stop()


def test_continuation_resolver_refuses_before_any_unit_creation():
    """Order guards: unclaimed/mismatched/duplicate reservations never create."""
    from types import SimpleNamespace
    from ordessa_server.composition.engineering_native_dispatch_assembly import (
        _continuation_unit_resolver,
    )
    from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
        ContinuationCandidate, continuation_operation_id,
    )

    class _Owner:
        permission = SimpleNamespace(profile_revision=None, identity=None)

    class _Access:
        def guard_unit_bootstrap(self, *_a, **_k):
            raise AssertionError('bootstrap must not be entered')

    cells = {'owner': SimpleNamespace(), 'access': _Access()}
    resolver = _continuation_unit_resolver(_Owner(), cells)
    with pytest.raises(ApplicationError) as refused:
        resolver(SimpleNamespace(request_id='r', scope=None), object(), {})
    assert refused.value.code == 'CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE'
