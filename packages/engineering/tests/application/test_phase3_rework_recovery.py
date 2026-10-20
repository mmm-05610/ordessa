"""Reopen the original MethodRun row against the exact frozen 2.6 candidate.

These are controlled SQLite recovery fixtures. They prove persisted round and
method identity survive reopening, cancellation requests use the original
MethodRun journal, and unknown native outcomes remain unconsumed. They do not
claim a complete 2.6 review operation chain or an external Unit stop.
"""
from dataclasses import asdict
from dataclasses import replace as dataclass_replace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from ordessa_engineering.application.orchestration.method_runs import (
    MethodRunBindings, MethodRunOrchestrator,
)
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.methods.compilation.encoding import program_plan_digest
from test_review_usecases import _context
from test_work_request_round_guard_phase1 import _freeze_candidate
from test_persisted_method_work import persisted_source
from test_method_work import (
    adopt_workflow_variant, call, env, query,
)


def _persist_rework_run(e, method_ref, snapshot, *, rounds):
    run_id = "phase3-rework-recovery-run"
    marker = {
        "work_contract": WORK_CONTRACT,
        "scope": asdict(e["input_revision"].scope),
        "method_ref": asdict(method_ref),
        "compiled_plan_digest": program_plan_digest(snapshot.program),
    }
    node_index = next(index for index, node in enumerate(snapshot.program.workflow.steps)
                      if node.id == "record_rework_review")
    context = _context(e["input_revision"].scope, "phase3-persist-rework-run")
    with e["factory"].begin(context.scope) as uow:
        material_ref = uow.workflow.write_material(
            kind="method", stable_id=run_id, revision=1, body=marker, generated=False)
        uow.workflow.insert_run(
            run_id=run_id,
            method_ref=material_ref,
            registry_ref={"fixture": "candidate-2.6.0"},
            inputs={**marker, "slots": {}, "rounds": {"implementation-rework": rounds}},
            now=context.received_at,
        )
        uow.workflow.update_run(
            run_id=run_id, status="RUNNING", cursor=node_index,
            wait_reason=None, now=context.received_at)
        uow.commit()
    return run_id, context


def _cancel_workflow(*, declared=True):
    workflow = {
        "schema_version": 1,
        "workflow_id": "phase3-cancellation-contract",
        "entry": "await_fixture_condition",
        "resume_contract": WORK_CONTRACT,
        "context_slots": ["kind", "initial", "artifact_ref"],
        "wait_kinds": ["owner_reconciliation"],
        "stop_outcomes": ["accepted", "cancelled"] if declared else ["accepted"],
        "steps": [
            {"id": "await_fixture_condition", "kind": "wait",
             "event": "engineering.work.current_condition",
             "bind": {"artifact_ref": "event.artifact_ref"}, "next": "accepted"},
            {"id": "accepted", "kind": "stop", "outcome": "accepted"},
        ],
    }
    if declared:
        workflow["cancellation"] = "authenticated_request_then_reconcile_external_effects"
    return workflow


def _cancel_parameters(e, run_id):
    row = query(e, "engineering.work.get", {"run_id": run_id},
                "phase3-cancel-parameters-" + run_id)
    return {
        "run_id": run_id,
        "expected_row_digest": row["row_digest"],
        "expected_next_step_ordinal": row["next_step_ordinal"],
        "reason": "operator requested stop",
    }


def _reopen_env(e):
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl

    old = e["lib"]
    path, library_id = old.path, old.library_id
    old.close()
    library = EngineeringLibrary.open(path, library_id=library_id)
    factory = SQLiteUoWFactory(library)
    store = SQLiteSnapshotStore(library)
    controls = SQLiteMethodControl(factory, store)
    bindings = MethodRunBindings(factory, controls, e["source"], e["bindings"].registry_loader)
    e.update(lib=library, factory=factory, store=store, controls=controls, bindings=bindings,
             facade=EngineeringService(factory, e["access"], current_wait_bindings=bindings))
    return library


def _declare_native_cancel_method(setup):
    """Freeze a test-only variant retaining native dispatch with cancel policy."""
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
    from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
    from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.methods import compile_method, load_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities

    e = setup["env"]
    source_root = Path(e["root"]).parent / "dispatch-method"
    workflow = json.loads((source_root / "workflow.yaml").read_text(encoding="utf-8"))
    workflow["stop_outcomes"].append("cancelled")
    workflow["cancellation"] = "authenticated_request_then_reconcile_external_effects"
    variant_root = Path(e["root"]).parent / "dispatch-method-cancellable"
    variant_root.mkdir()
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode()
    (variant_root / "workflow.yaml").write_bytes(workflow_bytes)
    manifest = json.loads((source_root / "method.yaml").read_text(encoding="utf-8"))
    manifest["method_id"] = "test.dispatch-method-run-cancellable"
    manifest["release_version"] = "2.0.0"
    manifest["resources"][0]["sha256"] = hashlib.sha256(workflow_bytes).hexdigest()
    (variant_root / "method.yaml").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="utf-8")

    descriptor = next(item for item in owner_capabilities()
                      if item.capability_id == "engineering.executions.dispatch")
    capabilities = CompilationCapabilities(
        (*command_capabilities().capabilities, descriptor), trust_class="host")
    loaded = load_method(MethodSource(variant_root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, capabilities, "fixture:cancellable-dispatch")
    assert compiled.ok and compiled.value is not None, compiled.error

    class Catalog:
        def read_current(self):
            return capabilities

    frozen = freeze_method(compiled.value, e["store"], e["store"],
                           capability_catalog=Catalog())
    assert frozen.ok and frozen.value is not None, frozen.error
    ref = frozen.value.ref
    method_ref = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                           Digest("sha256", ref.snapshot_digest))
    e["management"].adopt(method_ref,
        _context(e["scope"], "adopt-cancellable-dispatch-method"), expected_version=2)
    old_package = setup["package"]
    setup["method"] = method_ref
    setup["package"] = SimpleNamespace(scope=old_package.scope, ref=old_package.ref,
        payload=SimpleNamespace(method_ref=method_ref))
    return setup


