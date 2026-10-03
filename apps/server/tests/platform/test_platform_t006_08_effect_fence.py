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

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server.wire.errors import WireError
from ordessa_workspace.local_environment import LocalEnvironmentProvider
from ordessa_workspace.plugin import WorkspaceServerPlugin

from server_plugin_api.wire_errors import FAMILIES

HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}
LIST_PARAMS = {"includeArchived": False}

#: The wire-visible external-effect categories of the C2 fence (T006-08):
#: turn acceptance, asset publication, account material import and provider
#: artifact installation. Plugin-layer activation is covered where it lives
#: (the plugin host lifecycle tests); these rows are the ones a stopped round
#: must stop answering.
EFFECT_METHODS = (
    "sessions.createAndSend",     # accept a turn (may instantiate/dispatch)
    "assets.publishSkill",        # publish asset content
    "assets.publishMcp",
    "assets.publishPlugin",
    "accounts.importAsset",       # import account material
    "providerArtifacts.install",  # install provider artifacts
)


def _post_wire(client: TestClient, token: str, method: str, params: dict,
               request_id: str = "t006-08"):
    return client.post(
        f"/wire/v1/{method}",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


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
    opened = runtime.wire.dispatch("workspaces.open", params)
    assert opened["created"] is True
    workspace_id = opened["workspace"]["id"]
    replay = runtime.wire.dispatch(
        "workspaces.open", dict(params, requestId="t006-08-open-0002"))
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
        listed = runtime_a.wire.dispatch("workspaces.list", LIST_PARAMS)
        assert [item["id"] for item in listed["items"]] == [workspace_id]
    finally:
        runtime_a.stop()
    assert runtime_a.started is False

    fresh = _workspace_runtime(root)
    fresh.start()
    try:
        listed = fresh.wire.dispatch("workspaces.list", LIST_PARAMS)
        assert [item["id"] for item in listed["items"]] == [workspace_id]
    finally:
        fresh.stop()


def test_effect_methods_are_refused_typed_after_the_round_is_stopped(tmp_path):
    """Positive (effects fence): a stopped round answers no effect category.

    The six wire rows below are live before the stop (bound to the compat
    plugin, advertised in discovery) and gone after it: the registry lookup
    fails and dispatch raises the typed wire refusal for every one of them.
    The same refusal travels through the HTTP entry for a representative
    method, so neither entry can leak an effect after the round ended.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert "ordessa.server-compat" in runtime.plugin_host.active_ids()
        live_caps = {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}
        for method in EFFECT_METHODS:
            descriptor = runtime.wire._registry.lookup(method)
            assert descriptor is not None, method
            assert descriptor.owner == "ordessa.server-compat", method
            assert method in live_caps, method

        runtime.stop()
        assert runtime.started is False
        assert runtime.plugin_host.active_ids() == ()
        assert {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]} == (
            {"server.hello"})

        for method in EFFECT_METHODS:
            assert runtime.wire._registry.lookup(method) is None, method
            with pytest.raises(WireError) as refused:
                runtime.wire.dispatch(method, {})
            assert refused.value.family in FAMILIES, method
            assert refused.value.family == "INVALID_REQUEST", method

        # The same typed refusal through the HTTP entry of the stopped runtime
        # (constructed WITHOUT a lifespan: start/stop are driven by hand, so
        # the client cannot restart the round mid-test).
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        answer = _post_wire(client, runtime.token, "sessions.createAndSend", {})
        assert answer.status_code == 200, answer.text
        error = answer.json()["error"]
        assert error["code"] == "INVALID_REQUEST"
        assert "is not a wire/1 method" in error["message"]
    finally:
        runtime.stop()


def test_unknown_request_id_queries_as_unknown_and_never_re_dispatches(tmp_path):
    """Counterexample (unknown is not a resend): explicit not-found, no claim.

    A request id this Server never accepted answers ``{"outcome": "unknown"}``
    — the not-found semantic, not an accepted identity: the answer carries no
    sessionId/executionId, repeated lookups (local and HTTP) stay identical,
    and looking it up mints no ``sessions.send`` dispatch claim, so nothing
    was re-dispatched and nothing became a success. (The accepted half —
    querying a genuinely accepted request id and getting its frozen identity
    back — needs the controlled execution fixture of
    ``apps/server/tests/test_wire_v1.py``; it lives there, not here.)
    """
    runtime = build_runtime(tmp_path / "data")
    runtime.start()
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    request_id = "t006-08-never-submitted"
    try:
        first = runtime.wire.dispatch("sendOutcome.query", {"requestId": request_id})
        second = runtime.wire.dispatch("sendOutcome.query", {"requestId": request_id})
        assert first == second == {"outcome": "unknown"}
        # Not a success shape and not a second identity.
        assert set(first) == {"outcome"}

        answer = _post_wire(client, runtime.token, "sendOutcome.query",
                            {"requestId": request_id})
        assert answer.status_code == 200, answer.text
        assert answer.json()["result"] == {"outcome": "unknown"}

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
            runtime.wire.dispatch(method, {})
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
