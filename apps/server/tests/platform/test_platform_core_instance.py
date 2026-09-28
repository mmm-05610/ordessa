"""T015/S1c platform gates: the single Pacthold seam and the core-instance topology.

Every guard here answers a row of the quickstart gate table with a REAL
composition, not a substitute:

* 「核心实例」 — "关闭 A 后 B 仍可读写": proven with TWO live
  ``build_runtime`` compositions in ONE process (a single-instance test
  cannot pass this gate — the table says so in terms), plus the unbound-owner
  counterexample (an owner that never bound cannot submit).
* 「联合注册」 — the plugin contribution round stages through the composed
  ``CoreBinding`` into the real C1 registry (A's implementation checkpoint
  ``b47b6d7803`` wired ``stage/submit/query/request_stop/reconcile/close``
  for real), so this lane's wording moves from "替身通过" to a composed pass.
* S1c topology — the composition's C1 Core owns its own file inside the data
  root (``state/core.sqlite``); the shared-file alternative is not merely
  rejected but *demonstrated unsafe* by
  ``test_shared_file_topology_counterexample_double_applies_a_write``.

The doubles are controlled services in the sense the spec allows: the
C1-protocol providers are defined HERE (the seam never depends on a business
plugin), while everything on the other side of the seam is the real
``pacthold.public`` kernel at A's merged checkpoint.
"""
from __future__ import annotations

import dataclasses
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from contribution_fakes import ContribPlugin, contribution
from pacthold.public import (
    AcquireOutcome,
    AcquireRequest,
    AcquireResult,
    ContractNotRegisteredError,
    CoreStore,
    ExecutionPlan,
    ExecutionState,
    LeaseState,
    MissingContractReferenceError,
    Observation,
    ObservationKind,
    ProviderNotRegisteredError,
    ReconcileOutcome,
    ReconcileRequest,
    ReconcileResult,
    ReconcileSupport,
    RegistrationConflictError,
    ReleaseOutcome,
    ReleaseRequest,
    ReleaseResult,
    ResourceProviderDescriptor,
    ResourceRequirement,
    RuntimeClosedError,
    StartOutcome,
    StartRequest,
    StartResult,
    StopOutcome,
    StopRequest,
    StopResult,
)
from server_plugin_api import (
    PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID,
)

from ordessa_server.bootstrap import build_runtime
from ordessa_server.core_binding import CoreBinding

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@dataclasses.dataclass(frozen=True)
class FragmentV1:
    """A controlled C1 contract (frozen dataclass + versioned id), test-side."""

    contract_id: dataclasses.ClassVar[str] = "sample.t015.fragment@1"
    text: str = ""


class ControlledResourceProvider:
    def __init__(self, provider_id: str = "res.t015", *,
                 supported: frozenset[str] | None = None) -> None:
        self.provider_id = provider_id
        self.supported_contract_ids = supported or frozenset({FragmentV1.contract_id})
        self.acquire_calls: list = []
        self.reconcile_calls: list = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id, display_name="controlled t015 resource",
            version="1.0", reconcile_support=ReconcileSupport.SUPPORTED)

    def acquire(self, request: AcquireRequest) -> AcquireResult:
        self.acquire_calls.append(request)
        lease_id = f"lease-{len(self.acquire_calls)}"
        return AcquireResult(
            outcome=AcquireOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, lease_id=lease_id,
            safe_handle=f"handle-{lease_id}", lease_state=LeaseState.ACQUIRED)

    def release(self, request: ReleaseRequest) -> ReleaseResult:
        return ReleaseResult(
            outcome=ReleaseOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, lease_id=request.lease_id)

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        self.reconcile_calls.append(request)
        return ReconcileResult(
            outcome=ReconcileOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id, resolution_ref="evidence-t015")


class ControlledExecutionProvider:
    provider_id = "exec.t015"

    def __init__(self, *, supported: frozenset[str] | None = None) -> None:
        self.supported_contract_ids = supported or frozenset({FragmentV1.contract_id})
        self.start_calls: list = []
        self.stop_calls: list = []

    def describe(self) -> ResourceProviderDescriptor:
        return ResourceProviderDescriptor(
            id=self.provider_id, display_name="controlled t015 execution",
            version="1.0", reconcile_support=ReconcileSupport.UNSUPPORTED)

    def start(self, request: StartRequest) -> StartResult:
        self.start_calls.append(request)
        return StartResult(
            outcome=StartOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id,
            run_safe_handle=f"run-{request.execution_id}")

    def observe(self, handle) -> Observation:
        return Observation(kind=ObservationKind.RUNNING, safe_handle=handle.safe_handle)

    def stop(self, request: StopRequest) -> StopResult:
        self.stop_calls.append(request)
        return StopResult(
            outcome=StopOutcome.SUCCESS, operation_key=request.operation_key,
            execution_id=request.execution_id)