def test_declared_cancel_replays_recovers_and_cannot_resume(env):
    adopt_workflow_variant(env, _cancel_workflow(), "test.current-work-cancel-declared")
    run_id = "phase3-cancel-run"
    call(env, "engineering.work.start", {"run_id": run_id}, "phase3-cancel-start")
    env["source"].revoked = True
    parameters = _cancel_parameters(env, run_id)
    before = env["lib"].run_row(run_id)
    cancelled = call(env, "engineering.runs.cancel", parameters, "phase3-cancel-command")
    env["source"].revoked = False
    assert cancelled.status == "completed"
    assert cancelled.result["status"] == "SLICE_DONE"
    assert cancelled.result["cursor"] == before["cursor"]
    assert cancelled.result["stop_outcome"] == "cancelled"
    assert cancelled.result["unit_stop_confirmed"] is False
    row = env["lib"].run_row(run_id)
    assert row["status"] == "SLICE_DONE"
    assert row["cursor"] == before["cursor"]
    assert row["wait_reason"] is None
    with env["factory"].begin(env["scope"], "read") as uow:
        steps = uow.workflow.step_rows(run_id)
        assert len(steps) == 1 and steps[0]["status"] == "cancelled"
        receipt = uow.workflow.read(steps[0]["receipt_ref"])
        assert receipt["stop_outcome"] == "cancelled"
        assert receipt["unit_stop_confirmed"] is False
        assert receipt["external_effects_reversed"] is False

    replay = call(env, "engineering.runs.cancel", parameters, "phase3-cancel-command")
    assert replay == cancelled
    assert len(env["lib"].step_rows(run_id)) == 1

    library = _reopen_env(env)
    try:
        replay_after_reopen = call(env, "engineering.runs.cancel", parameters,
                                   "phase3-cancel-command")
        assert replay_after_reopen == cancelled
        recovered = query(env, "engineering.work.get", {"run_id": run_id},
                          "phase3-cancel-recovered")
        assert recovered["status"] == "SLICE_DONE"
        assert recovered["method_ref"] == asdict(before["method_ref"])
        assert recovered["inputs"]["method_ref"] == before["inputs"]["method_ref"]
        resume_params = {
            "run_id": run_id,
            "expected_row_digest": recovered["row_digest"],
            "expected_condition_digest": {"algorithm": "sha256", "hex": "e" * 64},
            "expected_next_step_ordinal": recovered["next_step_ordinal"],
        }
        with pytest.raises(ApplicationError, match="WORK_WAIT_UNAVAILABLE"):
            call(env, "engineering.runs.resume", resume_params, "phase3-cancel-resume")
        assert library.run_row(run_id)["status"] == "SLICE_DONE"
        with env["factory"].begin(env["scope"], "read") as uow:
            assert uow.commands.get(_context(env["scope"], "phase3-cancel-resume").key) is None
            assert len(uow.workflow.step_rows(run_id)) == 1
    finally:
        library.close()


def test_undeclared_cancel_is_refused_without_writes(env):
    adopt_workflow_variant(env, _cancel_workflow(declared=False),
                           "test.current-work-cancel-undeclared")
    run_id = "phase3-cancel-run"
    call(env, "engineering.work.start", {"run_id": run_id}, "phase3-cancel-start")
    parameters = _cancel_parameters(env, run_id)
    before = env["lib"].run_row(run_id)

    with pytest.raises(ApplicationError, match="WORK_CANCELLATION_UNAVAILABLE"):
        call(env, "engineering.runs.cancel", parameters, "phase3-cancel-undeclared-request")
    assert env["lib"].run_row(run_id) == before
    with env["factory"].begin(env["scope"], "read") as uow:
        assert uow.workflow.step_rows(run_id) == []
        assert uow.commands.get(_context(env["scope"],
            "phase3-cancel-undeclared-request").key) is None


