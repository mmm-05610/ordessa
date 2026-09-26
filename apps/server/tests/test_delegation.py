"""Order 65 C: the delegation service - roster, run, linkage, cancellation.

A fake execution port stands in for the room: it drives the child turn the way
the real backend does (dispatch → complete with a summary + usage), so the
service's rules are tested without a sandbox. The order's counterexamples:
unauthorized, unavailable child, depth, cycle, cross-family continuation,
over-fan-out, and the parent's roll-up/cancel linkage.
"""
from __future__ import annotations

import pytest

from ordessa_server.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.errors import ServerError
from ordessa_server.execution.delegation import DelegationService
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.profiles import ProfileRecords
from ordessa_server.profiles.subagents import DelegationError
from ordessa_server_compat.sessions import SessionRecords, SessionService
from ordessa_server.workspaces import WorkspaceRecords
from pacthold.storage import Database, ObjectStore


class FakeExecution:
    """Completes every accepted child turn with a summary and a usage fact."""

    def __init__(self, records, *, fail_code: str | None = None) -> None:
        self.records = records
        self.accepted: list[str] = []
        self.fail_code = fail_code

    def accept(self, turn_id: str) -> None:
        self.accepted.append(turn_id)
        row = self.records.get_turn_context(turn_id)
        session_id = row["session_id"]
        self.records.set_turn_dispatch(
            turn_id, work_id="w", execution_id="e", dispatch_id="d", state="running")
        self.records.append_turn_event(
            turn_id, "message.delta", {"text": f"summary of {turn_id}"})
        if self.fail_code:
            self.records.fail_turn(turn_id, self.fail_code)
            return
        self.records.complete_turn(
            turn_id, checkpoint_object_digest="sha256:a", checkpoint_native_id=f"native-{turn_id}",
            result_object_digest="sha256:r",
            usage={"inputTokens": 11, "outputTokens": 7, "totalTokens": 18},
            usage_source="fake")
        del session_id