def payload(*, res=None, exe=None, contracts=(FragmentV1,)):
    """A plugin-side opaque payload in exactly the shape the C2 carrier
    transports: one object with the three C1 field names. ``bind_owner``
    translates it by identity — no mirror dataclass in between."""
    return SimpleNamespace(
        contracts=contracts,
        resource_providers=(res if res is not None else ControlledResourceProvider(),),
        execution_providers=(exe if exe is not None else ControlledExecutionProvider(),),
    )


def plan_for(request_key: str, digest: str = DIGEST_A):
    return ExecutionPlan(
        request_key=request_key, digest=digest, provider_id="exec.t015",
        provider_version="1.0", work_id="work-0001",
        resources=(ResourceRequirement(
            slot="frag", contract_id=FragmentV1.contract_id, provider_id="res.t015"),))


@pytest.fixture()
def binding(tmp_path) -> CoreBinding:
    # Built exactly the way build_runtime builds it: one per composition,
    # its own file inside the data root, opened lazily.
    b = CoreBinding(tmp_path / "state" / "core.sqlite")
    yield b
    b.close()


# -- the seam itself -----------------------------------------------------------


def test_the_seam_names_no_core_internals_import():
    """Binding rule (1), checkable form: core_binding.py imports from
    pacthold.public and nowhere else inside the kernel."""
    from ordessa_server import core_binding as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("from pacthold.") or stripped.startswith("import pacthold."):
            assert ".public" in stripped, line


def test_unbound_owner_cannot_submit_counterexample(binding):
    """The quickstart demands a counterexample: an owner that never bound
    cannot submit — and it is the UNBOUND state that refuses, because the
    same plan passes the moment an owner binds."""
    snapshot_before = binding.snapshot()
    assert (snapshot_before.contract_ids, snapshot_before.resource_provider_ids,
            snapshot_before.execution_provider_ids) == ((), (), ())
    with pytest.raises(ProviderNotRegisteredError):
        binding.submit(plan_for("req-unbound"))
    binding.bind_owner("owner.t015", payload())
    result = binding.submit(plan_for("req-bound", DIGEST_B))
    assert binding.query(result.execution_id).execution_state is not None


def test_bind_owner_translates_the_plugin_payload_by_identity(binding):
    """Binding rule (2): the C2 payload object's three fields go to the C1
    constructor as-is; what lands in the registry is exactly the plugin's
    own provider objects (identity, not a re-projection)."""
    res, exe = ControlledResourceProvider(), ControlledExecutionProvider()
    registration = binding.bind_owner("owner.identity", payload(res=res, exe=exe))
    assert registration.owner == "owner.identity"
    snap = binding.snapshot()
    assert FragmentV1.contract_id in snap.contract_ids
    assert "res.t015" in snap.resource_provider_ids
    assert "exec.t015" in snap.execution_provider_ids
    result = binding.submit(plan_for("req-identity"))
    assert exe.start_calls, "dispatch did not reach the plugin's own provider"
    # FR-007 busy refusal at the seam: an owner with an unresolved lease
    # unbinds NEVER — the typed refusal is the honest answer, and a quiet
    # destroy of the run would be the gate 「卸载/恢复」 forbids.
    from pacthold.public import OwnerBusyError
    with pytest.raises(OwnerBusyError):
        binding.unbind_owner("owner.identity")
    stop = binding.request_stop(result.execution_id, result.operation_key)
    assert stop.execution_id == result.execution_id and exe.stop_calls
    # an idle owner retires cleanly:
    binding.bind_owner("owner.idle",
                       SimpleNamespace(contracts=(), resource_providers=(),
                                       execution_providers=()))
    binding.unbind_owner("owner.idle")