def test_stale_foreign_and_access_denied_cancel_requests_write_nothing(env):
    adopt_workflow_variant(env, _cancel_workflow(), "test.current-work-cancel-declared")
    run_id = "phase3-cancel-run"
    call(env, "engineering.work.start", {"run_id": run_id}, "phase3-cancel-start-declared")
    base = _cancel_parameters(env, run_id)
    stale = {**base, "expected_row_digest": {"algorithm": "sha256", "hex": "f" * 64}}
    before = env["lib"].run_row(run_id)
    with pytest.raises(ApplicationError, match="RUN_WAIT_CHANGED"):
        call(env, "engineering.runs.cancel", stale, "phase3-cancel-stale")
    assert env["lib"].run_row(run_id) == before

    foreign_context = dataclass_replace(_context(env["scope"], "phase3-cancel-foreign"),
        scope=type(env["scope"])("foreign-realm", "foreign-project"))
    with pytest.raises(ApplicationError, match="WORK_BINDING_INVALID"):
        import asyncio
        asyncio.run(env["facade"].execute("engineering.runs.cancel", base, foreign_context))
    assert env["lib"].run_row(run_id) == before
    with env["factory"].begin(foreign_context.scope, "read") as uow:
        assert uow.commands.get(foreign_context.key) is None

    class DeniedAccess:
        def require(self, context, operation):
            raise ApplicationError("ACCESS_DENIED")

    denied = EngineeringService(env["factory"], DeniedAccess(),
                                current_wait_bindings=env["bindings"])
    denied_context = _context(env["scope"], "phase3-cancel-denied")
    import asyncio
    with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
        asyncio.run(denied.execute("engineering.runs.cancel", base, denied_context))
    assert env["lib"].run_row(run_id) == before
    with env["factory"].begin(env["scope"], "read") as uow:
        assert uow.workflow.step_rows(run_id) == []
        for request_id in ("phase3-cancel-stale", "phase3-cancel-denied"):
            assert uow.commands.get(_context(env["scope"], request_id).key) is None


def test_candidate_round_two_recovers_from_original_sqlite_after_reopen(persisted_source):
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    loop = next(item for item in snapshot.program.workflow.loops
                if item.loop_id == "implementation-rework")
    assert loop.max_rounds == 2
    assert loop.on_exhausted == "revision_required"

    run_id, context = _persist_rework_run(e, method_ref, snapshot, rounds=2)
    bindings = MethodRunBindings(e["factory"], e["controls"], None, None)
    persisted_before = e["library"].run_row(run_id)
    before = MethodRunOrchestrator(e["factory"], e["access"], bindings).read(
        {"run_id": run_id}, context)
    assert before["method_ref"] == asdict(persisted_before["method_ref"])
    assert before["inputs"]["method_ref"] == asdict(method_ref)
    assert before["inputs"]["rounds"] == {"implementation-rework": 2}
    assert before["method_run"]["status"] == "RUNNING"

    original = e["library"]
    path, library_id = original.path, original.library_id
    original.close()
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl

    reopened = EngineeringLibrary.open(path, library_id=library_id)
    try:
        factory = SQLiteUoWFactory(reopened)
        store = SQLiteSnapshotStore(reopened)
        controls = SQLiteMethodControl(factory, store)
        read = MethodRunOrchestrator(factory, e["access"],
            MethodRunBindings(factory, controls, None, None)).read(
                {"run_id": run_id}, context)
        assert read["method_ref"] == asdict(persisted_before["method_ref"])
        assert read["inputs"]["method_ref"] == asdict(method_ref)
        assert read["inputs"]["rounds"] == {"implementation-rework": 2}
        assert read["cursor"] == before["cursor"]
        assert read["method_run"] == before["method_run"]
    finally:
        reopened.close()


@pytest.mark.parametrize("rounds", [{}, {"implementation-rework": 3}])
def test_candidate_recovery_rejects_missing_or_exhausted_round_state(persisted_source, rounds):
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    run_id, context = _persist_rework_run(e, method_ref, snapshot,
                                          rounds=rounds.get("implementation-rework", 1))
    with e["factory"].begin(context.scope) as uow:
        row = uow.workflow.run_row(run_id)
        changed = {**row["inputs"], "rounds": rounds}
        uow.workflow.replace_run_inputs(run_id=run_id,
            expected_inputs=row["inputs"], inputs=changed)
        uow.commit()
    bindings = MethodRunBindings(e["factory"], e["controls"], None, None)
    with pytest.raises(ApplicationError, match="WORK_LOOP_STATE_INVALID"):
        MethodRunOrchestrator(e["factory"], e["access"], bindings).read(
            {"run_id": run_id}, context)