def _pieces(tmp_path):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    execution = FakeExecution(records)
    # a-3 A-family rebuild: the fixture now accepts a real Turn through the
    # service route, which asserts the harness the same way production send
    # does - register the families the fixture Profiles declare.
    harnesses = HarnessRegistry()
    harnesses.register(HarnessDescriptor(
        "codex", credential_kind=None,
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    harnesses.register(HarnessDescriptor(
        "claude-code", credential_kind=None,
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    sessions = SessionService(records, idempotency, objects, harnesses=harnesses,
                              profiles=profiles, credentials=None, execution=execution)
    service = DelegationService(records=records, profiles=profiles, sessions=sessions,
                                execution=execution, objects=objects)
    return database, profiles, workspaces, records, sessions, execution, service


def _setup(tmp_path, *, parent_permissions=None):
    database, profiles, workspaces, records, sessions, execution, service = _pieces(tmp_path)
    objects = service.objects

    def config_for(harness: str) -> str:
        # A real published configuration object: every Profile in the product
        # has one, and the delegation path reads it to start the child turn
        # with the child's own controls.
        return objects.publish(
            f'{{"schema_version":1,"harness_type":"{harness}","configuration":{{}}}}'.encode()
        ).digest

    digest = config_for("codex")
    parent = profiles.create(key="p", request_digest="p", name="alpha", harness_type="codex",
                             config_digest=digest, credential_id=None)[1]
    child = profiles.create(key="c", request_digest="c", name="beta", harness_type="codex",
                            config_digest=digest, credential_id=None)[1]
    other = profiles.create(key="o", request_digest="o", name="gamma", harness_type="codex",
                            config_digest=digest, credential_id=None)[1]
    if parent_permissions is not None:
        preset, rules = parent_permissions
        profiles.set_permissions(
            profile_id=parent["profile_id"], preset=preset, rules=rules,
            expected_version=profiles.get(parent["profile_id"])["version"],
            key="pp", request_digest="pp")
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/workspace", connection_id="c")[1]
    session = sessions.create_session("parent-session", {
        "workspace_id": workspace["workspace_id"], "profile_id": parent["profile_id"]})[1]
    # A workspace for each callable Profile, so a fresh child session has
    # somewhere to run.
    for callable_profile in (child, other):
        sessions.create_session(f"seed-{callable_profile['profile_id']}", {
            "workspace_id": workspace["workspace_id"],
            "profile_id": callable_profile["profile_id"]})
    # a-3 gate-reds ruling (C 06:19/06:30Z) A-family rebuild: the parent Turn
    # is constructed through the acceptance route (SessionService.create_turn ->
    # publish effective configuration), like production, so the frozen object
    # carries the permissions section delegation narrows from. Returns the
    # real turn id; every former 'parent-turn' literal now uses it.
    _, parent_turn = sessions.create_turn(session["session_id"], "parent-key", {
        "text": "parent task",
        "expected_profile_revision": int(profiles.get(parent["profile_id"])["config_revision"]),
    })
    parent_turn_id = parent_turn["turn_id"]
    return (database, profiles, records, sessions, execution, service,
            parent, child, other, parent_turn_id)


def test_zero_grants_means_no_tools_and_no_run(tmp_path):
    _db, _profiles, _records, _sessions, _execution, service, parent, _child, _other, parent_turn_id = _setup(tmp_path)
    listing = service.list_for(parent_profile_id=parent["profile_id"])
    assert listing == {"tools": [], "roster": []}
    with pytest.raises(DelegationError) as refused:
        service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work", "prompt": "x"})
    assert refused.value.code == "SUBAGENT_NOT_AUTHORIZED"


def test_a_granted_run_completes_links_and_returns_the_bounded_summary(tmp_path):
    database, profiles, records, _sessions, execution, service, parent, child, _other, parent_turn_id = _setup(tmp_path)
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])

    listing = service.list_for(parent_profile_id=parent["profile_id"])
    assert [tool["name"] for tool in listing["tools"]] == ["list_subagents", "run_subagent"]
    assert [entry["name"] for entry in listing["roster"]] == ["beta"]

    result = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "Summarise the thing."})
    assert result["state"] == "completed"
    assert result["summary"].startswith("summary of turn_")
    assert result["task_id"].startswith("native-turn_")
    assert result["usage"] == {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18,
                               "usageSource": "fake"}
    # The child turn names the parent (attribution is one join away).
    with database.read() as conn:
        row = conn.execute("SELECT parent_turn_id FROM server_turns WHERE id=?",
                           (result["turnId"],)).fetchone()
    assert row["parent_turn_id"] == parent_turn_id
    # The ledger is what knows who is whose child (order 086 wires the stop).
    assert records.live_child_turn_ids(parent_turn_id) == []
    with database.transaction() as conn:
        conn.execute("UPDATE server_turns SET state='running' WHERE id=?", (result["turnId"],))
    assert records.live_child_turn_ids(parent_turn_id) == [result["turnId"]]
    assert execution.accepted == [parent_turn_id, result["turnId"]], (
        "a-3 rebuild: the fixture parent is now accepted through the "
        "service route too; the child is accepted exactly once after it")


def test_continuation_depends_on_family_and_unknown_handles_refuse(tmp_path):
    database, profiles, _records, _sessions, _execution, service, parent, child, other, parent_turn_id = _setup(tmp_path)
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=other["profile_id"])

    with pytest.raises(DelegationError) as unknown:
        service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work",
                               "prompt": "x", "task_id": "native-nope"})
    assert unknown.value.code == "SUBAGENT_TASK_UNKNOWN"

    # A handle from another family refuses rather than silently opening a new
    # session: create a claude-code session and hand its native id over.
    claude_digest = service.objects.publish(
        b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest
    claude = profiles.create(key="cl", request_digest="cl", name="claude-role",
                             harness_type="claude-code",
                             config_digest=claude_digest, credential_id=None)[1]
    workspace_id = service._shared_workspace_id(profiles.get(child["profile_id"]))
    foreign = service.sessions.create_session("foreign", {
        "workspace_id": workspace_id, "profile_id": claude["profile_id"]})[1]
    with database.transaction() as conn:
        conn.execute("UPDATE server_sessions SET checkpoint_native_id='native-foreign' "
                     "WHERE id=?", (foreign["session_id"],))
    with pytest.raises(DelegationError) as mismatch:
        service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work",
                               "prompt": "x", "task_id": "native-foreign"})
    assert mismatch.value.code == "SUBAGENT_TASK_FAMILY_MISMATCH"

    # Within the same family, the handle continues the same session.
    first = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                        arguments={"subagent": "beta", "description": "do some work",
                                   "prompt": "first"})
    second = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do more work",
                                    "prompt": "again", "task_id": first["task_id"]})
    assert second["resumed"] is True and second["sessionId"] == first["sessionId"]
    assert second["task_id"] != first["task_id"]  # each turn reports its own native id


