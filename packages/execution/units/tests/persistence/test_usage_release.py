"""Controlled Usage release seam: only active rows, exact holder, terminal.

Real temporary SQLite store. The unknown-row release case is the latent gap
this seam closes: before the guard, a concluded step could release a Usage
row in unknown state.
"""
from __future__ import annotations

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment.errors import IdentityMismatchError, UnknownResultError
from ordessa_execution_api.environment.operations import (
    OperationIntent, OperationRevisionConflict, StepIntent, UsageMutation,
    node_holder, operation_holder,
)
from ordessa_units.persistence.sqlite.store import SqliteUnitStore

PROVIDER = {"environmentNamespace": "env", "providerId": "codex", "generation": 1}
NODE = {"environmentNamespace": "env", "instanceId": "node-1", "generation": 1}
TARGET = {"environmentNamespace": "env", "targetId": "unit-1"}
NODE_HOLDER = node_holder("env", "node-1", 1)


def _request(name):
    return RequestKey("env", "principal", name)


def _intent(operation_ref, step_id, node=NODE):
    step = StepIntent(step_id, PROVIDER, "digest-" + step_id, operation_ref + "." + step_id, (), 0)
    return OperationIntent(operation_ref, "agent-test",
                           {"environmentNamespace": "env", "ref": "profile"},
                           {"environmentNamespace": "env", "ref": "context"},
                           (step,), node, 0)


def _reserve(store, request, digest, operation_ref, step_id, usages=()):
    intent = _intent(operation_ref, step_id)
    store.reserve_operation(request, digest, intent, usages=tuple(usages))
    step = intent.steps[0]
    assert store.claim_operation_step(request, digest, step).claimed
    return intent, step


def _published_usage(tmp_path, usage_id="usage.a", state="active"):
    """A published node-held Usage row (revision 2) for release tests."""
    store = SqliteUnitStore(tmp_path / "store.sqlite")
    request = _request("publish-1")
    owner = operation_holder(request, "op-1")
    hold = UsageMutation(usage_id, 0, None, owner, TARGET, ("use",), state)
    _reserve(store, request, "digest-1", "op-1", "prepare", usages=(hold,))
    if state == "active":
        step = store.read_operation_step(request, "prepare")
        store.record_operation_step(request, "digest-1", "prepare", "digest-prepare", step.revision,
                                    "concluded", {"evidenceRef": "sha256:one"})
        transfer = UsageMutation(usage_id, 1, owner, NODE_HOLDER, TARGET, ("use",), "active")
        operation = store.read_operation(request)
        store.publish_operation(request, "digest-1", operation.revision, ("prepare",), (), (transfer,),
                                {"nodeRef": NODE})
    return store


def _release_attempt(store, usage_id, holder, *, expected_revision=2, state="released",
                     payload=None, holder_mutation=None, expected_holder=None, request_name="release-1",
                     digest="digest-2"):
    request = _request(request_name)
    _reserve(store, request, digest, "op-" + request_name, "release")
    mutation = UsageMutation(usage_id, expected_revision,
                             expected_holder if expected_holder is not None else holder,
                             holder_mutation if holder_mutation is not None else holder,
                             TARGET, ("use",), state, payload if payload is not None else {})
    step = store.read_operation_step(request, "release")
    return store.record_operation_step(request, digest, "release", "digest-release", step.revision,
                                       "concluded", {"terminationRef": "sha256:x"},
                                       usages=(mutation,), release_holder=holder)


def test_unknown_usage_row_cannot_be_released_and_keeps_its_hold(tmp_path):
    store = SqliteUnitStore(tmp_path / "store.sqlite")
    request = _request("unknown-1")
    owner = operation_holder(request, "op-1")
    hold = UsageMutation("usage.u", 0, None, owner, TARGET, ("use",), "active")
    _reserve(store, request, "digest-1", "op-1", "prepare", usages=(hold,))
    turned = UsageMutation("usage.u", 1, owner, owner, TARGET, ("use",), "unknown")
    step = store.read_operation_step(request, "prepare")
    store.record_operation_step(request, "digest-1", "prepare", "digest-prepare", step.revision,
                                "unknown", {}, usages=(turned,))
    with pytest.raises(UnknownResultError, match="only an active Usage"):
        _release_attempt(store, "usage.u", owner, expected_revision=2,
                         request_name="release-unknown", digest="digest-unknown")
    rows = store.read_usages("env", owner)
    assert [(row["usageId"], row["state"]) for row in rows] == [("usage.u", "unknown")]