def test_candidate_rework_limit_projection_consumes_two_original_commands(env):
    """Exercise the shared counted-loop mechanism with candidate policy values.

    The temporary workflow uses a real public artifact command as its loop
    operation. Only max_rounds and on_exhausted are projected from the exact
    2.6 candidate declaration; this is not the candidate business review loop.
    """
    import yaml
    from pathlib import Path

    from test_persisted_method_work import CANDIDATE

    source = Path(CANDIDATE) / "workflows" / "change-cycle.yaml"
    declared = yaml.safe_load(source.read_text(encoding="utf-8"))
    candidate_loop = next(item for item in declared["loops"]
                          if item["loop_id"] == "implementation-rework")
    assert candidate_loop["max_rounds"] == 2
    assert candidate_loop["on_exhausted"] == "revision_required"

    workflow = {
        "schema_version": 1,
        "workflow_id": "candidate-rework-loop-mechanism-projection",
        "entry": "seed",
        "resume_contract": WORK_CONTRACT,
        "context_slots": ["kind", "initial", "artifact_ref"],
        "wait_kinds": ["owner_reconciliation"],
        "stop_outcomes": ["revision_required"],
        "steps": [
            {"id": "seed", "kind": "wait", "event": "engineering.work.current_condition",
             "bind": {"artifact_ref": "event.artifact_ref"}, "next": "record_rework_review"},
            {"id": "record_rework_review", "kind": "operation",
             "operation": "engineering.artifacts.create",
             "inputs": {"kind": "kind", "initial": "initial"},
             "outcomes": {"completed": {"stop": "revision_required"},
                          "rejected": {"stop": "revision_required"}},
             "result_routing": {"path": "/revision_ref/project_id",
                                "outcomes": {"project-1": {"next": "record_rework_review"}}}},
        ],
        "loops": [{
            "loop_id": candidate_loop["loop_id"],
            "from_step": "record_rework_review",
            "to_step": "record_rework_review",
            "max_rounds": candidate_loop["max_rounds"],
            "on_exhausted": candidate_loop["on_exhausted"],
        }],
    }
    adopt_workflow_variant(env, workflow, "test.candidate-rework-loop-projection")

    call(env, "engineering.work.start", {"run_id": "phase3-loop-projection"},
         "phase3-loop-start")
    ready = query(env, "engineering.work.current_condition", {"run_id": "phase3-loop-projection"},
                  "phase3-loop-condition")
    call(env, "engineering.runs.resume", {
        "run_id": "phase3-loop-projection",
        "expected_row_digest": ready["row_digest"],
        "expected_condition_digest": ready["condition_digest"],
        "expected_next_step_ordinal": ready["next_step_ordinal"],
    }, "phase3-loop-resume")
    row = query(env, "engineering.work.get", {"run_id": "phase3-loop-projection"},
                "phase3-loop-read-1")
    parameters = {"kind": row["inputs"]["slots"]["kind"],
                  "initial": row["inputs"]["slots"]["initial"]}

    first = call(env, "engineering.artifacts.create", parameters, "phase3-loop-command-1")
    assert first.status == "completed"
    current = env["lib"].run_row("phase3-loop-projection")
    consumed = call(env, "engineering.work.record_command_step", {
        "run_id": "phase3-loop-projection",
        "operation_request_id": "phase3-loop-command-1",
        "expected_row_digest": asdict(run_wait_row_digest(current)),
        "expected_next_step_ordinal": 0,
    }, "phase3-loop-record-1")
    assert consumed.status == "completed"
    current = env["lib"].run_row("phase3-loop-projection")
    assert current["inputs"]["rounds"] == {"implementation-rework": 2}
    assert current["status"] == "RUNNING"
    assert current["cursor"] == 1
    with pytest.raises(ApplicationError, match="WORK_COMMAND_ALREADY_CONSUMED"):
        call(env, "engineering.work.record_command_step", {
            "run_id": "phase3-loop-projection",
            "operation_request_id": "phase3-loop-command-1",
            "expected_row_digest": asdict(run_wait_row_digest(current)),
            "expected_next_step_ordinal": 1,
        }, "phase3-loop-reuse-command-1")

    # Recreate the public service over the same owners and same SQLite state.
    env["facade"] = EngineeringService(env["factory"], env["access"],
                                       current_wait_bindings=env["bindings"])
    second = call(env, "engineering.artifacts.create", parameters, "phase3-loop-command-2")
    assert second.status == "completed"
    current = env["lib"].run_row("phase3-loop-projection")
    exhausted = call(env, "engineering.work.record_command_step", {
        "run_id": "phase3-loop-projection",
        "operation_request_id": "phase3-loop-command-2",
        "expected_row_digest": asdict(run_wait_row_digest(current)),
        "expected_next_step_ordinal": 1,
    }, "phase3-loop-record-2")
    assert exhausted.result["status"] == "SLICE_DONE"
    view = query(env, "engineering.work.get", {"run_id": "phase3-loop-projection"},
                 "phase3-loop-read-final")
    assert [(step["attempt"], step["status"]) for step in view["steps"]] == [
        (1, "completed"), (2, "completed")]
    assert view["inputs"]["rounds"] == {"implementation-rework": 2}
    with env["factory"].begin(env["scope"], "read") as uow:
        rows = uow.workflow.step_rows("phase3-loop-projection")
        last_receipt = uow.workflow.read(rows[-1]["receipt_ref"])
        assert last_receipt["stop_outcome"] == "revision_required"


@pytest.fixture
def native_dispatch_setup(request):
    """Reuse the existing original-native fixture with this module's env."""
    from test_native_method_step import dispatch_setup as native_fixture
    return native_fixture.__wrapped__(request.getfixturevalue("env"))