def test_fan_out_refuses_and_the_caller_no_longer_reports_its_own_ancestry(tmp_path):
    """The per-turn bound stays; the chain parameter is gone (order 086).

    What replaced it is the ledger: `test_subagent_rule_liveness_086.py` drives
    the cycle rule through real child turns, because a chain a caller hands over
    says nothing about who is actually waiting - which is how 65's rule ended up
    written down and never live.
    """
    _db, profiles, _records, _sessions, _execution, service, parent, child, _other, parent_turn_id = _setup(tmp_path)
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])

    with pytest.raises(DelegationError) as fan_out:
        service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                    arguments={"subagent": "beta", "description": "do some work", "prompt": "x"},
                    calls_this_turn=4)
    assert fan_out.value.code == "SUBAGENT_TURNS_EXCEEDED"


def test_a_failed_child_returns_its_typed_code_not_raw_output(tmp_path):
    database, profiles, records, sessions, _execution, _service, parent, child, _other, parent_turn_id = _setup(tmp_path)
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    failing = FakeExecution(records, fail_code="TURN_FAILED_FOR_TEST")
    service = DelegationService(records=records, profiles=profiles,
                                sessions=SessionService(
                                    records, IdempotentRecords(database), ObjectStore(tmp_path / "data"),
                                    harnesses=None, profiles=profiles, credentials=None,
                                    execution=failing),
                                execution=failing, objects=ObjectStore(tmp_path / "data"))
    result = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x"})
    assert result["state"] == "failed" and result["errorCode"] == "TURN_FAILED_FOR_TEST"
    assert "summary" in result  # the bounded text, never a raw stdout dump
    del sessions