def test_a_raising_stage_aborts_with_zero_leaked_contributions(binding):
    """Binding rule (3): failure inherits the T012/T013 transaction — a
    rejected stage reserves nothing, leaves the snapshot unchanged and the
    loser unbound, and never blocks a later honest rebind."""
    binding.bind_owner("owner.a", payload())
    before = binding.snapshot()
    # Same contract id claimed twice: typed conflict, nothing reserved.
    with pytest.raises(RegistrationConflictError):
        binding.bind_owner("owner.b", payload())
    assert binding.snapshot() == before
    # A provider referencing a contract neither in its batch nor active.
    orphan_res = ControlledResourceProvider(
        provider_id="res.orphan", supported=frozenset({"sample.orphan@1"}))
    with pytest.raises(MissingContractReferenceError):
        binding.bind_owner("owner.c",
                           SimpleNamespace(contracts=(), resource_providers=(orphan_res,),
                                           execution_providers=()))
    assert binding.snapshot() == before
    from pacthold.public import OwnerNotRegisteredError
    with pytest.raises(OwnerNotRegisteredError):
        binding.unbind_owner("owner.b")
    # The aborted rounds leaked nothing that would block the retry: owner.b
    # can bind now (its conflicted claim was never reserved).
    binding.bind_owner("owner.b",
                       SimpleNamespace(contracts=(), resource_providers=(),
                                       execution_providers=()))


def test_close_surfaces_the_shutdown_report_and_store_facts_survive(tmp_path):
    """The close contract: ``CoreRuntime.close()`` runs first (its store
    closes inside it, last), the ShutdownReport is surfaced, an unresolved
    execution is LISTED not killed, and after the composition's next round
    the durable row — not process memory — answers."""
    b = CoreBinding(tmp_path / "state" / "core.sqlite")
    b.bind_owner("owner.close", payload())
    result = b.submit(plan_for("req-close"))
    report = b.close()
    assert b.shutdown_report is report
    assert b.close() is report  # re-close returns the same report
    with pytest.raises(RuntimeClosedError):
        b.snapshot()
    # the composition restarts its round over the SAME server-owned file:
    b.open()
    view = b.query(result.execution_id)
    assert view.execution_state is not None  # durable fact, new round's memory
    b.close()


# -- the 核心实例 gate: two live compositions, one process ----------------------


def test_two_live_compositions_close_a_b_still_reads_and_writes(tmp_path):
    """Quickstart 「核心实例」: 关闭 A 后 B 仍可读写 — with TWO real
    ``build_runtime`` compositions in ONE process (single-instance cannot
    pass this gate), each carrying its own CoreBinding over its own file."""
    runtime_a = build_runtime(tmp_path / "core-a-instance")
    runtime_b = build_runtime(tmp_path / "core-b-instance")
    runtime_a.start()
    runtime_b.start()
    try:
        a, b = runtime_a.core_binding, runtime_b.core_binding
        assert a is not b
        assert Path(a.store_path).resolve() != Path(b.store_path).resolve()
        exe_a = ControlledExecutionProvider()
        res_b = ControlledResourceProvider()
        exe_b = ControlledExecutionProvider()
        a.bind_owner("owner.a", payload(exe=exe_a))
        b.bind_owner("owner.b", payload(res=res_b, exe=exe_b))
        first_b = b.submit(plan_for("req-b-first"))
        # Stop A's round completely through the composition lifecycle.
        runtime_a.stop()
        assert runtime_a.core_shutdown_report is not None  # surfaced, not dropped
        with pytest.raises(RuntimeClosedError):
            a.snapshot()
        # B, still live, WRITES: a new submission through its own seam...
        second_b = b.submit(plan_for("req-b-after", DIGEST_B))
        # ...and READS both the pre-stop and the post-stop records.
        assert b.query(first_b.execution_id).execution_state is not None
        assert b.query(second_b.execution_id).execution_state is not None
        # and B's store kept every row while A's round came and went.
        assert Path(b.store_path).is_file()
        for res in (first_b, second_b):
            b.request_stop(res.execution_id, res.operation_key)
    finally:
        runtime_b.stop()


def test_core_binding_is_per_composition_and_crosses_the_host_wall(tmp_path):
    """The binding is handed to consumers through the existing wall, once per
    composition — never a module global two compositions could share."""
    runtime_a = build_runtime(tmp_path / "wall-a")
    runtime_b = build_runtime(tmp_path / "wall-b")
    try:
        assert runtime_a.core_binding is not runtime_b.core_binding
        # Host wall, host side: the object a declaring plugin resolves from
        # `context.ports` is the SAME instance a host-side consumer holds.
        assert runtime_a.plugin_host.host_ports["core.binding"] is runtime_a.core_binding
        assert runtime_b.plugin_host.host_ports["core.binding"] is runtime_b.core_binding
        # the fixed core seam point is bound to THIS composition's handler.
        point = runtime_a.plugin_host.contribution_points.point(
            PACTHOLD_CONTRIBUTIONS_POINT_ID)
        assert point is not None and point.handler is runtime_a.core_binding
        assert point.api_version == PACTHOLD_CONTRIBUTIONS_API_VERSION
    finally:
        runtime_a.stop()
        runtime_b.stop()