def test_unknown_native_result_stays_unconsumed_after_reopening_original_sqlite(
        native_dispatch_setup, monkeypatch):
    from test_native_method_step import (
        _dispatch_row, _params, _record, _reserve, _step_count, _stub_package_resolver,
    )
    from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
    from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
    from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
    from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
    from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings

    _declare_native_cancel_method(native_dispatch_setup)
    _reserve(native_dispatch_setup, "unknown")
    e = native_dispatch_setup["env"]
    _stub_package_resolver(monkeypatch, native_dispatch_setup["package"], [])
    original_row = e["lib"].run_row("dispatch-run")
    cancel = _cancel_parameters(e, "dispatch-run")
    with pytest.raises(ApplicationError, match="WORK_CANCELLATION_RECONCILIATION_REQUIRED"):
        call(e, "engineering.runs.cancel", cancel, "phase3-cancel-unknown")
    assert e["lib"].run_row("dispatch-run") == original_row
    assert _step_count(e) == 1
    with e["factory"].begin(e["scope"], "read") as uow:
        assert uow.commands.get(_context(e["scope"], "phase3-cancel-unknown").key) is None
    with pytest.raises(ApplicationError, match="WORK_OPERATION_OUTCOME_UNKNOWN"):
        _record(e, _params(e), "phase3-unknown-record")
    assert e["lib"].run_row("dispatch-run") == original_row
    assert _step_count(e) == 1

    original = e["lib"]
    path, library_id = original.path, original.library_id
    original.close()
    reopened = EngineeringLibrary.open(path, library_id=library_id)
    try:
        factory = SQLiteUoWFactory(reopened)
        store = SQLiteSnapshotStore(reopened)
        controls = SQLiteMethodControl(factory, store)
        bindings = MethodRunBindings(factory, controls, e["source"], e["bindings"].registry_loader)
        from ordessa_engineering.application.api.service import EngineeringService
        e["lib"], e["factory"], e["store"], e["controls"] = (
            reopened, factory, store, controls)
        e["bindings"] = bindings
        e["facade"] = EngineeringService(factory, e["access"], current_wait_bindings=bindings)
        before_retry = reopened.run_row("dispatch-run")
        with pytest.raises(ApplicationError, match="WORK_OPERATION_OUTCOME_UNKNOWN"):
            _record(e, _params(e), "phase3-unknown-record")
        assert reopened.run_row("dispatch-run") == before_retry
        assert _step_count(e) == 1
        assert _dispatch_row(e)[3:5] == ("unknown", "unknown")
        with reopened._read_connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM eng_commands "
                "WHERE operation='engineering.work.record_dispatch_step' "
                "AND request_id='phase3-unknown-record'").fetchone()[0] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize("phase", ["completed", "failed"])
def test_cancel_records_known_native_result_without_erasing_it(
        native_dispatch_setup, phase):
    from test_native_method_step import _dispatch_row, _reserve, _step_count

    _declare_native_cancel_method(native_dispatch_setup)
    prepared = _reserve(native_dispatch_setup, phase)
    e = native_dispatch_setup["env"]
    before = e["lib"].run_row("dispatch-run")
    before_dispatch = _dispatch_row(e)
    assert before_dispatch[3:5] == (phase, phase)
    with e["factory"].begin(e["scope"], "read") as uow:
        assert uow.implementation.read_blob(prepared["result_ref"])

    cancelled = call(e, "engineering.runs.cancel", _cancel_parameters(e, "dispatch-run"),
                     "phase3-cancel-known-" + phase)
    assert cancelled.status == "completed"
    assert cancelled.result["stop_outcome"] == "cancelled"
    assert cancelled.result["unit_stop_confirmed"] is False
    after = e["lib"].run_row("dispatch-run")
    assert after["status"] == "SLICE_DONE"
    assert after["cursor"] == before["cursor"]
    assert after["inputs"] == before["inputs"]
    assert _dispatch_row(e) == before_dispatch
    assert _step_count(e) == 2
    with e["factory"].begin(e["scope"], "read") as uow:
        rows = uow.workflow.step_rows("dispatch-run")
        receipt = uow.workflow.read(rows[-1]["receipt_ref"])
        assert receipt["operation"] == "engineering.runs.cancel"
        assert receipt["known_dispatches"] == [{
            "step_id": "dispatch", "attempt": 1,
            "operation_ref": prepared["dispatch"]["execution_operation_ref"],
            "phase": phase, "binding_digest": asdict(prepared["dispatch"]["binding_digest"]),
        }]


@pytest.mark.parametrize(("tamper", "expected"), [
    ("missing", "IMPLEMENTATION_BLOB_NOT_FOUND"),
    ("corrupt", "IMPLEMENTATION_BLOB_CORRUPT"),
])
def test_cancel_refuses_missing_or_corrupt_terminal_result_blob(
        native_dispatch_setup, tamper, expected):
    from test_native_method_step import _dispatch_row, _reserve, _step_count

    _declare_native_cancel_method(native_dispatch_setup)
    prepared = _reserve(native_dispatch_setup, "completed")
    e = native_dispatch_setup["env"]
    before = e["lib"].run_row("dispatch-run")
    before_dispatch = _dispatch_row(e)
    parameters = _cancel_parameters(e, "dispatch-run")
    with e["lib"].transaction() as connection:
        if tamper == "missing":
            connection.execute("DELETE FROM eng_method_blobs WHERE digest=?",
                               (prepared["result_ref"].digest.hex,))
        else:
            connection.execute("UPDATE eng_method_blobs SET body=? WHERE digest=?",
                               (b"X" * prepared["result_ref"].byte_length,
                                prepared["result_ref"].digest.hex))

    with pytest.raises(ApplicationError, match=expected):
        call(e, "engineering.runs.cancel", parameters,
             "phase3-cancel-blob-" + tamper)
    assert e["lib"].run_row("dispatch-run") == before
    assert _dispatch_row(e) == before_dispatch
    assert _step_count(e) == 1
    with e["factory"].begin(e["scope"], "read") as uow:
        assert uow.commands.get(_context(e["scope"],
            "phase3-cancel-blob-" + tamper).key) is None