def test_the_delegation_endpoint_resolves_only_its_own_token(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        # An unknown token is a 404: the surface resolves tokens, not callers.
        unknown = client.post("/internal/delegation/not-a-token", json={"op": "list"})
        assert unknown.status_code == 404 and unknown.json()["error"] == "DELEGATION_TOKEN_UNKNOWN"

        profile = runtime.repository.profiles.create(
            key="p", request_digest="p", name="alpha", harness_type="codex",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest,
            credential_id=None)[1]
        runtime.delegation_tokens["token-1"] = {
            "turnId": "parent-turn", "profileId": profile["profile_id"],
        }
        listed = client.post("/internal/delegation/token-1", json={"op": "list"})
        assert listed.status_code == 200
        # Zero grants: no tools at all - the pair is not materialised.
        assert listed.json()["result"] == {"tools": [], "roster": []}
        refused = client.post("/internal/delegation/token-1", json={
            "op": "run", "arguments": {"subagent": "beta", "description": "do some work",
                                       "prompt": "x"}})
        assert refused.status_code == 409
        assert refused.json()["error"] == "SUBAGENT_NOT_AUTHORIZED"
        unknown_op = client.post("/internal/delegation/token-1", json={"op": "nope"})
        assert unknown_op.status_code == 400


def test_a_granted_parent_renders_the_bridge_entry_and_zero_grants_does_not(tmp_path):
    import json
    import shutil

    from fastapi.testclient import TestClient

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    REPO = __import__("pathlib").Path(__file__).resolve().parents[3]
    PLUGIN = REPO / "plugins"  / "harness"
    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = REPO / "tests" / "server" / "fixtures" / "home_probe_acp_peer.mjs"
    deployment = {"schemaVersion": 1, "harnesses": [{
        "id": "claude-code", "capabilityClaims": {"stream": True},
        "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
        "stateProjection": {"target": "/runtime/home/.claude"},
        "timeoutMs": 60_000}]}
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    try:
        (tmp_path / "project").mkdir(exist_ok=True)
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN,
            secret_store=MemorySecretStore(values={"locator_1": b"fake-key"}))
        runtime.start()
        runtime.repository.register_credential("credential_1", "api-key", "locator_1")
        parent = runtime.repository.profiles.create(
            key="p", request_digest="p", name="alpha", harness_type="claude-code",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest,
            credential_id="credential_1")[1]
        child = runtime.repository.profiles.create(
            key="c", request_digest="c", name="beta", harness_type="claude-code",
            config_digest=runtime.objects.publish(
                b'{"schema_version":1,"harness_type":"claude-code","configuration":{}}').digest,
            credential_id="credential_1")[1]

        with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
            token = runtime.token
            opened = client.post("/wire/v1/workspaces.open", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": "o", "method": "workspaces.open",
                "params": {"requestId": "bridge-open-1", "path": str(tmp_path / "project"),
                           "environment": {"kind": "local", "host": None, "user": None}},
            }).json()["result"]

            def send(request_id: str):
                return client.post("/wire/v1/sessions.createAndSend", headers={
                    "Authorization": f"Bearer {token}"}, json={
                    "jsonrpc": "2.0", "id": "s", "method": "sessions.createAndSend",
                    "params": {"requestId": request_id,
                               "workspaceId": opened["workspace"]["id"],
                               "profileId": parent["profile_id"], "overrides": [],
                               "message": {"text": "hello", "attachments": []}},
                }).json()["result"]

            import time
            first = send("bridge-turn-1")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                session = runtime.repository.get_session(first["session"]["id"])
                if session["turns"] and session["turns"][0]["state"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            role = next(item for item in (tmp_path / "server" / "profiles").iterdir()
                        if item.is_dir() and item.name != "_sessions")
            # 086 stage 1: this family's `mcpServers` slot is `.claude.json` -
            # settings.json is a file the CLI never reads for MCP servers.
            candidate = role / ".claude" / ".claude.json"
            rendered = (json.loads(candidate.read_text(encoding="utf-8"))
                        if candidate.is_file() else {})
            assert "agentbox-subagents" not in rendered.get("mcpServers", {}), \
                "zero grants must not materialise the bridge"

            runtime.repository.profiles.grant_subagent(
                parent_id=parent["profile_id"], child_id=child["profile_id"])
            second = send("bridge-turn-2")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                session = runtime.repository.get_session(second["session"]["id"])
                if session["turns"] and session["turns"][0]["state"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            # The second session's role directory holds its own `.claude.json`.
            role_dirs = [item for item in (tmp_path / "server" / "profiles").iterdir()
                         if item.is_dir() and item.name != "_sessions"]
            found = None
            for role in sorted(role_dirs, key=lambda item: item.stat().st_mtime, reverse=True):
                candidate = role / ".claude" / ".claude.json"
                if candidate.is_file():
                    document_value = json.loads(candidate.read_text(encoding="utf-8"))
                    if "agentbox-subagents" in document_value.get("mcpServers", {}):
                        found = document_value
                        break
            assert found is not None, "a granted parent must materialise the bridge"
            entry = found["mcpServers"]["agentbox-subagents"]
            assert entry["command"] == "/usr/bin/node"
            assert entry["args"][0].endswith("subagent-bridge.mjs")
            assert entry["env"]["AGENTBOX_BRIDGE_TOKEN"]
            assert any(
                grant["profileId"] == parent["profile_id"]
                for grant in runtime.delegation_tokens.values()
            ) or runtime.delegation_tokens, "a token is minted for the attempt"
    finally:
        runtime_module._sidecar_deployment_file = original_file
        del shutil


def test_the_grant_wire_face_lists_grants_and_callers(tmp_path):
    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server.transport.http import create_app

    runtime = build_runtime(tmp_path / "server")
    runtime.start()
    profiles = runtime.repository.profiles
    parent = profiles.create(key="p", request_digest="p", name="alpha", harness_type="codex",
                             config_digest="sha256:" + "0" * 64, credential_id=None)[1]
    child = profiles.create(key="c", request_digest="c", name="beta", harness_type="codex",
                            config_digest="sha256:" + "1" * 64, credential_id=None)[1]
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        token = runtime.token

        def call(method, params):
            return client.post(f"/wire/v1/{method}", headers={
                "Authorization": f"Bearer {token}"}, json={
                "jsonrpc": "2.0", "id": method, "method": method, "params": params,
            }).json()

        empty = call("profiles.subagentGrants", {"profileId": parent["profile_id"]})["result"]
        assert empty == {"subagentGrants": [], "callableBy": []}

        granted = call("profiles.grantSubagent", {
            "requestId": "grant-req-1", "profileId": parent["profile_id"],
            "childProfileId": child["profile_id"]})["result"]["grant"]
        assert granted["parentProfileId"] == parent["profile_id"]

        seen = call("profiles.subagentGrants", {"profileId": parent["profile_id"]})["result"]
        assert seen["subagentGrants"] == [{"childProfileId": child["profile_id"]}]
        # The child sees exactly one caller - the partition has both directions.
        reverse = call("profiles.subagentGrants", {"profileId": child["profile_id"]})["result"]
        assert reverse["callableBy"] == [{"parentProfileId": parent["profile_id"]}]

        # A cycle is refused at grant time, with the same code the service uses.
        cycle = call("profiles.grantSubagent", {
            "requestId": "grant-req-2", "profileId": child["profile_id"],
            "childProfileId": parent["profile_id"]})
        assert cycle["error"]["details"]["internalCode"] == "SUBAGENT_CYCLE"

        revoked = call("profiles.revokeSubagent", {
            "requestId": "grant-req-3", "profileId": parent["profile_id"],
            "childProfileId": child["profile_id"]})["result"]
        assert revoked["revoked"] is True
        assert call("profiles.subagentGrants", {
            "profileId": parent["profile_id"]})["result"]["subagentGrants"] == []

def test_the_parents_denials_narrow_the_child_and_its_own_allow_set_stands(tmp_path):
    """Order 65 §1b: the parent's `deny`s (its neutral limits) travel into the
    child's frozen posture; the child's own rules decide everything else."""
    import json

    # The parent is on `plan` (edit/bash/external_directory denied) and adds
    # its own deny on webfetch before its turn is accepted and frozen; the
    # child is on `default` with no rules.
    database, profiles, _records, _sessions, _execution, service, parent, child, _other, parent_turn_id = _setup(
        tmp_path, parent_permissions=("plan", [{"key": "webfetch", "action": "deny"}]))
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])

    result = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x"})
    with database.read() as conn:
        digest = conn.execute(
            "SELECT effective_config_object_digest FROM server_turns WHERE id=?",
            (result["turnId"],)).fetchone()[0]
    assert digest, "the child turn freezes its merged posture"
    frozen = json.loads(service.objects.read(digest))
    posture = frozen["permissions"]
    # The parent's denials travelled...
    assert posture["keys"]["edit"] == "deny"
    assert posture["keys"]["bash"] == "deny"
    assert posture["keys"]["webfetch"] == "deny"
    # ...and the child's own default still decides the rest (nothing widened).
    assert posture["keys"]["read"] == "ask"
    assert posture["inheritedFrom"] == parent["profile_id"]


