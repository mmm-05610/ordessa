"""026 T006-06/T006-08 (test half): 数据根 writer 准入、效果 fence 与 unknown 不重发.

C2 ``contracts/recovery.md`` §效果fence与回退 fixes the rules pinned here at
the composed-Server layer:

* **one effectful writer per data root** — while runtime A (root R1) holds the
  data-root ownership lock, a second composition on R1 is refused with the
  existing ``DATA_ROOT_IN_USE`` error family. A paused-but-alive old writer is
  never silently joined by a second writer, and once the lock is released the
  same root opens again with the first writer's records intact (no dual write,
  no permanent poisoning);
* **effects fence** — activation/instantiate/config-apply/control-reply all
  count as external effects, so the wire methods that accept turns, publish
  assets, import account material and install provider artifacts must not
  answer after the round is stopped: a stopped round has no live provider and
  refuses typed (its rows are gone from the live registry and from discovery),
  never fabricating a success;
* **unknown is not a resend signal** — ``sendOutcome.query`` for a request id
  the Server never accepted answers the explicit ``unknown`` outcome (the
  not-found semantic), stays stable across repeated queries, mints no
  ``sessions.send`` dispatch claim and therefore never re-dispatches;
* **drift pin** — an unregistered method name keeps the frozen
  ``is not a wire/1 method`` typed refusal.

Every fixture is controlled and in-process: ``tmp_path`` data roots,
``fastapi.testclient.TestClient``, no model call, no network, no real data.

Slice note (T006-08 test half): the stopped-round refusal below is the
existing lifecycle behaviour (``ServerPluginHost.shutdown`` retires the
plugin rows). The I-slice started-gate is expected to keep this guarantee
typed; if it changes the family/message, this is the pin that must be
reconciled — no production file was touched for this test file.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ordessa_server.composition.runtime import build_runtime
from ordessa_interfaces.http import create_app
from ordessa_server_plugin_api.wire_errors import WireError
from ordessa_workspace.local_environment import LocalEnvironmentProvider
from ordessa_workspace.plugin import WorkspaceServerPlugin

from ordessa_server_plugin_api.wire_errors import FAMILIES

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
LIST_PARAMS = {"includeArchived": False}

#: The wire-visible external-effect categories of the C2 fence (T006-08):
#: core Profile creation, core node preparation, provider turn-application
#: and approval decision. Retired Agent submission/configuration rows are
#: asserted absent by the live registry fence. Plugin-layer
#: activation is covered where it lives (the plugin host lifecycle tests);
#: these rows are the ones a stopped round must stop answering.
EFFECT_METHODS = (
    "agents.profiles.create",         # core catalog mutation (unavailable without key)
    "agents.nodes.prepare",           # core assembly (unavailable without production ports)
    "modelProvider.beginTurnApplication",  # apply a turn against the provider
    "permissions.approvals.decide",   # decide an approval
)


def _post_wire(client: TestClient, token: str, method: str, params: dict,
               request_id: str = "t006-08"):
    return client.post(
        f"/wire/v1/{method}",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def _caller(runtime):
    return runtime.wire.identity_authority.authenticate("Bearer " + runtime.token)


def _workspace_runtime(root):
    """A controlled composition whose local Workspace surface really opens.

    ``execution_mode="native"`` means no sandbox probe and no machine
    connector is needed: the local provider answers from this process, so the
    record below is minted without any real environment.
    """
    return build_runtime(
        root,
        server_plugins=[WorkspaceServerPlugin()],
        local_workspace_provider=LocalEnvironmentProvider(execution_mode="native"),
    )


def _open_one_workspace(runtime, project):
    """A controlled idempotent operation: first open creates, replay reuses."""
    params = {
        "requestId": "t006-08-open-0001",
        "environment": {"kind": "local", "host": None, "user": None},
        "path": str(project),
    }
    opened = runtime.wire.dispatch("workspaces.open", params, caller=_caller(runtime))
    assert opened["created"] is True
    workspace_id = opened["workspace"]["id"]
    replay = runtime.wire.dispatch(
        "workspaces.open", dict(params, requestId="t006-08-open-0002"),
        caller=_caller(runtime))
    assert replay["created"] is False
    assert replay["workspace"]["id"] == workspace_id
    return workspace_id


def test_a_second_writer_is_refused_while_the_root_owner_holds_the_lock(tmp_path):
    """Positive (freeze admission): one effectful writer per data root.

    Runtime A owns root R1 and has already produced a controlled effect (one
    Workspace record, replayed idempotently by path). While R1's ownership
    lock is held — A makes no in-flight call, it is the "paused" writer — a
    second composition on R1 must be refused at the point the lock is taken
    (``build_runtime`` acquires the root ownership before any token, database
    or plugin work), so a second writer can never be assembled, let alone
    started. The refusal leaves A's record and lock untouched; after A stops,
    the same root opens cleanly and still holds exactly the one record — the
    released lock is not poisoned and no dual writer ever appended.
    """
    root = tmp_path / "data"
    runtime_a = _workspace_runtime(root)
    runtime_a.start()
    try:
        project = tmp_path / "project"
        project.mkdir()
        workspace_id = _open_one_workspace(runtime_a, project)

        with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
            _workspace_runtime(root)

        # The refused second writer changed nothing about the owner.
        assert runtime_a.started is True
        listed = runtime_a.wire.dispatch("workspaces.list", LIST_PARAMS, caller=_caller(runtime_a))
        assert [item["id"] for item in listed["items"]] == [workspace_id]
    finally:
        runtime_a.stop()
    assert runtime_a.started is False

    fresh = _workspace_runtime(root)
    fresh.start()
    try:
        listed = fresh.wire.dispatch("workspaces.list", LIST_PARAMS, caller=_caller(fresh))
        assert [item["id"] for item in listed["items"]] == [workspace_id]
    finally:
        fresh.stop()


def test_effect_methods_are_refused_typed_after_the_round_is_stopped(tmp_path):
    """Positive (effects fence): a stopped round answers no effect category.

    The five wire rows below are live before the stop (bound to their new
    domain owners, advertised in discovery) and gone after it: the registry
    lookup fails and dispatch raises the typed wire refusal for every one of
    them. The same refusal travels through the HTTP entry for a
    representative method, so neither entry can leak an effect after the
    round ended.
    """
    expected_owners = {
        "agents.profiles.create": "pacthold.agents",
        "agents.nodes.prepare": "pacthold.agents",
        "modelProvider.beginTurnApplication": "ordessa.model-provider",
        "permissions.approvals.decide": "permissions-backend",
    }
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert "ordessa.server-compat" not in runtime.plugin_host.active_ids()
        live_caps = {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}
        for method in EFFECT_METHODS:
            descriptor = runtime.wire._registry.lookup(method)
            assert descriptor is not None, method
            assert descriptor.owner == expected_owners[method], method
            assert method in live_caps, method

        runtime.stop()
        assert runtime.started is False
        assert runtime.plugin_host.active_ids() == ()
        assert {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]} == (
            {"server.hello"})

        for method in EFFECT_METHODS:
            assert runtime.wire._registry.lookup(method) is None, method
            with pytest.raises(WireError) as refused:
                runtime.wire.dispatch(method, {}, caller=_caller(runtime))
            assert refused.value.family in FAMILIES, method
            assert refused.value.family == "INVALID_REQUEST", method

        # The same typed refusal through the HTTP entry of the stopped runtime
        # (constructed WITHOUT a lifespan: start/stop are driven by hand, so
        # the client cannot restart the round mid-test).
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        answer = _post_wire(client, runtime.token, "agents.profiles.create", {})
        assert answer.status_code == 200, answer.text
        error = answer.json()["error"]
        assert error["code"] == "INVALID_REQUEST"
        assert "is not a wire/1 method" in error["message"]
    finally:
        runtime.stop()


def test_unknown_operation_read_stays_not_found_and_never_dispatches(tmp_path):
    """The `/3` metadata query is read-only for an absent operation identity."""
    runtime = build_runtime(tmp_path / "data")
    runtime.start()
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    operation_ref = "t006-08-never-created"
    try:
        params = {"operationRef": operation_ref}
        for _ in range(2):
            with pytest.raises(WireError) as refused:
                runtime.wire.dispatch("agents.operations.read", dict(params), caller=_caller(runtime))
            assert refused.value.family == "NOT_FOUND"

        answer = _post_wire(client, runtime.token, "agents.operations.read", dict(params))
        assert answer.status_code == 200, answer.text
        assert answer.json()["error"]["code"] == "NOT_FOUND"

        # No dispatch claim exists for the unknown key: the query is a read
        # and never re-sends the operation under the same or a fresh key.
        with runtime.database.read() as conn:
            claims = conn.execute(
                "SELECT COUNT(*) FROM server_idempotency WHERE scope='sessions.send'"
            ).fetchone()[0]
        assert claims == 0
    finally:
        runtime.stop()


def test_an_unregistered_method_keeps_the_frozen_typed_refusal(tmp_path):
    """Missing condition: an unknown method name is a typed refusal (drift pin).

    A method this composition never registered — before or after any round —
    must keep the frozen ``is not a wire/1 method`` answer through both the
    local and the HTTP entry, and must not appear in discovery. This pins the
    unknown-method floor the effect fence sits on: a started-gate change may
    re-word the stopped-round refusal, but it must not turn an unregistered
    name into a different family or a fabricated answer.
    """
    runtime = build_runtime(tmp_path / "data")
    runtime.start()
    try:
        method = "effects.fenceProbe"
        assert runtime.wire._registry.lookup(method) is None
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch(method, {}, caller=_caller(runtime))
        assert refused.value.family in FAMILIES
        assert refused.value.family == "INVALID_REQUEST"
        assert refused.value.message == f"{method} is not a wire/1 method"
        assert method not in {
            entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}

        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        answer = _post_wire(client, runtime.token, method, {})
        assert answer.status_code == 200, answer.text
        error = answer.json()["error"]
        assert error["code"] == "INVALID_REQUEST"
        assert error["message"] == f"{method} is not a wire/1 method"
    finally:
        runtime.stop()