@pytest.mark.parametrize(("encoded", "expected"), [
    ("not-json", "DISPATCH_RECORD_CORRUPT"),
    ("{}", "WORK_CANCELLATION_RECONCILIATION_REQUIRED"),
])
def test_cancel_refuses_malformed_terminal_result_locator(native_dispatch_setup, encoded, expected):
    import sqlite3
    from pathlib import Path
    from test_native_method_step import _dispatch_row, _reserve, _step_count

    _declare_native_cancel_method(native_dispatch_setup)
    _reserve(native_dispatch_setup, "failed")
    e = native_dispatch_setup["env"]
    parameters = _cancel_parameters(e, "dispatch-run")
    before_dispatch = _dispatch_row(e)
    sql = "UPDATE step_log SET result_blob_json=? WHERE run_id=? AND step_id=? AND attempt=?"
    values = (encoded, "dispatch-run", "dispatch", 1)
    with pytest.raises(sqlite3.IntegrityError, match="DISPATCH_TERMINAL_IMMUTABLE"):
        with e["lib"].transaction() as connection:
            connection.execute(sql, values)
    assert _dispatch_row(e) == before_dispatch
    # Explicit corruption injection in this temporary fixture database only.
    # Normal terminal writes remain immutable and were asserted above.
    assert Path(e["lib"].path).is_relative_to(Path(e["root"]).parent)
    with e["lib"].transaction() as connection:
        triggers = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='step_log' AND (sql LIKE '%DISPATCH_TERMINAL_IMMUTABLE%' "
            "OR sql LIKE '%DISPATCH_TRANSITION_INVALID%')").fetchall()
        assert {row[0] for row in triggers} == {
            'step_log_dispatch_terminal_immutable', 'step_log_dispatch_transition'}
        for name, _ddl in triggers:
            connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        connection.execute(sql, values)
        for _name, ddl in triggers:
            connection.execute(ddl)

    with pytest.raises(ApplicationError, match=expected):
        call(e, "engineering.runs.cancel", parameters,
             "phase3-cancel-malformed-locator")
    after_dispatch = _dispatch_row(e)
    assert after_dispatch[:6] == before_dispatch[:6]
    assert after_dispatch[6] == encoded
    assert _step_count(e) == 1
    with e["factory"].begin(e["scope"], "read") as uow:
        assert uow.commands.get(_context(e["scope"],
            "phase3-cancel-malformed-locator").key) is None


def test_cancel_refuses_valid_but_mismatched_method_run_marker(native_dispatch_setup):
    from ordessa_engineering.domain.artifacts.library_material_codec import (
        canonical_json, material_ref_to_dict,
    )
    from test_native_method_step import _dispatch_row, _reserve, _step_count

    _declare_native_cancel_method(native_dispatch_setup)
    _reserve(native_dispatch_setup, "completed")
    e = native_dispatch_setup["env"]
    original_row = e["lib"].run_row("dispatch-run")
    original_dispatch = _dispatch_row(e)
    parameters = _cancel_parameters(e, "dispatch-run")
    with e["factory"].begin(e["scope"], "read") as uow:
        mismatched_marker = dict(uow.workflow.read(original_row["method_ref"]))
    mismatched_marker["scope"] = {"realm_id": "other-realm", "project_id": "other-project"}
    with e["factory"].begin(e["scope"]) as uow:
        mismatched_ref = uow.workflow.write_material(
            kind="method", stable_id="phase3-cancel-marker-mismatch", revision=1,
            body=mismatched_marker, generated=False)
        uow.commit()
    with e["lib"].transaction() as connection:
        connection.execute("UPDATE runs SET method_ref_json=? WHERE run_id=?",
                           (canonical_json(material_ref_to_dict(mismatched_ref)), "dispatch-run"))
    mismatched_row = e["lib"].run_row("dispatch-run")

    with pytest.raises(ApplicationError, match="WORK_BINDING_INVALID"):
        query(e, "engineering.work.get", {"run_id": "dispatch-run"},
              "phase3-cancel-marker-mismatch-read")
    parameters["expected_row_digest"] = asdict(run_wait_row_digest(mismatched_row))

    with pytest.raises(ApplicationError, match="WORK_BINDING_INVALID"):
        call(e, "engineering.runs.cancel", parameters,
             "phase3-cancel-marker-mismatch")
    assert e["lib"].run_row("dispatch-run") == mismatched_row
    assert _dispatch_row(e) == original_dispatch
    assert _step_count(e) == 1
    with e["factory"].begin(e["scope"], "read") as uow:
        assert uow.commands.get(_context(e["scope"],
            "phase3-cancel-marker-mismatch").key) is None