def test_a_child_approval_is_mirrored_into_the_parent_turn(tmp_path):
    """Order 65: the subagent's `ask` rises into the parent as the same kind
    of interruption the parent already handles (same approval id)."""
    database, _profiles, records, _sessions, _execution, service, parent, child, _other, parent_turn_id = _setup(tmp_path)
    _profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    result = service.run(parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                         arguments={"subagent": "beta", "description": "do some work",
                                    "prompt": "x"}, )
    child_turn = result["turnId"]

    from ordessa_server.approvals import ApprovalRecords

    class _Port:
        def register_approval(self, approval_id, turn_id, request_id):
            return None

    backend = _Backend(records, ApprovalRecords(records.database, append_event=records._append_session_event))
    backend._native_event(child_turn, "approval.requested",
                          {"request": {"requestId": "req-1", "tool": "bash",
                                       "summary": "run a command"}}, _Port())
    with database.read() as conn:
        parent_session_id = conn.execute(
            "SELECT id FROM server_sessions WHERE profile_id=? ORDER BY rowid LIMIT 1",
            (parent["profile_id"],),
        ).fetchone()[0]
    parent_session = records.get_session(parent_session_id)
    mirrored = [event for event in parent_session["events"]
                if event["kind"] == "approval.requested"
                and event.get("turn_id") == parent_turn_id]
    assert mirrored, "the interruption reached the parent turn"
    assert mirrored[-1]["data"]["from_subagent"]["turnId"] == child_turn
    assert mirrored[-1]["data"]["approval_id"].startswith("approval_")