# -- the 联合注册 gate: a real plugin round into a real Core ---------------------


def test_a_plugin_contribution_round_registers_into_the_composed_core(tmp_path):
    """联合注册 proven with a real Core composition, not a substitute: the
    plugin carries a C2 Contribution whose payload is a C1 contribution
    shape; the host round stages it through the composed CoreBinding and a
    submission dispatches to the plugin's own providers."""
    res, exe = ControlledResourceProvider(), ControlledExecutionProvider()
    plugin = ContribPlugin(
        "t015.joint",
        contributions=(contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            payload(res=res, exe=exe)),),
    )
    runtime = build_runtime(tmp_path / "joint", server_plugins=(plugin,))
    runtime.start()
    try:
        snap = runtime.core_binding.snapshot()
        assert "exec.t015" in snap.execution_provider_ids
        result = runtime.core_binding.submit(plan_for("req-joint"))
        assert exe.start_calls and result.execution_id
        assert runtime.core_binding.query(result.execution_id).execution_state is not None
        # settle the run before retirement: teardown unbinds the owner
        # through the seam (committed batch -> unregister), which stays
        # busy-refused while a lease is unresolved (FR-007).
        runtime.core_binding.request_stop(result.execution_id, result.operation_key)
    finally:
        runtime.stop()
    assert runtime.core_shutdown_report is not None


def test_a_refused_contribution_round_leaves_the_composition_rebindable(tmp_path):
    """The round's zero-leak at composition scale: a plugin whose payload
    fails C1 staging aborts activation with the typed C1 error, releases the
    data root, and the SAME data root recomposes cleanly with a valid
    plugin — an aborted round squats on no id."""
    orphan = ControlledResourceProvider(supported=frozenset({"sample.orphan@1"}))
    bad = ContribPlugin(
        "t015.bad",
        contributions=(contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            SimpleNamespace(contracts=(), resource_providers=(orphan,),
                            execution_providers=())),),
    )
    root = tmp_path / "joint-abort"
    with pytest.raises(MissingContractReferenceError):
        build_runtime(root, server_plugins=(bad,))
    good = ContribPlugin(
        "t015.good",
        contributions=(contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            payload()),),
    )
    retry = build_runtime(root, server_plugins=(good,))
    retry.start()
    try:
        snap = retry.core_binding.snapshot()
        assert "res.t015" in snap.resource_provider_ids
        assert FragmentV1.contract_id in snap.contract_ids
    finally:
        retry.stop()


def test_request_stop_and_reconcile_reach_the_plugin_provider(tmp_path, binding):
    """The last two verbs of the seam, exercised for real through the
    composition-owned binding: request_stop delegates to the provider that
    started the run; reconcile resolves a lease by the provider's evidence,
    never by guessing."""
    res, exe = ControlledResourceProvider(), ControlledExecutionProvider()
    binding.bind_owner("owner.verbs", payload(res=res, exe=exe))
    result = binding.submit(plan_for("req-verbs"))
    stop = binding.request_stop(result.execution_id, result.operation_key)
    assert exe.stop_calls, "stop never reached the plugin's provider"
    assert stop.execution_id == result.execution_id
    # reconcile: the lease this run resolved cleanly needs nothing — typed
    # refusal or typed no-op; a fabricated disposition is what must NOT
    # happen. (Full unknown-lease reconciliation is pinned kernel-side at
    # A's checkpoint; here the seam's delegation is what is proven.)
    from pacthold.public import CoreError
    with pytest.raises(CoreError):
        binding.reconcile(result.execution_id, result.operation_key)


# -- S1c topology: the counterexample that decided the choice --------------------