def test_candidate_rework_record_journal_is_consumed_by_original_method_run(
        persisted_source):
    """Consume a real candidate request and record command around a seeded response prefix.

    Selection, request journaling, request consumption, review recording and
    record consumption use the original owners. The response event and cursor
    after the response wait are an explicit fixture prefix; no Unit response
    producer or full candidate execution is claimed.
    """
    import asyncio
    import hashlib
    from contextlib import contextmanager
    from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
    from ordessa_engineering.application.orchestration.method_runs import MethodRunBindings
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.models import (
        CurrentReviewTrust, Observation, ReviewRecord, observations_digest,
    )
    from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
    from ordessa_engineering.domain.reviews.identity import RecordIdentity
    from ordessa_infrastructure.encoding import canonical_bytes
    from test_review_usecases import REVIEWER, TEST_ACTOR, _context
    from test_work_request_round_guard_phase1 import (
        _ControlledWorkAdmission, _append_correction_plan, _append_v2_input,
        _candidate_proposal, _freeze_candidate,
    )
    from ordessa_engineering.application.contracts.operation_registry import registry_ref

    e = persisted_source
    scope = e["input_revision"].scope
    method_ref, snapshot = _freeze_candidate(e)
    e["snapshot"] = snapshot
    correction = _append_correction_plan(e, method_ref)
    proposal_ref = _candidate_proposal(e, method_ref)
    run_id = "phase3-candidate-record-run"
    review_id = "phase3-candidate-record-review"
    input_value = {
        "document_type": "work-inputs", "schema_version": 2, "run_id": run_id,
        "proposal_ref": asdict(proposal_ref), "events": {},
        "events_by_round": {"1": {"await_rework_review_response": {}}},
    }
    input_revision = _append_v2_input(e, snapshot, method_ref, input_value,
                                      "phase3-candidate-record-input")
    slots = {"method_ref": asdict(method_ref), "proposal_ref": asdict(proposal_ref),
        "work_inputs": asdict(input_revision.ref), "correction_plan_ref": asdict(correction.ref)}
    request_index = next(i for i, node in enumerate(snapshot.program.workflow.steps)
                         if node.id == "rework_review")
    response_index = next(i for i, node in enumerate(snapshot.program.workflow.steps)
                          if node.id == "await_rework_review_response")
    record_index = next(i for i, node in enumerate(snapshot.program.workflow.steps)
                        if node.id == "record_rework_review")
    context = _context(scope, "phase3-candidate-record-seed")
    marker = {"work_contract": WORK_CONTRACT, "scope": asdict(scope),
        "method_ref": asdict(method_ref), "compiled_plan_digest": program_plan_digest(snapshot.program)}
    registry = {"registry_id": "phase3-candidate-registry", "revision": 1,
        "registry_digest": "sha256:" + "c" * 64}
    with e["factory"].begin(scope) as uow:
        material_ref = uow.workflow.write_material(kind="method", stable_id=run_id,
            revision=1, body=marker, generated=False)
        uow.workflow.insert_run(run_id=run_id, method_ref=material_ref,
            registry_ref=registry_ref(registry),
            inputs={**marker, "slots": slots, "rounds": {"implementation-rework": 1}},
            now=context.received_at)
        uow.workflow.update_run(run_id=run_id, status="RUNNING", cursor=request_index,
            wait_reason=None, now=context.received_at)
        uow.commit()

    blobs = SQLiteBlobStore(e["library"])
    review_bindings = SQLiteWorkReviewBindings(e["factory"], e["controls"],
        scope=scope, blobs=blobs)
    selection_context = _context(scope, "phase3-candidate-select")
    _selector, plan = review_bindings.review_selection(selection_context,
        run_id=run_id, review_id=review_id, subject_ref=correction.ref)
    with e["factory"].begin(scope) as uow:
        row = uow.workflow.run_row(run_id)
        updated = {**row["inputs"], "slots": {
            **row["inputs"]["slots"], "rework_review_plan": asdict(plan)}}
        uow.workflow.replace_run_inputs(run_id=run_id, expected_inputs=row["inputs"], inputs=updated)
        uow.commit()

    # The first selection derives the exact plan; the second captures the
    # selector against the row after that plan is in its declared slot.
    selector, selected_plan = review_bindings.review_selection(
        _context(scope, "phase3-candidate-select-current"), run_id=run_id,
        review_id=review_id, subject_ref=correction.ref)
    assert selected_plan == plan

    class CompleteControlledAdmission:
        """Controlled external reviewer source with one answer per Plan CheckKey."""

        def __init__(self):
            self.work = _ControlledWorkAdmission(review_bindings)

        @contextmanager
        def guard_plan(self, context, selected_plan, *, work_selector=None):
            with review_bindings.guard_plan_bindings(
                    context, selected_plan, work_selector=work_selector):
                yield object()

        def check_work_review_current(self, uow, context, selected_plan, work_selector):
            return self.work.check_work_review_current(uow, context, selected_plan, work_selector)

        def work_review_result(self, context, selected_plan, work_selector, entry,
                               *, request, work_facts):
            return self.work.work_review_result(context, selected_plan, work_selector,
                entry, request=request, work_facts=work_facts)

        def verify_response(self, context, selected_plan, request, raw_ref):
            raw = blobs.read_verified(raw_ref)
            assert raw == raw_response
            observations = tuple(Observation(key, "pass", (),
                "controlled fixture reviewer answered this exact check")
                for key in selected_plan.check_keys)
            evidence = VerifiedReviewerEvidence(scope, REVIEWER,
                selected_plan.reviewer_requirements,
                "controlled-reviewer", "1", 7, selected_plan.request_digest,
                raw_ref.digest, observations_digest(observations), Digest("sha256", "c" * 64))
            return ReviewRecord(RecordIdentity(scope, selected_plan.review_id,
                context.received_at, TEST_ACTOR, schema_version=2), selected_plan,
                evidence, observations, raw_response_ref=raw_ref)

        @contextmanager
        def guard_trust(self, context, records):
            yield tuple(CurrentReviewTrust(record.ref, record.reviewer_evidence.verifier_id,
                record.reviewer_evidence.trust_version) for record in records)

    admission = CompleteControlledAdmission()
    source = SQLitePersistedMethodWorkSource(e["factory"], e["controls"],
        blobs=blobs, review_bindings=review_bindings)
    bindings = MethodRunBindings(e["factory"], e["controls"], source, lambda: registry)
    facade = EngineeringService(e["factory"], e["access"], review_admission=admission,
        blobs=blobs, current_wait_bindings=bindings)
    e["facade"] = facade

    request_id = "phase3-candidate-review-request-command"
    request_context = _context(scope, request_id)
    request_row = e["library"].run_row(run_id)
    request_node = snapshot.program.workflow.steps[request_index]
    with source.guard_step_completion(request_context, snapshot, request_node,
            {"run_id": run_id, "row": request_row}) as request_reads:
        requested = asyncio.run(facade.execute("engineering.reviews.request",
            {"plan": asdict(plan)}, request_context, read_set=request_reads,
            work_selector=selector))
    assert requested.status == "completed"
    with e["factory"].begin(scope, "read") as uow:
        request = uow.reviews.get_request(review_id)
    request_row = e["library"].run_row(run_id)
    request_step = asyncio.run(facade.execute("engineering.work.record_command_step", {
        "run_id": run_id, "operation_request_id": request_id,
        "expected_row_digest": asdict(run_wait_row_digest(request_row)),
        "expected_next_step_ordinal": 0,
    }, _context(scope, "phase3-candidate-review-request-step")))
    assert request_step.status == "completed"
    assert request_step.result["status"] == "WAITING_FOR_CONDITION"
    assert request_step.result["cursor"] == response_index

    raw_response = canonical_bytes({"document_type": "unit-review-result", "schema_version": 1,
        "plan_digest": asdict(plan.plan_digest), "answers": [
            {"check_key": asdict(key), "status": "satisfied", "evidence_refs": [],
             "rationale": "controlled test admission"} for key in plan.check_keys]})
    raw_ref = blobs.put_verified(raw_response,
        Digest("sha256", hashlib.sha256(raw_response).hexdigest()), "application/json")
    appended_input = {
        **input_value,
        "events_by_round": {"1": {"await_rework_review_response": {
            "review_id": review_id, "request_version": request.version,
            "fence": request.fence, "raw_response_ref": asdict(raw_ref)}}},
    }
    appended_revision = _append_v2_input(e, snapshot, method_ref, appended_input,
        "phase3-candidate-record-input-after-request", parents=(input_revision.ref,))
    raw_utf8 = raw_response.decode("utf-8")
    parameters = {"review_id": review_id, "request_version": request.version,
        "fence": request.fence, "raw_response_utf8": raw_utf8}
    with e["factory"].begin(scope) as uow:
        row = uow.workflow.run_row(run_id)
        updated = {**row["inputs"], "slots": {**row["inputs"]["slots"],
            "work_inputs": asdict(appended_revision.ref),
            "rework_review_id": review_id, "rework_request_version": request.version,
            "rework_review_fence": request.fence, "rework_raw_response_utf8": raw_utf8}}
        uow.workflow.replace_run_inputs(run_id=run_id, expected_inputs=row["inputs"], inputs=updated)
        # Historical response-wait prefix: the controlled fixture supplies the
        # exact v2 event and advances the persisted cursor to the declared
        # record operation. No external Unit response producer is simulated.
        uow.workflow.update_run(run_id=run_id, status="RUNNING", cursor=record_index,
            wait_reason=None, now=context.received_at)
        uow.commit()

    command_id = "phase3-candidate-review-record-command"
    record_context = _context(scope, command_id)
    current = e["library"].run_row(run_id)
    record_node = snapshot.program.workflow.steps[record_index]
    with source.guard_step_completion(record_context, snapshot, record_node,
            {"run_id": run_id, "row": current}) as invocation_reads:
        record_result = asyncio.run(facade.execute("engineering.reviews.record",
            parameters, record_context, read_set=invocation_reads))
    assert record_result.status == "completed"
    current = e["library"].run_row(run_id)
    consumed = asyncio.run(facade.execute("engineering.work.record_command_step", {
        "run_id": run_id, "operation_request_id": command_id,
        "expected_row_digest": asdict(run_wait_row_digest(current)),
        "expected_next_step_ordinal": 1,
    }, _context(scope, "phase3-candidate-review-record-step")))
    assert consumed.status == "completed"
    assert consumed.result["status"] == "WAITING_FOR_CONDITION"
    assert consumed.result["dispatched"] is False
    from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
    recorded_ref = decode_review_ref(record_result.result["review_ref"])
    with e["factory"].begin(scope, "read") as uow:
        saved = uow.reviews.get_review(recorded_ref)
        rows = uow.workflow.step_rows(run_id)
        request_receipt = uow.workflow.read(rows[0]["receipt_ref"])
        receipt = uow.workflow.read(rows[1]["receipt_ref"])
        journal = uow.commands.get(_context(scope, command_id).key)
    assert saved.record.plan == plan
    assert request_receipt["node_id"] == "rework_review"
    assert receipt["node_id"] == "record_rework_review"
    assert receipt["round"] == 1 and receipt["attempt"] == 1
    assert journal is not None and journal.state == "completed"