class _Backend:
    """The minimal backend surface the approval-mirror test needs."""

    def __init__(self, records, approvals) -> None:
        self.records = records
        self.approvals = approvals
        self._lock = __import__("threading").RLock()
        self._approval_ports = {}
        self.on_event = lambda *args, **kwargs: None
        self._message_parts = {}

    from ordessa_server.execution.sidecar_backend import SidecarExecutionBackend as _B

    _native_event = _B._native_event


def test_the_real_bridge_process_runs_a_child_turn_end_to_end(tmp_path, monkeypatch):
    """Order 65 C: the bridge, un-faked.

    A real `subagent-bridge.mjs` process speaks stdio MCP to this test, dials
    the Server's loopback delegation surface with an attempt token, and the
    delegated turn runs on the *real* local channel (bwrap + the fixture
    adapter) - so the summary this test reads back is one a genuine execution
    produced. Zero model calls: the fixture answers.
    """
    import json
    import os
    import shutil
    import subprocess
    import threading
    import time

    import uvicorn

    from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
    from ordessa_server.transport.http import create_app
    from pacthold.storage.secrets import MemorySecretStore

    import ordessa_server_compat.composition as runtime_module

    if shutil.which("bwrap") is None or shutil.which("node") is None:
        pytest.skip("bwrap and node are required")

    REPO = __import__("pathlib").Path(__file__).resolve().parents[3]
    PLUGIN = REPO / "plugins"  / "harness"
    peer_source = "tests/harness_remote/home_probe_acp_peer.mjs"
    peer_bytes = REPO / "tests" / "server" / "fixtures" / "home_probe_acp_peer.mjs"
    harness = "claude-code"
    deployment = {"schemaVersion": 1, "harnesses": [{
        "id": harness, "capabilityClaims": {"stream": True},
        "adapter": {"command": "/usr/bin/node", "args": [], "source": peer_source},
        "stateProjection": {"target": f"/runtime/home/.{harness}"},
        "timeoutMs": 60_000}]}
    original_file = runtime_module._sidecar_deployment_file

    def deployment_file(root, relative):
        if relative == peer_source:
            return peer_bytes.read_bytes()
        return original_file(root, relative)

    runtime_module._sidecar_deployment_file = deployment_file
    port = 18760
    monkeypatch.setenv("AGENT_BOX_HTTP_PORT", str(port))
    try:
        (tmp_path / "project").mkdir(exist_ok=True)
        document = tmp_path / "deployment.json"
        document.write_text(json.dumps(deployment), encoding="utf-8")
        runtime = build_runtime_from_sidecar_deployment(
            tmp_path / "server", document, plugin_root=PLUGIN,
            secret_store=MemorySecretStore(values={}))
        runtime.start()

        from ordessa_server.idempotency import IdempotentRecords
        from ordessa_server_compat.sessions import SessionService

        sessions = SessionService(
            runtime.repository.sessions, IdempotentRecords(runtime.database),
            runtime.objects, harnesses=runtime.harnesses,
            profiles=runtime.repository.profiles,
            credentials=runtime.repository.credentials, execution=runtime.execution)
        parent = runtime.repository.profiles.create(
            key="p", request_digest="p", name="alpha", harness_type=harness,
            config_digest=runtime.objects.publish(
                f'{{"schema_version":1,"harness_type":"{harness}","configuration":{{}}}}'.encode()
            ).digest, credential_id=None)[1]
        child = runtime.repository.profiles.create(
            key="c", request_digest="c", name="beta", harness_type=harness,
            config_digest=runtime.objects.publish(
                f'{{"schema_version":1,"harness_type":"{harness}","configuration":{{}}}}'.encode()
            ).digest, credential_id=None)[1]
        workspace = runtime.repository.workspaces.create(
            key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
            remote_path=str(tmp_path / "project"), connection_id="conn")[1]
        with runtime.database.transaction() as conn:
            conn.execute(
                "UPDATE server_workspaces SET env_kind='local', normalized_path=? WHERE id=?",
                (str(tmp_path / "project"), workspace["workspace_id"]),
            )
        sessions.create_session("child-seed", {
            "workspace_id": workspace["workspace_id"], "profile_id": child["profile_id"]})
        runtime.repository.profiles.grant_subagent(
            parent_id=parent["profile_id"], child_id=child["profile_id"])
        # Order 138: the bridge is invoked from a *live parent turn*, and placement is
        # scoped to that turn's workspace. The fabricated token id must therefore name a
        # real turn in the shared workspace (as production guarantees), not a phantom.
        parent_session = sessions.create_session("parent-e2e", {
            "workspace_id": workspace["workspace_id"], "profile_id": parent["profile_id"]})[1]
        with runtime.database.transaction() as conn:
            conn.execute(
                "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
                "native_generation,state,capture_state,cleanup_state,input_object_digest,"
                "created_at,updated_at) VALUES ('parent-turn-e2e',?,?,1,0,'running','pending',"
                "'pending','x','t','t')",
                (parent_session["session_id"], parent["profile_id"]))
        runtime.delegation_tokens["e2e-token"] = {
            "turnId": "parent-turn-e2e", "profileId": parent["profile_id"],
        }

        server = uvicorn.Server(uvicorn.Config(
            create_app(runtime), host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "the loopback server did not start"

        bridge = REPO / "plugins"  / "harness" / "runtime" / "subagent-bridge.mjs"
        process = subprocess.Popen(
            ["/usr/bin/node", str(bridge)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "AGENTBOX_BRIDGE_URL": f"http://127.0.0.1:{port}",
                 "AGENTBOX_BRIDGE_TOKEN": "e2e-token"},
            text=True,
        )

        def exchange(payload: dict) -> dict:
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            assert line, process.stderr.read()[:400]
            return json.loads(line)

        try:
            hello = exchange({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                              "params": {"protocolVersion": "2024-11-05"}})
            assert hello["result"]["serverInfo"]["name"] == "agentbox-subagents"
            tools = exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            names = [tool["name"] for tool in tools["result"]["tools"]]
            assert names == ["list_subagents", "run_subagent"]
            assert "beta" in tools["result"]["tools"][1]["description"]

            listed = exchange({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "list_subagents", "arguments": {}}})
            assert "beta" in listed["result"]["content"][0]["text"]

            ran = exchange({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "run_subagent", "arguments": {
                                "subagent": "beta", "description": "answer the question",
                                "prompt": "Say hello and return it."}}})
            payload = json.loads(ran["result"]["content"][0]["text"])
            assert payload["state"] == "completed", payload
            assert payload["summary"], "the child's bounded summary came back"
            assert payload["task_id"], "a continuable handle came back"

            # The child turn really ran through the local channel: its record
            # names the parent, and the summary is its own streamed text.
            with runtime.database.read() as conn:
                row = conn.execute(
                    "SELECT parent_turn_id,state FROM server_turns "
                    "WHERE parent_turn_id='parent-turn-e2e'").fetchone()
            assert row is not None and row["state"] == "completed"
        finally:
            process.kill()
            process.wait(timeout=5)
            server.should_exit = True
            thread.join(timeout=5)
    finally:
        runtime_module._sidecar_deployment_file = original_file