def test_shared_file_topology_counterexample_double_applies_a_write(tmp_path):
    """The rejected S1c option, demonstrated rather than asserted away.

    If Core shared the legacy database file, the host's in-process
    ``db.write_lock`` would no longer serialise Core's second OS-level
    connection (``CoreStore``: ``sqlite3.connect(path, timeout=10.0)``,
    default journal, no injection seam). This witness scripts the
    multi-statement read-check-write the legacy chain runs under that lock,
    against a second connection on the SAME file, with a forced interleave:
    both sides count zero, both apply — a DOUBLE-APPLIED WRITE. Under the
    chosen topology (Core at its own ``state/core.sqlite``) the same script
    cannot land two writes on one logical target, because there is no second
    connection to the legacy tables at all.

    If a future edit re-points the composition's CoreBinding at
    ``runtime.database.path``, this witness plus
    ``test_stage_a_server.py::test_core_uses_the_server_owned_database_file``
    is what goes red.
    """
    from pacthold.work_core import db as legacy_db_module

    shared_file = tmp_path / "shared.sqlite"

    def shared_script() -> int:
        """Both writers guard 'apply once' under the host's process lock.
        Forced interleave: legacy counts, core counts, core commits, legacy
        re-applies from its stale zero — one logical application, two rows."""
        legacy = sqlite3.connect(str(shared_file), timeout=10.0,
                                 check_same_thread=False)
        legacy.execute("CREATE TABLE IF NOT EXISTS applied_once (who TEXT PRIMARY KEY, "
                       "n INTEGER NOT NULL CHECK (n = 1))")
        legacy.commit()
        store = CoreStore(shared_file)  # THE REJECTED CHOICE: same file, second connection
        legacy_counted = threading.Event()
        core_counted = threading.Event()
        outcome = {"rows": None}

        def legacy_side():
            with legacy_db_module.write_lock:
                n = legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
                legacy_counted.set()
                core_counted.wait(10)
                if n == 0:
                    legacy.execute("INSERT INTO applied_once VALUES ('legacy', 1)")
                    legacy.commit()

        def core_side():
            legacy_counted.wait(10)
            with store.transaction() as conn:
                n = conn.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
                if n == 0:
                    conn.execute("INSERT INTO applied_once VALUES ('core', 1)")
            core_counted.set()

        threads = [threading.Thread(target=legacy_side),
                   threading.Thread(target=core_side)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        outcome["rows"] = legacy.execute(
            "SELECT COUNT(*) FROM applied_once").fetchone()[0]
        store.close()
        legacy.close()
        return outcome["rows"]

    # The counterexample: one logical application double-applied across the
    # two OS-level connections — exactly the hazard the write_lock was
    # supposed to prevent and cannot, once the second connection exists.
    assert shared_script() == 2, (
        "the shared-file counterexample did NOT double-apply: either the "
        "interleave was lost (fix the witness; do NOT approve option (b) on "
        "this run) or sqlite serialised the guarded window on this machine")

    # Chosen topology: the same guarded script, but Core's file is NOT the
    # legacy file — a core write can never interleave a legacy read-check-
    # write because they touch different databases.
    legacy_file = tmp_path / "chosen" / "state" / "agentbox.sqlite"
    core_file = tmp_path / "chosen" / "state" / "core.sqlite"
    legacy_file.parent.mkdir(parents=True)
    assert core_file != legacy_file
    legacy = sqlite3.connect(str(legacy_file), timeout=10.0, check_same_thread=False)
    legacy.execute("CREATE TABLE IF NOT EXISTS applied_once (who TEXT PRIMARY KEY, n INTEGER)")
    legacy.commit()
    store = CoreStore(core_file)
    with store.transaction() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS core_marker (t TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO core_marker VALUES ('applied')")
    with legacy_db_module.write_lock:
        n = legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
        if n == 0:
            legacy.execute("INSERT INTO applied_once VALUES ('legacy', 1)")
            legacy.commit()
    assert legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0] == 1
    core_tables = [r[0] for r in store.query_all(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    assert "applied_once" not in core_tables  # the legacy table is not even there
    store.close()
    legacy.close()


def test_composition_core_file_is_its_own_and_never_the_legacy_file(tmp_path):
    """The chosen topology at composition scale: after a real default
    product composition has opened and used its Core round, the legacy
    product database and the C1 store are two files inside one server-owned
    data root; writing Core adds nothing to the legacy file's table set."""
    runtime = build_runtime(tmp_path / "topology")
    runtime.start()
    try:
        runtime.core_binding.bind_owner("owner.topo", payload())
        runtime.core_binding.submit(plan_for("req-topo"))
        core_file = Path(runtime.core_binding.store_path)
        assert core_file == runtime.data_root / "state" / "core.sqlite"
        assert core_file != runtime.database.path
        with sqlite3.connect(runtime.database.path) as conn:
            legacy_tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "core_execution" not in legacy_tables  # C1 rows never entered it
        with sqlite3.connect(core_file) as conn:
            core_tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"core_execution", "core_operation"} <= core_tables
    finally:
        runtime.stop()
