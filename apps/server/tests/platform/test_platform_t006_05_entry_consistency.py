"""026 T006-05 (test half): 本地/HTTP 对同一 controlled provider 的 dispatch 一致。

One composed Server, one dispatch truth: the local entry
(``runtime.wire.dispatch``) and the HTTP entry (``POST /wire/v1/{method}``)
must reach the SAME runtime instance, the same method registry and the same
capability table — a second parallel dispatch path would be an independent
activation surface (G006-1). Every fixture here is controlled and in-process:
``tmp_path`` data roots, ``fastapi.testclient.TestClient``, no model call, no
network and no real data.

Scenarios pinned by this file:

* positive — HTTP and local entries answer ``server.hello`` and the
  idempotent read ``workspaces.list`` with the same capability set, the same
  result structure and the same provider identity (the HTTP leg is observed
  going through THIS runtime's ``wire.dispatch`` object);
* positive — N repeated same-key idempotent reads keep a 1:1 relation between
  entry dispatches and registry-handler invocations (the wire-layer spy is
  compared against a registry-layer spy), so an entry never fans a read out
  into extra dispatches/port calls;
* counterexample — a resource reference minted by runtime A (different data
  root) is refused typed by runtime B through BOTH entries (``NOT_FOUND`` /
  ``WORKSPACE_NOT_FOUND``), while A keeps resolving it: identity is per
  runtime, not shared;
* missing condition — a runtime with no active plugin round (a never-started
  bare composition, exercised through BOTH the local and the HTTP entry, and
  a stopped default-product round) refuses business wire calls in the typed
  error family instead of answering a fabricated empty payload, and
  advertises no stale business capability.
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


def _post_wire(client: TestClient, token: str, method: str, params: dict,
               request_id: str = "t006-05"):
    return client.post(
        f"/wire/v1/{method}",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )


def _workspace_runtime(root):
    """A controlled composition whose local Workspace surface really opens.

    ``execution_mode="native"`` means no sandbox probe and no machine
    connector is needed: the local provider answers from this process, so the
    cross-runtime reference below is minted without any real environment.
    """
    return build_runtime(
        root,
        server_plugins=[WorkspaceServerPlugin()],
        local_workspace_provider=LocalEnvironmentProvider(execution_mode="native"),
    )


def test_http_and_local_entries_dispatch_the_same_runtime_and_capabilities(
        tmp_path, monkeypatch):
    """Positive: one runtime, two entries, one identity.

    The instance-level spy on ``runtime.wire.dispatch`` is the proof of
    identity: the HTTP leg must show up in the SAME counter as the local leg,
    so the transport cannot be serving a second composition. ``serverId`` and
    the whole hello result (capabilities included) must be byte-equal, and the
    read method must answer the same structure through both entries.
    """
    runtime = build_runtime(tmp_path / "data")
    seen: list[str] = []
    original_dispatch = runtime.wire.dispatch

    def counting_dispatch(method, params):
        seen.append(method)
        return original_dispatch(method, params)

    monkeypatch.setattr(runtime.wire, "dispatch", counting_dispatch)
    try:
        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            local_hello = runtime.wire.dispatch("server.hello", HELLO)
            local_list = runtime.wire.dispatch("workspaces.list", LIST_PARAMS)

            http_hello = _post_wire(client, runtime.token, "server.hello", HELLO).json()["result"]
            http_list = _post_wire(client, runtime.token, "workspaces.list", LIST_PARAMS).json()["result"]

            # Same provider identity: the HTTP leg went through this runtime's
            # dispatch object (a second wire would not be recorded here).
            assert seen == ["server.hello", "workspaces.list",
                            "server.hello", "workspaces.list"], seen
            assert runtime.wire._registry is runtime.plugin_host.methods

            # Same capability set and same answer structure.
            assert local_hello == http_hello
            assert local_hello["serverId"] == http_hello["serverId"]
            assert [entry["id"] for entry in local_hello["capabilities"]] == [
                entry["id"] for entry in http_hello["capabilities"]]
            assert len(local_hello["capabilities"]) > 1, "default composition is not bare"
            assert local_list == http_list == {"items": [], "nextCursor": None}
    finally:
        runtime.stop()
    assert runtime.started is False


def test_repeated_same_key_reads_dispatch_once_per_entry_and_hit_registry_once(
        tmp_path, monkeypatch):
    """Positive: N repeated idempotent reads, exact 1:1 dispatch accounting.

    The wire-layer spy (instance ``dispatch``) and the registry-layer spy (the
    live descriptor's handler) must advance together by exactly one per
    request, alternating local and HTTP entries. A repeated same-key read that
    re-entered the port on the way or dispatched twice per HTTP request would
    break the equality; the exact deltas keep the assertion non-vacuous.
    """
    runtime = build_runtime(tmp_path / "data")
    descriptor = runtime.wire._registry.lookup("workspaces.list")
    assert descriptor is not None and descriptor.owner == "ordessa.workspace"
    original_handler = descriptor.handler
    original_dispatch = runtime.wire.dispatch
    counts = {"wire": 0, "registry": 0}

    def counting_dispatch(method, params):
        counts["wire"] += 1
        return original_dispatch(method, params)

    def counting_handler(params):
        counts["registry"] += 1
        return original_handler(params)

    monkeypatch.setattr(runtime.wire, "dispatch", counting_dispatch)
    runtime.start()
    # The descriptor is frozen; the sanctioned live-table primitive rebinds
    # the row, and the finally below puts the original handler back before the
    # round stops (TestClient runs without a lifespan here, the start/stop is
    # driven by hand so the restore cannot race the plugin teardown).
    runtime.wire.replace_handler("workspaces.list", counting_handler)
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    baseline = dict(counts)
    results = []
    try:
        for index in range(4):
            if index % 2:
                body = _post_wire(client, runtime.token, "workspaces.list",
                                  LIST_PARAMS, request_id=f"t006-05-{index}")
                results.append(body.json()["result"])
            else:
                results.append(runtime.wire.dispatch("workspaces.list", LIST_PARAMS))
    finally:
        delta = {name: counts[name] - baseline[name] for name in counts}
        runtime.wire.replace_handler("workspaces.list", original_handler)
        runtime.stop()

    assert delta == {"wire": 4, "registry": 4}, delta
    assert all(result == {"items": [], "nextCursor": None} for result in results)
    assert all(result == results[0] for result in results)


def test_cross_runtime_reference_is_refused_typed_through_both_entries(tmp_path):
    """Counterexample: A's resource reference used against B is NOT_FOUND.

    Two runtimes, two data roots, same controlled provider code. Runtime A
    mints a real Workspace record; its identifier is then driven into runtime
    B through the local entry AND the HTTP entry. Both must answer the same
    typed refusal, and B's own store must stay empty while A still resolves
    the reference — identity is not transferable between runtimes.
    """
    runtime_a = _workspace_runtime(tmp_path / "a")
    runtime_b = _workspace_runtime(tmp_path / "b")
    runtime_a.start()
    runtime_b.start()
    try:
        project = tmp_path / "project"
        project.mkdir()
        opened = runtime_a.wire.dispatch("workspaces.open", {
            "requestId": "req-open-0001",
            "environment": {"kind": "local", "host": None, "user": None},
            "path": str(project),
        })
        workspace_id = opened["workspace"]["id"]
        assert runtime_a.wire.dispatch("workspaces.list", LIST_PARAMS)["items"][0]["id"] == workspace_id

        foreign = {"requestId": "req-cross-0001", "workspaceId": workspace_id}

        with pytest.raises(WireError) as refused:
            runtime_b.wire.dispatch("workspaces.gitStatus", foreign)
        assert refused.value.family in FAMILIES
        assert refused.value.family == "NOT_FOUND"
        assert refused.value.details.get("internalCode") == "WORKSPACE_NOT_FOUND"

        with TestClient(create_app(runtime_b), base_url="http://127.0.0.1") as client:
            answer = _post_wire(client, runtime_b.token, "workspaces.gitStatus", foreign)
            assert answer.status_code == 200, answer.text
            error = answer.json()["error"]
            assert error["code"] == "NOT_FOUND"
            assert error["details"]["internalCode"] == "WORKSPACE_NOT_FOUND"
            # ...and it is not just "B has no workspaces": the same entry
            # answers B's own read, which is empty and must stay that way.
            assert runtime_b.wire.dispatch("workspaces.list", LIST_PARAMS) == {
                "items": [], "nextCursor": None}

        # The refusal changed nothing about the reference's real owner.
        assert runtime_a.wire.dispatch("workspaces.list", LIST_PARAMS)["items"][0]["id"] == workspace_id
    finally:
        runtime_a.stop()
        runtime_b.stop()


def test_unstarted_bare_runtime_refuses_business_methods_typed_not_empty(tmp_path):
    """Missing condition (never started): no active round, no empty answers.

    The bare composition is built and never started. A method this
    composition does not carry must be refused in the typed error family with
    the explicit unknown-method message — a fabricated ``{"items": []}``
    would be indistinguishable from an honest empty read. Discovery stays
    honest too: only the host row is advertised.
    """
    runtime = build_runtime(tmp_path / "data", server_plugins=[])
    try:
        assert runtime.started is False
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch("workspaces.list", LIST_PARAMS)
        assert refused.value.family in FAMILIES
        assert refused.value.family == "INVALID_REQUEST"
        assert "is not a wire/1 method" in refused.value.message
        # The same refusal through the HTTP entry of the never-started runtime:
        # TestClient runs WITHOUT a lifespan here, so start() is never called.
        client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
        answer = _post_wire(client, runtime.token, "workspaces.list", LIST_PARAMS)
        assert answer.status_code == 200, answer.text
        error = answer.json()["error"]
        assert error["code"] == "INVALID_REQUEST"
        assert "is not a wire/1 method" in error["message"]
        assert runtime.started is False
        capabilities = {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}
        assert capabilities == {"server.hello"}
    finally:
        runtime.stop()


def test_a_stopped_round_refuses_business_methods_typed_not_empty(tmp_path):
    """Missing condition (round ended): a stopped runtime has no live provider.

    After ``start()`` → ``stop()`` the default composition holds no active
    plugin round. Business calls must refuse typed and discovery must stop
    advertising the business rows — no empty payload can leak out of the
    disposed round.
    """
    runtime = build_runtime(tmp_path / "data")
    try:
        runtime.start()
        assert runtime.plugin_host.active_ids()
        # The same call answers while the round is live, so the refusal below
        # is the lifecycle change, not a permanently unknown method.
        assert runtime.wire.dispatch("workspaces.list", LIST_PARAMS) == {
            "items": [], "nextCursor": None}
        runtime.stop()
        assert runtime.started is False
        assert runtime.plugin_host.active_ids() == ()
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch("workspaces.list", LIST_PARAMS)
        assert refused.value.family in FAMILIES
        assert refused.value.family == "INVALID_REQUEST"
        assert "is not a wire/1 method" in refused.value.message
        capabilities = {entry["id"] for entry in runtime.wire.hello(HELLO)["capabilities"]}
        assert capabilities == {"server.hello"}
    finally:
        runtime.stop()