def test_two_subagent_calls_in_one_turn_both_complete_and_attribute(tmp_path):
    """Order 65 G8 (service level): the same message may fan out two calls;
    both complete, both are linked to the parent turn, and neither overwrites
    the other's record."""
    import threading

    database, profiles, records, _sessions, _execution, service, parent, child, other, parent_turn_id = _setup(tmp_path)
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=child["profile_id"])
    profiles.grant_subagent(parent_id=parent["profile_id"], child_id=other["profile_id"])

    results: dict[str, dict] = {}
    errors: list[str] = []

    def run(name: str) -> None:
        try:
            results[name] = service.run(
                parent_turn_id=parent_turn_id, parent_profile_id=parent["profile_id"],
                arguments={"subagent": name, "description": "do some work", "prompt": "x"})
        except BaseException as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")

    threads = [threading.Thread(target=run, args=(name,)) for name in ("beta", "gamma")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [], errors
    assert set(results) == {"beta", "gamma"}
    assert all(result["state"] == "completed" for result in results.values())
    turn_ids = {result["turnId"] for result in results.values()}
    assert len(turn_ids) == 2
    with database.read() as conn:
        linked = [
            row[0] for row in conn.execute(
                "SELECT id FROM server_turns WHERE parent_turn_id=? ORDER BY id",
                (parent_turn_id,)
            ).fetchall()
        ]
    assert sorted(turn_ids) == linked