def test_release_requires_exact_release_holder_identity(tmp_path):
    store = _published_usage(tmp_path)
    other = node_holder("env", "node-2", 1)
    with pytest.raises(IdentityMismatchError, match="exact release holder"):
        _release_attempt(store, "usage.a", NODE_HOLDER, holder_mutation=other,
                         request_name="release-2a", digest="digest-2a")
    with pytest.raises(IdentityMismatchError, match="exact release holder"):
        _release_attempt(store, "usage.a", NODE_HOLDER, expected_holder=other,
                         request_name="release-2b", digest="digest-2b")
    with pytest.raises(OperationRevisionConflict):
        _release_attempt(store, "usage.a", NODE_HOLDER, expected_revision=99,
                         request_name="release-2c", digest="digest-2c")
    rows = store.read_usages("env", NODE_HOLDER)
    assert [row["state"] for row in rows] == ["active"]


def test_active_release_is_terminal_and_idempotent(tmp_path):
    store = _published_usage(tmp_path)
    result = _release_attempt(store, "usage.a", NODE_HOLDER, payload={"terminationEvidenceRef": "sha256:stop"})
    assert result.outcome == "concluded"
    rows = store.read_usages("env", NODE_HOLDER)
    assert [(row["state"], row["revision"]) for row in rows] == [("released", 3)]
    # identical replay of the same release is idempotent; rewritten history is not
    request = _request("release-3")
    _reserve(store, request, "digest-3", "op-3", "release")
    same = UsageMutation("usage.a", 3, NODE_HOLDER, NODE_HOLDER, TARGET, ("use",), "released",
                         {"terminationEvidenceRef": "sha256:stop"})
    step = store.read_operation_step(request, "release")
    store.record_operation_step(request, "digest-3", "release", "digest-release", step.revision,
                                "concluded", {"terminationRef": "sha256:x"},
                                usages=(same,), release_holder=NODE_HOLDER)
    rewritten = UsageMutation("usage.a", 3, NODE_HOLDER, NODE_HOLDER, TARGET, ("use",), "released",
                              {"terminationEvidenceRef": "sha256:other"})
    request = _request("release-3b")
    _reserve(store, request, "digest-3b", "op-3b", "release")
    step = store.read_operation_step(request, "release")
    with pytest.raises(IdentityMismatchError, match="history cannot be rewritten"):
        store.record_operation_step(request, "digest-3b", "release", "digest-release", step.revision,
                                    "concluded", {"terminationRef": "sha256:y"},
                                    usages=(rewritten,), release_holder=NODE_HOLDER)


def test_release_seam_requires_concluded_step_and_explicit_holder(tmp_path):
    store = _published_usage(tmp_path)
    request = _request("release-4")
    _reserve(store, request, "digest-4", "op-4", "release")
    mutation = UsageMutation("usage.a", 2, NODE_HOLDER, NODE_HOLDER, TARGET, ("use",), "released")
    step = store.read_operation_step(request, "release")
    with pytest.raises(ValueError, match="concluded step"):
        store.record_operation_step(request, "digest-4", "release", "digest-release", step.revision,
                                    "unknown", {}, usages=(mutation,), release_holder=NODE_HOLDER)
    with pytest.raises(ValueError, match="release holder"):
        store.record_operation_step(request, "digest-4", "release", "digest-release", step.revision,
                                    "concluded", {"terminationRef": "sha256:x"},
                                    usages=(mutation,), release_holder="node-holder-string")
    # a release step cannot mix in occupation changes
    mixed = UsageMutation("usage.a", 2, NODE_HOLDER, NODE_HOLDER, TARGET, ("use",), "active")
    with pytest.raises(IdentityMismatchError, match="only release"):
        store.record_operation_step(request, "digest-4", "release", "digest-release", step.revision,
                                    "concluded", {"terminationRef": "sha256:x"},
                                    usages=(mixed,), release_holder=NODE_HOLDER)


def test_released_mutation_under_unknown_outcome_is_refused(tmp_path):
    store = SqliteUnitStore(tmp_path / "store.sqlite")
    request = _request("unknown-2")
    owner = operation_holder(request, "op-1")
    hold = UsageMutation("usage.v", 0, None, owner, TARGET, ("use",), "active")
    _reserve(store, request, "digest-1", "op-1", "prepare", usages=(hold,))
    released = UsageMutation("usage.v", 1, owner, owner, TARGET, ("use",), "released")
    step = store.read_operation_step(request, "prepare")
    with pytest.raises(UnknownResultError, match="unknown evidence cannot release"):
        store.record_operation_step(request, "digest-1", "prepare", "digest-prepare", step.revision,
                                    "unknown", {}, usages=(released,))
    rows = store.read_usages("env", owner)
    assert [row["state"] for row in rows] == ["active"]


def test_read_usages_reports_holder_rows_for_cas_construction(tmp_path):
    store = _published_usage(tmp_path)
    rows = store.read_usages("env", NODE_HOLDER)
    assert len(rows) == 1
    row = rows[0]
    assert row["usageId"] == "usage.a" and row["state"] == "active" and row["revision"] == 2
    assert row["holderRef"]["kind"] == "node" and row["targetRef"] == TARGET
    assert row["rights"] == ["use"]
    assert store.read_usages("env", node_holder("env", "nobody", 1)) == ()
