"""Two-phase operation persistence on the original SQLite request ledger.

This slice exercises storage and the existing InvocationIssuer only. It never
resolves material, calls a provider, or performs native/Harness work.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
import json
import sqlite3
from threading import Barrier

import pytest

from ordessa_environment_api import RequestKey
from ordessa_environment_api.domain import DomainWrite
from ordessa_environment_api.errors import (
    GuaranteeUnavailableError,
    IdentityMismatchError,
    UnknownResultError,
)
from ordessa_environment_api.operations import (
    OperationIntent,
    OperationRevisionConflict,
    OperationStorePort,
    StepIntent,
    UsageMutation,
    node_holder,
    operation_holder,
    safe_json,
)
from ordessa_environment_api.staged_operations import (
    STAGED_OPERATION_STORE_VERSION,
    OperationRecipePhase,
    StagedOperationRecord,
    StagedOperationStorePort,
)
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.agents.directory import DirectoryBindingRef
from pacthold.agents.invocation import (
    InvocationAuthorityRefused,
    InvocationCurrentState,
    InvocationGrant,
    InvocationIssuer,
)


def _request(request_id="request"):
    return RequestKey("env", "principal", request_id)


def _provider(provider_id="material-owner", generation=1):
    return {
        "environmentNamespace": "env",
        "providerId": provider_id,
        "version": "1.0",
        "generation": generation,
    }


def _target(target_id="node"):
    return {
        "environmentNamespace": "env",
        "hostId": "fixture-host",
        "nativeRealm": "fixture-realm",
        "objectId": target_id,
        "scope": "unit",
        "generation": 1,
    }


def _binding(action="apply", *, cleanup=False, target=None):
    return {
        "action": action,
        "targetRef": target or _target(),
        "delegationRef": None,
        "cleanup": cleanup,
    }


def _root(request=None, *, operation_ref="operation", step_id="materials",
          provider=None, context_extra=None):
    request = request or _request()
    provider = provider or _provider()
    context = {
        "environmentNamespace": request.environment_namespace,
        "directoryBindingRef": DirectoryBindingRef(
            request.environment_namespace, "binding", 1, "sha256:" + "a" * 64
        ).to_dict(),
        "invocationBindings": {step_id: _binding()},
        "rootFact": {"environmentNamespace": request.environment_namespace, "value": "fixed"},
    }
    if context_extra:
        context.update(context_extra)
    step = StepIntent(step_id, provider, f"input-{step_id}", f"correlation-{step_id}")
    return OperationIntent(
        operation_ref,
        "controlled-staged-fixture",
        {"environmentNamespace": request.environment_namespace,
         "profileId": "profile", "revision": "1"},
        context,
        (step,),
        node_holder(request.environment_namespace, "node", 1),
        0,
    )


def _phase(*, phase_id="phase-one", step_id="configure", provider=None,
           context_facts=None, prerequisite=("materials",)):
    provider = provider or _provider("configuration-owner")
    step = StepIntent(
        step_id,
        provider,
        f"input-{step_id}",
        f"correlation-{step_id}",
        prerequisite,
        0,
    )
    binding = _binding()
    facts = context_facts or {
        "materialReceiptRef": {"environmentNamespace": "env", "receiptId": "receipt-1"}
    }
    return OperationRecipePhase(phase_id, (step,), {step_id: binding}, facts)


def _reserve(store, request=None, *, digest="request-digest", root=None, usages=()):
    request = request or _request()
    root = root or _root(request)
    return request, root, store.reserve_staged_operation(request, digest, root, usages=usages)


def _intent_digest(record):
    return hashlib.sha256(record.operation.intent_json.encode("utf-8")).hexdigest()


def _append(store, request, record, phase=None, *, digest="request-digest",
            revision=None, intent_digest=None):
    return store.append_staged_operation_phase(
        request,
        digest,
        record.operation.revision if revision is None else revision,
        _intent_digest(record) if intent_digest is None else intent_digest,
        phase or _phase(),
    )


def _conclude(store, request, intent, step, evidence=None):
    claim = store.claim_operation_step(request, "request-digest", step)
    assert claim.claimed
    return store.record_operation_step(
        request,
        "request-digest",
        step.step_id,
        step.input_digest,
        claim.step.revision,
        "concluded",
        evidence or {"evidenceRef": f"controlled-{step.step_id}"},
    )


def _usage(request, intent):
    return UsageMutation(
        "usage-1",
        0,
        None,
        operation_holder(request, intent.operation_ref),
        {"environmentNamespace": request.environment_namespace, "resourceId": "fixture"},
        ("use",),
        "active",
    )


def _usage_transfer(request, intent):
    return UsageMutation(
        "usage-1",
        1,
        operation_holder(request, intent.operation_ref),
        intent.node_ref,
        {"environmentNamespace": request.environment_namespace, "resourceId": "fixture"},
        ("use",),
        "active",
    )


def test_phase_dto_is_closed_deep_frozen_and_canonical():
    facts = {"materialReceiptRef": {"environmentNamespace": "env", "receiptId": "receipt-1"}}
    source = _phase(context_facts=facts).to_dict()
    phase = OperationRecipePhase.from_dict(source)
    facts["materialReceiptRef"]["receiptId"] = "mutated"
    source["invocationBindings"]["configure"]["targetRef"]["objectId"] = "mutated"

    assert phase.to_dict().keys() == {"phaseId", "steps", "invocationBindings", "contextFacts"}
    assert phase.to_dict()["contextFacts"]["materialReceiptRef"]["receiptId"] == "receipt-1"
    assert phase.digest == hashlib.sha256(safe_json(phase.to_dict()).encode("utf-8")).hexdigest()
    restored = OperationRecipePhase.from_dict(phase.to_dict())
    assert restored == phase
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        phase.phase_id = "other"
    for bad in (
        {**phase.to_dict(), "extra": True},
        {k: v for k, v in phase.to_dict().items() if k != "contextFacts"},
    ):
        with pytest.raises((TypeError, ValueError)):
            OperationRecipePhase.from_dict(bad)


def test_phase_copies_step_intents_without_calling_overridden_serializer():
    calls = []
    source_step = StepIntent(
        "configure", _provider("configuration-owner"), "input-configure",
        "correlation-configure", ("materials",), 0,
    )

    def forbidden_to_dict(self):
        calls.append(self.step_id)
        raise AssertionError("step serializer override must not execute")

    object.__setattr__(source_step, "to_dict", forbidden_to_dict.__get__(source_step, StepIntent))
    phase = OperationRecipePhase(
        "phase-one", (source_step,), {"configure": _binding()},
        {"materialReceiptRef": {"environmentNamespace": "env", "receiptId": "receipt-1"}},
    )
    assert calls == []
    assert phase.steps[0] is not source_step
    assert phase.steps[0].input_digest == "input-configure"
    object.__setattr__(source_step, "input_digest", "caller-mutated")
    assert phase.steps[0].input_digest == "input-configure"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["contextFacts"].update(environmentNamespace="env"),
        lambda d: d["contextFacts"].update(invocationBindings={}),
        lambda d: d["invocationBindings"].update(extra=_binding()),
    ],
)
def test_phase_rejects_root_overwrite_and_binding_shape_mismatch(mutate):
    value = _phase().to_dict()
    mutate(value)
    with pytest.raises((TypeError, ValueError)):
        OperationRecipePhase.from_dict(value)


def test_phase_rejects_references_without_complete_same_environment_scope(tmp_path):
    store = SqliteStorePort(tmp_path / "scope.sqlite")
    request, root, _ = _reserve(store)
    try:
        _conclude(store, request, root, root.steps[0])
        before = store.read_staged_operation(request)
        invalid_refs = (
            ("targetRef", {"environmentNamespace": "other", "objectId": "target"}),
            ("targetRef", {"objectId": "missing-environment"}),
            ("delegationRef", {"environmentNamespace": "other", "delegationId": "foreign"}),
            ("delegationRef", {"delegationId": "missing-environment"}),
        )
        for field, changed in invalid_refs:
            value = _phase().to_dict()
            value["invocationBindings"]["configure"][field] = changed
            phase = OperationRecipePhase.from_dict(value)
            with pytest.raises(IdentityMismatchError):
                _append(store, request, before, phase)
            assert store.read_staged_operation(request) == before

        # A syntactically valid fact cannot overwrite any frozen root context key.
        conflict = _phase(context_facts={
            "rootFact": {"environmentNamespace": "env", "value": "changed"}
        })
        with pytest.raises(IdentityMismatchError):
            _append(store, request, before, conflict)
        assert store.read_staged_operation(request) == before
    finally:
        store.close()


@pytest.mark.parametrize("invalid_recipe", ["duplicate-correlation", "future-prerequisite", "epoch"])
def test_merged_phase_rejects_duplicate_correlation_future_prerequisite_and_epoch(invalid_recipe, tmp_path):
    store = SqliteStorePort(tmp_path / f"{invalid_recipe}.sqlite")
    request, root, _ = _reserve(store)
    try:
        _conclude(store, request, root, root.steps[0])
        before = store.read_staged_operation(request)
        provider = _provider("later-owner")
        if invalid_recipe == "duplicate-correlation":
            steps = (StepIntent("configure", provider, "input", root.steps[0].recovery_correlation),)
        elif invalid_recipe == "future-prerequisite":
            steps = (
                StepIntent("configure", provider, "input-a", "correlation-a", ("later",)),
                StepIntent("later", provider, "input-b", "correlation-b", ("materials",)),
            )
        else:
            steps = (StepIntent("configure", provider, "input", "correlation-configure", (), 1),)
        bindings = {step.step_id: _binding() for step in steps}
        phase = OperationRecipePhase(
            "phase-one", steps, bindings,
            {"materialReceiptRef": {"environmentNamespace": "env", "receiptId": "receipt-1"}},
        )
        with pytest.raises(IdentityMismatchError):
            _append(store, request, before, phase)
        assert store.read_staged_operation(request) == before
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


def test_optional_port_is_additive_and_root_reservation_replays_cold(tmp_path):
    path = tmp_path / "staged.sqlite"
    request, root = _request(), _root()
    first = SqliteStorePort(path)
    try:
        assert isinstance(first, OperationStorePort)
        assert isinstance(first, StagedOperationStorePort)
        assert first.staged_operation_contract_version == STAGED_OPERATION_STORE_VERSION
        assert first.read_staged_operation(_request("missing")) is None
        created = first.reserve_staged_operation(request, "request-digest", root)
        assert type(created) is StagedOperationRecord
        assert created.root_intent == root
        assert created.phase is None and created.sealed is False
        assert created.root_intent_digest == hashlib.sha256(
            created.root_intent_json.encode("utf-8")).hexdigest()
        assert first.read_operation(request) == created.operation
        assert first.reserve_staged_operation(request, "request-digest", root) == created
        with pytest.raises(IdentityMismatchError):
            first.reserve_staged_operation(request, "request-digest", _root(operation_ref="other"))
        with pytest.raises(IdentityMismatchError):
            first.reserve_staged_operation(request, "different-input", root)
    finally:
        first.close()

    reopened = SqliteStorePort(path)
    try:
        cold = reopened.read_staged_operation(request)
        assert cold == created
        assert cold.root_intent == root
        assert reopened.reserve_staged_operation(request, "request-digest", root) == cold
        assert reopened.claim_operation_step(request, "request-digest", root.steps[0]).claimed
        assert not reopened.claim_operation_step(request, "request-digest", root.steps[0]).claimed
        assert reopened.read_operation_step(request, root.steps[0].step_id).revision == 1
    finally:
        reopened.close()


def test_legacy_reserve_semantics_stay_strict_and_cannot_mix_with_staged_rows(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, root = _request(), _root()
    ordinary_request = _request("ordinary")
    ordinary = _root(ordinary_request, operation_ref="ordinary-operation")
    try:
        stored = store.reserve_operation(ordinary_request, "request-digest", ordinary)
        assert store.reserve_operation(ordinary_request, "request-digest", ordinary) == stored
        with pytest.raises(GuaranteeUnavailableError):
            store.read_staged_operation(ordinary_request)
        with pytest.raises(IdentityMismatchError):
            store.reserve_operation(
                ordinary_request,
                "request-digest",
                _root(ordinary_request, operation_ref="changed-operation"),
            )

        _, _, staged = _reserve(store, request, root=root)
        expanded = OperationIntent.from_dict(json.loads(staged.operation.intent_json))
        for candidate in (root, expanded):
            with pytest.raises(IdentityMismatchError):
                store.reserve_operation(request, "request-digest", candidate)
        assert store.read_staged_operation(request) == staged
        assert store.read_operation(request) == staged.operation
    finally:
        store.close()


@pytest.mark.parametrize(
    "unfinished", ["pending", "possibly-dispatched", "unknown", "refused-step", "refused"]
)
def test_append_requires_every_root_step_concluded_and_nonterminal(tmp_path, unfinished):
    store = SqliteStorePort(tmp_path / f"{unfinished}.sqlite")
    request, root, before = _reserve(store)
    step = root.steps[0]
    try:
        if unfinished == "possibly-dispatched":
            store.claim_operation_step(request, "request-digest", step)
        elif unfinished == "unknown":
            claim = store.claim_operation_step(request, "request-digest", step)
            store.record_operation_step(
                request, "request-digest", step.step_id, step.input_digest,
                claim.step.revision, "unknown", {},
            )
        elif unfinished == "refused-step":
            claim = store.claim_operation_step(request, "request-digest", step)
            store.record_operation_step(
                request, "request-digest", step.step_id, step.input_digest,
                claim.step.revision, "refused", {"evidenceRef": "controlled-step-refusal"},
            )
        elif unfinished == "refused":
            current = store.read_operation(request)
            store.record_operation_outcome(
                request, "request-digest", current.revision, "refused",
                {"evidenceRef": "controlled-refusal"},
            )
        before = store.read_staged_operation(request)
        before_step = store.read_operation_step(request, step.step_id)
        with pytest.raises(UnknownResultError):
            _append(store, request, before)
        assert store.read_staged_operation(request) == before
        assert store.read_operation_step(request, step.step_id) == before_step
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == int(before_step is not None)
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


def test_append_is_one_shot_seal_and_preserves_root_recipe_facts(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, root, reserved = _reserve(store)
    try:
        with pytest.raises(IdentityMismatchError):
            store.claim_operation_step(request, "request-digest", _phase().steps[0])
        root_step_record = _conclude(store, request, root, root.steps[0])
        current = store.read_staged_operation(request)
        before_intent = current.operation.intent
        phase = _phase()
        sealed = _append(store, request, current, phase)

        assert sealed.sealed is True
        assert sealed.phase == phase
        assert sealed.operation.revision == current.operation.revision + 1
        after = sealed.operation.intent
        assert after.operation_ref == before_intent.operation_ref
        assert after.kind == before_intent.kind
        assert after.profile_snapshot_ref == before_intent.profile_snapshot_ref
        assert after.node_ref == before_intent.node_ref
        assert after.management_epoch == before_intent.management_epoch
        assert after.context_ref["directoryBindingRef"] == before_intent.context_ref["directoryBindingRef"]
        assert after.context_ref["rootFact"] == before_intent.context_ref["rootFact"]
        assert after.context_ref["invocationBindings"]["materials"] == before_intent.context_ref["invocationBindings"]["materials"]
        assert after.steps[:len(root.steps)] == root.steps
        assert after.steps[-len(phase.steps):] == phase.steps
        assert after.context_ref["materialReceiptRef"] == phase.context_facts["materialReceiptRef"]
        assert store.read_operation_step(request, root.steps[0].step_id) == root_step_record

        exact_replay = _append(
            store, request, reserved, phase,
            revision=reserved.operation.revision,
            intent_digest=_intent_digest(reserved),
        )
        assert exact_replay == sealed
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
        changed_same_id = _phase(context_facts={
            "materialReceiptRef": {"environmentNamespace": "env", "receiptId": "different"}
        })
        with pytest.raises(IdentityMismatchError):
            _append(store, request, sealed, changed_same_id)
        with pytest.raises(UnknownResultError):
            _append(store, request, sealed, _phase(phase_id="phase-two", step_id="later"))
        with pytest.raises(IdentityMismatchError):
            store.append_staged_operation_phase(
                request, "different-input", sealed.operation.revision,
                _intent_digest(sealed), phase,
            )
        assert store.read_staged_operation(request) == sealed
        expanded = sealed.operation.intent
        with pytest.raises(IdentityMismatchError):
            store.reserve_operation(request, "request-digest", root)
        with pytest.raises(IdentityMismatchError):
            store.reserve_operation(request, "request-digest", expanded)
        with pytest.raises(ValueError):
            store.append_staged_operation_phase(
                request,
                "request-digest",
                True,
                _intent_digest(reserved),
                phase,
            )

        assert store.claim_operation_step(request, "request-digest", phase.steps[0]).claimed
        current = store.read_staged_operation(request)
        assert current.sealed and current.phase == phase
        assert current.operation.intent.steps == after.steps
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 2
    finally:
        store.close()


def test_append_cas_refuses_stale_revision_or_intent_hash_without_mutation(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, root, reserved = _reserve(store)
    try:
        _conclude(store, request, root, root.steps[0])
        current = store.read_staged_operation(request)
        before = current
        with pytest.raises(OperationRevisionConflict):
            _append(store, request, current, revision=current.operation.revision - 1)
        with pytest.raises(OperationRevisionConflict):
            _append(store, request, current, intent_digest="0" * 64)
        with pytest.raises(ValueError):
            _append(store, request, current, revision=True)
        assert store.read_staged_operation(request) == before
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


def test_same_phase_concurrent_append_has_one_persisted_seal(tmp_path):
    path = tmp_path / "race.sqlite"
    left = SqliteStorePort(path, writer_token="staged-concurrent-fixture")
    right = SqliteStorePort(path, writer_token="staged-concurrent-fixture")
    request, root, reserved = _reserve(left)
    phase = _phase()
    try:
        _conclude(left, request, root, root.steps[0])
        before = left.read_staged_operation(request)
        revision, digest = before.operation.revision, _intent_digest(before)
        barrier = Barrier(2)

        def append(store):
            barrier.wait(timeout=5)
            return store.append_staged_operation_phase(
                request, "request-digest", revision, digest, phase
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(append, left)
            second = pool.submit(append, right)
            results = (first.result(timeout=10), second.result(timeout=10))
        assert results[0] == results[1]
        final = left.read_staged_operation(request)
        assert final == results[0]
        assert final.sealed and final.phase == phase
        assert len(final.operation.intent.steps) == 2
        assert left._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
    finally:
        left.close()
        right.close()

    reopened = SqliteStorePort(path)
    try:
        cold = reopened.read_staged_operation(request)
        assert cold == final
        assert cold.sealed and cold.phase == phase
        assert reopened.reserve_staged_operation(request, "request-digest", root) == cold
        assert _append(reopened, request, reserved, phase) == cold
        assert not reopened.claim_operation_step(request, "request-digest", root.steps[0]).claimed
        assert reopened._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
    finally:
        reopened.close()


def test_append_transaction_failure_rolls_back_all_staged_record_changes(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, root, _ = _reserve(store)
    try:
        _conclude(store, request, root, root.steps[0])
        before = store.read_staged_operation(request)
        before_row = tuple(store._conn.execute(
            "SELECT * FROM env_requests WHERE request_id=?", (request.request_id,)
        ).fetchone())
        before_domain_count = store._conn.execute(
            "SELECT COUNT(*) FROM env_domain_records"
        ).fetchone()[0]
        with store.transaction() as conn:
            conn.execute(
                "CREATE TRIGGER staged_append_abort BEFORE UPDATE OF staged_operation_json ON env_requests "
                "BEGIN SELECT RAISE(ABORT, 'controlled staged append failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            _append(store, request, before)
        after_row = tuple(store._conn.execute(
            "SELECT * FROM env_requests WHERE request_id=?", (request.request_id,)
        ).fetchone())
        assert after_row == before_row
        assert store.read_staged_operation(request) == before
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM env_domain_records").fetchone()[0] == before_domain_count
    finally:
        store.close()


def test_root_reservation_insert_failure_rolls_back_identity_domain_and_usage(tmp_path):
    store = SqliteStorePort(tmp_path / "state.sqlite")
    request, root = _request(), _root()
    writes = (DomainWrite(
        "fixture.root-facts", "root", 0,
        {"environmentNamespace": "env", "root": "controlled"},
    ),)
    usages = (_usage(request, root),)
    try:
        with store.transaction() as conn:
            conn.execute(
                "CREATE TRIGGER staged_reserve_abort BEFORE INSERT ON env_requests "
                "BEGIN SELECT RAISE(ABORT, 'controlled staged reserve failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            store.reserve_staged_operation(
                request, "request-digest", root, writes=writes, usages=usages
            )
        assert store.read_operation(request) is None
        assert store.read_staged_operation(request) is None
        assert store.read_domain("env", "core.operation-identities", root.operation_ref) is None
        assert store.read_domain("env", "fixture.root-facts", "root") is None
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
        with store.transaction() as conn:
            conn.execute("DROP TRIGGER staged_reserve_abort")
        recovered = store.reserve_staged_operation(
            request, "request-digest", root, writes=writes, usages=usages
        )
        assert recovered.root_intent == root
        assert store.read_domain("env", "core.operation-identities", root.operation_ref) is not None
        assert store.read_domain("env", "fixture.root-facts", "root") is not None
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("corruption", ["delete", "evidence"])
def test_sealed_reads_revalidate_concluded_root_step_evidence(tmp_path, corruption):
    store = SqliteStorePort(tmp_path / f"{corruption}.sqlite")
    request, root, _ = _reserve(store)
    try:
        _conclude(store, request, root, root.steps[0])
        before = store.read_staged_operation(request)
        _append(store, request, before)
        with store.transaction() as conn:
            if corruption == "delete":
                conn.execute(
                    "DELETE FROM env_request_steps WHERE environment=? AND principal=? "
                    "AND request_id=? AND step_id=?",
                    (request.environment_namespace, request.principal_scope,
                     request.request_id, root.steps[0].step_id),
                )
            else:
                conn.execute(
                    "UPDATE env_request_steps SET evidence_json=? WHERE environment=? AND principal=? "
                    "AND request_id=? AND step_id=?",
                    ('{"evidenceRef":"tampered"}', request.environment_namespace,
                     request.principal_scope, request.request_id, root.steps[0].step_id),
                )
        for read in (store.read_operation, store.read_staged_operation):
            with pytest.raises(GuaranteeUnavailableError):
                read(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.append_staged_operation_phase(
                request, "request-digest", before.operation.revision,
                _intent_digest(before), _phase(),
            )
    finally:
        store.close()


@pytest.mark.parametrize("current_step", ["root", "sealed-phase"])
def test_reads_and_claim_refuse_when_running_current_step_row_is_missing(tmp_path, current_step):
    store = SqliteStorePort(tmp_path / f"{current_step}.sqlite")
    request, root, _ = _reserve(store)
    if current_step == "root":
        tail = root.steps[0]
    else:
        _conclude(store, request, root, root.steps[0])
        sealed = _append(store, request, store.read_staged_operation(request))
        tail = sealed.phase.steps[0]
    try:
        assert store.claim_operation_step(request, "request-digest", tail).claimed
        with store.transaction() as conn:
            conn.execute(
                "DELETE FROM env_request_steps WHERE environment=? AND principal=? "
                "AND request_id=? AND step_id=?",
                (request.environment_namespace, request.principal_scope,
                 request.request_id, tail.step_id),
            )
        for read in (store.read_operation, store.read_staged_operation):
            with pytest.raises(GuaranteeUnavailableError):
                read(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(request, "request-digest", tail)
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == (
            0 if current_step == "root" else 1
        )
    finally:
        store.close()


def test_class_level_serialization_ignores_instance_to_dict_overrides(tmp_path):
    calls = []

    def forbidden_to_dict(self):
        calls.append(type(self).__name__)
        raise AssertionError("instance serializer override must not execute")

    request = _request()
    root = _root(request)
    root_step = root.steps[0]
    object.__setattr__(root, "to_dict", forbidden_to_dict.__get__(root, OperationIntent))
    object.__setattr__(root_step, "to_dict", forbidden_to_dict.__get__(root_step, StepIntent))
    phase = _phase()
    object.__setattr__(phase, "to_dict", forbidden_to_dict.__get__(phase, OperationRecipePhase))
    phase_step = phase.steps[0]
    object.__setattr__(phase_step, "to_dict", forbidden_to_dict.__get__(phase_step, StepIntent))
    store = SqliteStorePort(tmp_path / "state.sqlite")
    try:
        store.reserve_staged_operation(request, "request-digest", root)
        stored_root = store.read_staged_operation(request).root_intent
        assert stored_root.steps[0] is not root_step
        _conclude(store, request, stored_root, stored_root.steps[0])
        before = store.read_staged_operation(request)
        _append(store, request, before, phase)
        assert calls == []
        assert store.read_staged_operation(request).phase.steps[0] is not phase_step
        assert store.read_staged_operation(request).phase == _phase()
    finally:
        store.close()


@pytest.mark.parametrize("corruption", ["invalid-json", "version", "root", "phase", "noncanonical"])
def test_both_operation_reads_fail_closed_on_staged_metadata_corruption(tmp_path, corruption):
    store = SqliteStorePort(tmp_path / f"{corruption}.sqlite")
    request, root, _ = _reserve(store)
    try:
        raw = store._conn.execute(
            "SELECT staged_operation_json FROM env_requests WHERE request_id=?",
            (request.request_id,),
        ).fetchone()[0]
        value = json.loads(raw)
        if corruption == "invalid-json":
            corrupt = "{" 
        elif corruption == "version":
            value["contractVersion"] = "staged-operation/999"
            corrupt = safe_json(value)
        elif corruption == "root":
            value["rootIntent"]["operationRef"] = "other-operation"
            corrupt = safe_json(value)
        elif corruption == "phase":
            value["phase"] = {"phaseId": "missing-fields"}
            corrupt = safe_json(value)
        else:
            corrupt = json.dumps(value, sort_keys=True, indent=2)
        with store.transaction() as conn:
            conn.execute(
                "UPDATE env_requests SET staged_operation_json=? WHERE request_id=?",
                (corrupt, request.request_id),
            )
        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.read_staged_operation(request)
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
    finally:
        store.close()


def test_old_invocation_context_expires_but_new_query_verifies_same_old_claim(tmp_path):
    class Authority:
        issuer_ref = {"environmentNamespace": "env", "issuerId": "fixture-authority"}
        revision = "authority-rev-1"

        def authorize(self, request, actions, target_ref, delegation_ref):
            return InvocationGrant(
                principal_scope=request.principal_scope,
                delegation_ref=delegation_ref,
                actions=actions,
                target_ref=target_ref,
                authority_revision=self.revision,
                expires_at=100,
                issuer_ref=self.issuer_ref,
            )

        def revalidate(self, grant, request, actions, target_ref):
            return self.authorize(request, actions, target_ref, grant.delegation_ref)

    class CurrentState:
        def __init__(self, provider, target):
            self.provider, self.directory_ref = provider, DirectoryBindingRef(
                "env", "binding", 1, "sha256:" + "a" * 64
            )

        def inspect(self, request, provider_ref, context_ref, target_ref, action):
            return InvocationCurrentState(
                self.provider, True, 0, self.directory_ref, True, None, None
            )

    store = SqliteStorePort(tmp_path / "state.sqlite")
    request = _request()
    provider, target = _provider(), _target()
    root = _root(request, provider=provider)
    try:
        store.reserve_staged_operation(request, "request-digest", root)
        issuer = InvocationIssuer(
            store, Authority(), CurrentState(provider, target), clock=lambda: 50
        )
        old_context = issuer.issue(
            request, "request-digest", root.steps[0].step_id, "apply", target
        )
        old_claim = store.read_operation_step(request, root.steps[0].step_id)
        assert old_claim.outcome == "possibly-dispatched"
        issuer.verify_and_consume(
            old_context, "apply", provider, target, root.steps[0].input_digest
        )
        concluded = store.record_operation_step(
            request,
            "request-digest",
            root.steps[0].step_id,
            root.steps[0].input_digest,
            old_claim.revision,
            "concluded",
            {"evidenceRef": "controlled-root-conclusion"},
        )
        before_append = store.read_staged_operation(request)
        _append(store, request, before_append)

        with pytest.raises(InvocationAuthorityRefused):
            issuer.verify_continuation(
                old_context, "apply", provider, target, root.steps[0].input_digest
            )
        query = issuer.issue_query(request, "request-digest", root.steps[0].step_id)
        verified = issuer.verify_and_consume(
            query, "query", provider, target, root.steps[0].input_digest
        )
        assert verified["query"] is True
        assert store.read_operation_step(request, root.steps[0].step_id) == concluded
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 1
    finally:
        store.close()


def test_unsealed_publish_is_rejected_and_sealed_recipe_uses_original_publish_rules(tmp_path):
    store = SqliteStorePort(tmp_path / "publish.sqlite")
    request, root = _request(), _root()
    usage = _usage(request, root)
    store.reserve_staged_operation(request, "request-digest", root, usages=(usage,))
    try:
        _conclude(store, request, root, root.steps[0])
        current = store.read_staged_operation(request)
        before_usage = tuple(store._conn.execute("SELECT * FROM env_usages").fetchone())
        with pytest.raises(UnknownResultError):
            store.publish_operation(
                request,
                "request-digest",
                current.operation.revision,
                (root.steps[0].step_id,),
                (),
                (_usage_transfer(request, root),),
                {"nodeRef": dict(root.node_ref)},
            )
        assert tuple(store._conn.execute("SELECT * FROM env_usages").fetchone()) == before_usage
        assert store.read_staged_operation(request) == current

        sealed = _append(store, request, current)
        assert tuple(store._conn.execute("SELECT * FROM env_usages").fetchone()) == before_usage
        phase_step = sealed.phase.steps[0]
        _conclude(store, request, sealed.operation.intent, phase_step)
        after_steps = store.read_staged_operation(request)
        published = store.publish_operation(
            request,
            "request-digest",
            after_steps.operation.revision,
            tuple(step.step_id for step in after_steps.operation.intent.steps),
            (),
            (_usage_transfer(request, root),),
            {"nodeRef": dict(root.node_ref)},
        )
        assert published.status == "published"
        assert store.read_staged_operation(request).sealed is True
        with pytest.raises(UnknownResultError):
            _append(store, request, store.read_staged_operation(request), _phase(phase_id="later", step_id="later"))
    finally:
        store.close()
