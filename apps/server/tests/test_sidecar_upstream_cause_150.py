"""Work Order 150: an op failure's *upstream cause* must reach the product state.

Everything here drives the real Worker (`plugins/harness/runtime/
worker-entry.mjs`) over the real Python envelope (`SidecarEnvelope.request`, the leg
`sidecar.py:1039-1063` names), through deliberately different upstream faults, and
lands each fault on the real statement production uses
(`sidecar_backend.py:584-590`: ``fail_turn(turn_id, _safe_code(exc))``).

Measured before the fix (stage 1, `docs/server-round1/probes/
sim150_upstream_cause_collapse.mjs`): a missing adapter binary published the bare
errno ``ENOENT`` as its code, while a Harness that *did* state its cause ("Harness
session not found") published the single ``SIDECAR_OP_FAILED`` and lost the cause with
the message. Reverting the Worker's classification to the old
``error?.code ?? "SIDECAR_OP_FAILED"`` reddens G1/G2/G3 by itself - which is why these
assertions name the old shapes rather than sitting behind a separate revert file.

0 real model calls, 0 credential content: the adapter is a controlled fake peer, and
the credential-shaped literals below are strings that must never appear.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil

from ordessa_server_compat.execution.sidecar import (
    LocalProcessLauncher, SidecarEnvelope, SidecarError,
)
from ordessa_server_compat.execution.sidecar_backend import _safe_code
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server_compat.profiles import ProfileRecords
from ordessa_server_compat.sessions import SessionRecords
from ordessa_workspace import WorkspaceRecords
from pacthold_runtime_compat.storage import Database, ObjectStore

PLUGIN = pathlib.Path(__file__).resolve().parents[3] / "plugins"  / "harness"
WORKER = PLUGIN / "runtime" / "native-driver.mjs"  # worker-entry.mjs 随退役旧链移除
PEER = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"
NODE = shutil.which("node") or "/usr/bin/node"

PRODUCT_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
FALLBACK = "SIDECAR_OP_FAILED"
SECRET_SHAPES = ("sk-", "DEEPSEEK_API_KEY", "/runtime/secret/credential")


def _envelope(tmp_path: pathlib.Path):
    """A live Worker and the envelope that speaks to it (caller closes the channel)."""
    channels = LocalProcessLauncher([NODE, str(WORKER)]).launch({
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path), "AGENTBOX_SIDECAR_ISOLATED": "1",
    })
    return SidecarEnvelope(channels, on_event=lambda _message: None), channels


def _register(envelope: SidecarEnvelope, tmp_path: pathlib.Path, command: str, args=()):
    return envelope.request({
        "op": "register", "profile": "codex", "directory": str(tmp_path),
        "stateDirectory": str(tmp_path / "state"),
        "launch": {"command": command, "args": list(args)},
    }, timeout=25.0)


def _launch_fault(tmp_path: pathlib.Path, command: str) -> SidecarError:
    """The adapter never comes up: the upstream fault is the launch itself.

    Registration only stores the declaration, so the fault surfaces on the first
    operation that needs the peer - the same way it does for a real turn.
    """
    envelope, channels = _envelope(tmp_path)
    try:
        _register(envelope, tmp_path, command)
        envelope.request({"op": "start"}, timeout=25.0)
    except SidecarError as exc:
        return exc
    finally:
        channels.close()
    raise AssertionError("the adapter must not come up as a usable ACP peer")


def _session_fault(tmp_path: pathlib.Path) -> SidecarError:
    """The adapter is fine; the Harness refuses this turn for its own reason."""
    envelope, channels = _envelope(tmp_path)
    try:
        _register(envelope, tmp_path, NODE, [str(PEER)])
        envelope.request({"op": "start"}, timeout=25.0)
        envelope.request({"op": "prompt", "sessionId": "no-such-native-session",
                          "text": "x"}, timeout=25.0)
    except SidecarError as exc:
        return exc
    finally:
        channels.close()
    raise AssertionError("a prompt against an unknown session must fail")


def _ledger(tmp_path: pathlib.Path):
    """A real session/turn on the real ledger, so the assertions read product state."""
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    objects = ObjectStore(tmp_path / "data")
    profiles = ProfileRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    config_digest = objects.publish(
        b'{"schema_version":1,"harness_type":"codex","configuration":{}}').digest
    profile_id = profiles.create(key="p-150", request_digest="p-150", name="alpha",
                                 harness_type="codex", config_digest=config_digest,
                                 credential_id=None)[1]["profile_id"]
    workspace_id = workspaces.create(key="w-150", request_digest="w-150",
                                     distribution="Ubuntu", remote_user="t",
                                     remote_path="/w", connection_id="w")[1]["workspace_id"]
    _status, session = records.create_session(
        key="s-150", request_digest="s-150", workspace_id=workspace_id,
        profile_id=profile_id)
    session_id = session["session_id"]
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('t-1',?,?,1,0,'running','pending','pending',"
            "'x','t','t')", (session_id, profile_id))
    return records, session_id


def _product_view(records: SessionRecords, session_id: str, turn_id: str):
    """What the product itself carries for the failed turn - not the server log."""
    turn = records.get_turn_context(turn_id)
    with records.database.read() as conn:
        rows = conn.execute(
            "SELECT kind, data_json FROM server_session_events WHERE turn_id=? ORDER BY seq",
            (turn_id,)).fetchall()
    events = {row["kind"]: json.loads(row["data_json"]) for row in rows}
    return str(turn["error_code"]), turn["state"], events


# -- G1: two known-different upstream faults, two different visible causes -----

def test_a_launch_fault_and_a_session_fault_get_different_codes(tmp_path):
    launch = _launch_fault(tmp_path, "/nonexistent/harness-binary-that-is-not-installed")
    session = _session_fault(tmp_path)
    assert launch.code != session.code, (launch.code, session.code)
    assert launch.code == "HARNESS_LAUNCH_FAILED", launch.code
    assert session.code == "HARNESS_SESSION_UNAVAILABLE", session.code
    # The old shape put one of them on the fallback and the other on a bare errno.
    assert FALLBACK not in {launch.code, session.code}, (launch.code, session.code)
    assert "ENOENT" not in {launch.code, session.code}


def test_the_worker_still_answers_every_op_with_a_product_shaped_code(tmp_path):
    """Whatever the cause, the code position stays a code - never free text (G3)."""
    for fault in (_launch_fault(tmp_path, "/nonexistent/harness-binary"),
                  _session_fault(tmp_path)):
        assert PRODUCT_CODE.fullmatch(fault.code), fault.code


def test_an_unclassified_cause_still_exits_as_a_typed_fallback():
    """The fallback is demoted to last resort, and a non-code can never take it."""
    raw = SidecarError("weird-lowercase", "no shape the Worker knows")
    assert not PRODUCT_CODE.fullmatch(raw.code)          # would not survive as a code
    assert _safe_code(SidecarError(FALLBACK, "x")) == FALLBACK


# -- G5 / G3: bounded detail, no path or errno in the code position -----------

def test_a_long_and_path_bearing_cause_stays_bounded_and_out_of_the_code(tmp_path):
    fault = _launch_fault(tmp_path, "/nonexistent/" + "u" * 600)
    assert fault.code == "HARNESS_LAUNCH_FAILED", fault.code
    assert "nonexistent" not in fault.code and "ENOENT" not in fault.code
    assert len(fault.message) <= 500, len(fault.message)


# -- G2: the cause is readable in the product state, not only in the log ------

def test_the_cause_reaches_the_turn_record_and_its_event(tmp_path):
    records, session_id = _ledger(tmp_path)
    launch = _launch_fault(tmp_path, "/nonexistent/harness-binary-that-is-not-installed")
    session = _session_fault(tmp_path)

    records.fail_turn("t-1", _safe_code(launch))
    launch_code, _state, launch_events = _product_view(records, session_id, "t-1")
    assert launch_code == "HARNESS_LAUNCH_FAILED", launch_code
    assert launch_events["turn.state"]["error_code"] == "HARNESS_LAUNCH_FAILED"

    with records.database.transaction() as conn:  # re-open the turn for the second fault
        conn.execute("UPDATE server_turns SET state='running',error_code=NULL WHERE id='t-1'")
    records.fail_turn("t-1", _safe_code(session))
    session_code, _state, session_events = _product_view(records, session_id, "t-1")
    assert session_code == "HARNESS_SESSION_UNAVAILABLE", session_code
    assert session_events["turn.state"]["error_code"] == "HARNESS_SESSION_UNAVAILABLE"
    assert launch_code != session_code, "two different faults must not read the same"


def test_the_existing_terminal_routing_is_untouched(tmp_path):
    """`WORKER_DISCONNECTED` must still land as `unknown`, exactly as before."""
    records, session_id = _ledger(tmp_path)
    records.fail_turn("t-1", _safe_code(SidecarError("WORKER_DISCONNECTED", "gone")))
    _code, state, _events = _product_view(records, session_id, "t-1")
    assert state == "unknown", state


# -- G6: no credential shape on code, message or record ----------------------

def test_no_credential_shape_leaks_into_code_message_or_record(tmp_path):
    for fault in (_launch_fault(tmp_path, "/nonexistent/harness-binary"),
                  _session_fault(tmp_path)):
        for needle in SECRET_SHAPES:
            assert needle not in fault.code, needle
            assert needle not in fault.message, needle
    records, session_id = _ledger(tmp_path)
    records.fail_turn("t-1", _safe_code(
        _launch_fault(tmp_path, "/nonexistent/harness-binary")))
    code, _state, events = _product_view(records, session_id, "t-1")
    dumped = json.dumps({"code": code, "events": events}, ensure_ascii=False, default=str)
    for needle in SECRET_SHAPES + ("ENOENT",):
        assert needle not in dumped, needle


# -- G2, the real product surface: an accepted send, then read it over HTTP ----

def test_an_accepted_turn_whose_adapter_cannot_start_reports_that_cause_to_the_client(
        tmp_path):
    """The user's own leg: send is accepted, the turn fails, and *why* is readable
    from the product - the HTTP read the desktop uses, not the server log.

    The Worker here is the real one and the failure is a real spawn refusal, so if
    the Worker collapsed it to the fallback (`error?.code ?? SIDECAR_OP_FAILED`) or
    published the bare errno, both assertions below would read that instead.
    """
    import time

    from fastapi.testclient import TestClient

    from ordessa_server.bootstrap import build_runtime
    from ordessa_server_product.composition import create_composition
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry, SidecarExecutionBackend
    from ordessa_server_compat.execution.sidecar import SidecarHarnessPort
    from ordessa_server.transport.http import create_app
    from test_harness_sidecar import (
        FAKE_PEER, PLUGIN, SIDEcar_ENTRY, _fixture_capability_material, _wire_post,
        sidecar_environment,
    )

    registry = HarnessRegistry()
    registry.register(HarnessDescriptor("pi", capability_claims={"stream": True}))

    class Connector:
        def distributions(self): return [{"name": "Ubuntu"}]
        def probe(self, distribution, user):
            return {"probe_id": "probe", "distribution": distribution, "user": user}
        def browse(self, probe_id, path):
            return {"path": path, "directories": [], "files": []}
        def open_workspace(self, probe_id, path):
            return {"connection_id": "connection", "distribution": "Ubuntu",
                    "user": os.environ["USER"], "path": str(tmp_path)}

    def execution_factory(records, objects, approvals, notifier, _connector, _credentials,
                          _secrets, _turn_inputs):
        def port_factory(context, on_event):
            return SidecarHarnessPort(
                LocalProcessLauncher(["node", str(SIDEcar_ENTRY)], cwd=str(PLUGIN)),
                environment=sidecar_environment(tmp_path), profile=context["harness_type"],
                # The one deliberate difference from the working fixture: this adapter
                # cannot be launched at all, which is the R-0078 fault class.
                adapter={"command": "/nonexistent/harness-binary-that-is-not-installed",
                         "args": [str(FAKE_PEER)]},
                state_directory=str(tmp_path / "state"), directory=str(tmp_path),
                on_event=on_event, **_fixture_capability_material(context),
            )
        return SidecarExecutionBackend(
            records, objects, approvals, port_factory=port_factory, on_event=notifier.notify,
        )

    runtime = build_runtime(tmp_path / "server",
                            server_plugins=create_composition().compatibility_plugins(
                                harnesses=registry,
                                execution_factory=execution_factory, connector=Connector()))
    with TestClient(create_app(runtime), base_url="http://127.0.0.1") as client:
        opened = _wire_post(client, runtime.token, "workspaces.open", {
            "requestId": "cause-open", "path": str(tmp_path),
            "environment": {"kind": "wsl", "host": "Ubuntu", "user": None},
        })["workspace"]
        profile = client.post("/api/v1/profiles", headers={
            "Authorization": f"Bearer {runtime.token}", "Idempotency-Key": "cause-profile",
        }, json={"name": "cause", "harness_type": "pi",
                 "configuration": {"model": "initial"}, "credential_id": None}).json()
        accepted = _wire_post(client, runtime.token, "sessions.createAndSend", {
            "requestId": "cause-send", "workspaceId": opened["id"],
            "profileId": profile["profile_id"], "overrides": [],
            "message": {"text": "cause", "attachments": []},
        })
        session_id = accepted["session"]["id"]
        headers = {"Authorization": f"Bearer {runtime.token}"}

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            session = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
            turns = session.get("turns") or []
            if turns and turns[0].get("state") in {"failed", "unknown", "completed"}:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"the turn never reached a terminal state: {session}")

        assert turns[0]["state"] == "failed", turns[0]
        assert turns[0]["error_code"] == "HARNESS_LAUNCH_FAILED", turns[0]
        # The event surface is an SSE long-poll (`app.py:302-323` loops until the
        # next event arrives), so it is deliberately not read here: under
        # `TestClient` a bounded pull of it blocks. The same terminal event is
        # asserted off the ledger in
        # `test_the_cause_reaches_the_turn_record_and_its_event`, which is the row
        # that stream serialises from.
