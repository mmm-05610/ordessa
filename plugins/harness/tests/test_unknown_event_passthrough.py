"""T007-06 verification half: controlled-peer ``/workflow`` and unknown events.

Contract: ``specs/026-open-environment-migration/contracts/lifecycle-evidence.md``
§SDK真实穿透与样例 — an unknown payload summary must travel
native peer → Harness → Server → Desktop connector/SDK → surface outlet, must
not be re-fed around the SDK, and must keep a generic outlet before any
destructive filtering.  Order 007 T007-06 adds the bounded/no-terminal-state
duty: a controlled peer supports ``/workflow``/unknown events/native control
confirmation — original bytes within bounds, a trusted control consumed once,
and no new core command API.

What this module measures on the Python seam (registry/channel relay):

* positive — a real controlled peer's unknown ``sessionUpdate`` kind reaches
  the generic relay outlet verbatim, once, is never classified as an approval,
  and never writes a terminal run state;
* positive — a non-standard ``/workflow`` command travels the native command
  channel as prompt text, byte-identical, with the peer's own answer relayed
  back (no Core command whitelist exists on this path);
* negative — the same unknown event delivered repeatedly changes no concluded
  state and triggers no auto-resend/ack; a peer request with no answer gets no
  fabricated reply;
* missing condition — with no surface consumer attached the event is dropped
  (no relay buffer) and no state/thread crashes.

REGISTERED UNKNOWN (budget gap): the relay (``_Channel.deliver`` →
``NDJSONTransport`` → access entry) has no explicit per-event size or count
budget; the only bounds are the identity/evidence caps (``_native_sessions``
128, ``_seen_request_ids`` 4096, ``_configuration_queries`` 16) that unknown
events never touch.  This module therefore pins "relayed verbatim, no terminal
state, no state growth" and does not assert a numeric event budget.

The peer fixture is the allowlisted controlled peer
(``tests/integration/acp_orchestration/fixtures/bidirectional_acp_peer.mjs``,
content digest pinned by ``plugins/harness/runtime/controlled-peers.mjs``), so
the positive legs run through the real access entry, not a re-fed fixture.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from ordessa_harness.server_acp.access_entry import AccessEntryTransport
from ordessa_harness.server_acp.registry import AcpChannelRegistry

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins/harness/runtime/access-entry.mjs"
PEER = ROOT / "tests/integration/acp_orchestration/fixtures/bidirectional_acp_peer.mjs"


class Records:
    """The ledger stub the registry write path expects (same shape as sibling tests)."""

    def __init__(self) -> None:
        self.sessions = 0
        self.turns = 0
        self.finished: list[tuple[str, dict]] = []
        self.failed: list[tuple[str, Any]] = []

    def create_session(self, **_kwargs):
        self.sessions += 1
        return "accepted", {"session_id": f"ledger-session-{self.sessions}"}

    def create_turn(self, **_kwargs):
        self.turns += 1
        return True, "accepted", {"turn_id": f"execution-{self.turns}"}

    def finish_cancelled(self, execution_id, **_kwargs):
        self.finished.append((execution_id, dict(_kwargs)))

    def fail_turn(self, execution_id, code=None, **_kwargs):
        self.failed.append((execution_id, code))


class Profiles:
    def get(self, _profile_id):
        return {"config_revision": 1, "config_object_digest": "sha256:profile"}


class ImmediateLoop:
    """Schedules like the socket loop but runs immediately on the reader thread."""

    def call_soon_threadsafe(self, callback, item):
        callback(item)


def _wait_until(produce: Callable[[], Any], *, timeout: float = 15.0, message: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = produce()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {message}")


def _peer_rows(log_base: str) -> list[dict]:
    """Every frame the controlled peer recorded, across per-pid log files."""
    rows: list[dict] = []
    for path in sorted(glob.glob(log_base + ".*")):
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _frames(lines: list[str]) -> list[dict]:
    frames = []
    for line in lines:
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            frames.append(json.loads(text))
        except ValueError:
            continue
    return frames


def _response_for(lines: list[str], request_id: Any) -> dict | None:
    for frame in _frames(lines):
        if frame.get("id") == request_id and ("result" in frame or "error" in frame):
            return frame
    return None


def _session_new(channel, cwd: Path, request_id: str = "t706-new") -> str:
    channel.transport.send_line(json.dumps({
        "jsonrpc": "2.0", "id": request_id, "method": "session/new",
        "params": {"cwd": str(cwd), "mcpServers": []},
    }))
    return request_id


def _prompt(channel, native_id: str, text: str, request_id: str = "t706-prompt") -> str:
    channel.transport.send_line(json.dumps({
        "jsonrpc": "2.0", "id": request_id, "method": "session/prompt",
        "params": {"sessionId": native_id, "prompt": [{"type": "text", "text": text}]},
    }))
    return request_id


def _real_peer_rig(tmp_path: Path):
    """Registry + real allowlisted controlled peer + subscriber attached before traffic."""
    node = shutil.which("node")
    assert node is not None, "node is required to launch the controlled peer"
    log_base = str(tmp_path / "peer-log")
    records = Records()
    relayed: list[str] = []

    def launch(*, harness_id, cwd, on_line, on_exit, **_kwargs):
        return AccessEntryTransport(
            node=node, entry=str(ENTRY), harness_id=harness_id, cwd=cwd,
            adapter={"command": node, "args": [str(PEER)]},
            on_line=on_line, on_exit=on_exit,
            environment={**os.environ, "HD003_LOG": log_base},
            controlled_test_peer=True,
        ).start()

    registry = AcpChannelRegistry(session_records=records, profile_records=Profiles(), launch=launch)
    opened = registry.acquire(harness_id="pi", workspace_id="ws", profile_id="profile",
                              cwd=str(tmp_path))
    channel = registry.get(opened["connectionId"])
    assert channel is not None
    # The generic relay outlet: exactly what a desktop socket consumer would receive.
    channel.attach(ImmediateLoop(), relayed.append)
    return registry, opened, channel, records, relayed, log_base


def _fake_peer_rig(tmp_path: Path):
    """Registry over an in-process transport so line delivery is fully deterministic."""
    sent: list[str] = []
    callbacks: list[Callable[[str], None]] = []

    class Transport:
        def send_line(self, line: str) -> None:
            sent.append(line)

        def terminate(self) -> None:
            pass

    def launch(*, on_line, **_kwargs):
        callbacks.append(on_line)
        return Transport()

    records = Records()
    registry = AcpChannelRegistry(session_records=records, profile_records=Profiles(), launch=launch)
    opened = registry.acquire(harness_id="pi", workspace_id="ws", profile_id="profile",
                              cwd=str(tmp_path))
    channel = registry.get(opened["connectionId"])
    assert channel is not None
    return registry, opened, channel, records, sent, callbacks


def _unknown_update_line(session_id: str, payload: dict | None = None) -> str:
    return json.dumps({
        "jsonrpc": "2.0", "method": "session/update",
        "params": {"sessionId": session_id,
                   "update": {"sessionUpdate": "vendor_extension_update",
                              "payload": payload if payload is not None else {"keep": "me"}}},
    })


# -- positive: unknown event, bounded relay, no verdict -----------------------


def test_unknown_update_reaches_the_generic_outlet_once_and_writes_no_verdict(tmp_path):
    registry, opened, channel, records, relayed, log_base = _real_peer_rig(tmp_path)
    try:
        request_id = _session_new(channel, tmp_path)
        native = _wait_until(lambda: _response_for(relayed, request_id), message="session/new answer")
        native_id = native["result"]["sessionId"]

        _prompt(channel, native_id, "scenario:custom-update")
        unknown = _wait_until(
            lambda: [frame for frame in _frames(relayed)
                     if frame.get("method") == "session/update"
                     and frame.get("params", {}).get("update", {}).get("sessionUpdate") == "hd003_extension"],
            message="unknown sessionUpdate on the relay outlet")

        # (a) verbatim on the generic outlet, exactly once, still a notification.
        assert len(unknown) == 1, unknown
        assert unknown[0]["params"]["update"]["payload"] == {"keep": "me"}
        assert "id" not in unknown[0], "an unknown event is not an approval request or a reply"
        assert not any(frame.get("method") == "session/request_permission" for frame in _frames(relayed)), \
            "the unknown event must never be projected as an approval"
        peer_sent = [row for row in _peer_rows(log_base)
                     if row.get("dir") == "send" and row.get("frame", {}).get("method") == "session/update"
                     and row["frame"].get("params", {}).get("update", {}).get("sessionUpdate") == "hd003_extension"]
        assert len(peer_sent) == 1, "the native peer emitted the unknown update once; the relay must not duplicate it"
        assert [row["frame"]["params"]["update"]["payload"] for row in peer_sent] == [{"keep": "me"}]

        # (b) no terminal judgment came from the unknown event: the ledger was never ended and the
        # channel still owns its run.
        assert records.finished == [] and records.failed == []
        assert channel.ended is False
        assert registry.get(opened["connectionId"]) is channel
    finally:
        assert registry.release(opened["connectionId"])["released"] is True


def test_unknown_event_writes_no_per_session_state(tmp_path):
    """Unknown arrivals create no observation and no ledger transition, repeated or not."""
    registry, opened, channel, records, sent, callbacks = _fake_peer_rig(tmp_path)
    try:
        channel.transport.send_line(json.dumps({
            "jsonrpc": "2.0", "id": "new-1", "method": "session/new", "params": {"cwd": str(tmp_path)}}))
        callbacks[0](json.dumps({"jsonrpc": "2.0", "id": "new-1", "result": {"sessionId": "native-1"}}))
        observation = registry.native_session_observation(opened["connectionId"], "native-1")
        assert observation is not None

        relayed: list[str] = []
        channel.attach(ImmediateLoop(), relayed.append)
        before = list(sent)
        for index in range(64):
            callbacks[0](_unknown_update_line("native-1", {"n": index}))

        # No per-event state is minted by unknown traffic.
        assert registry.native_session_observation(opened["connectionId"], "native-1") is observation
        assert registry.native_session_observation(opened["connectionId"], "vendor_extension_update") is None
        assert records.finished == [] and records.failed == []
        assert channel.ended is False
        # Nothing is written back to the native side (no ack, no resend) for unknown traffic.
        assert sent == before
        # Every arrival is still relayed verbatim: the relay neither fuses nor drops subscribed events.
        assert len(relayed) == 64
        assert all(json.loads(line)["method"] == "session/update" for line in relayed)
    finally:
        registry.stop_all()


# -- positive: /workflow native command passthrough ---------------------------


def test_workflow_command_passes_the_native_channel_verbatim(tmp_path):
    """R03: a command the upstream carries needs no core enumeration to pass."""
    registry, opened, channel, records, relayed, log_base = _real_peer_rig(tmp_path)
    try:
        request_id = _session_new(channel, tmp_path)
        native = _wait_until(lambda: _response_for(relayed, request_id), message="session/new answer")
        native_id = native["result"]["sessionId"]

        command = "/workflow ship-it --dry-run"
        _prompt(channel, native_id, command)

        # The native peer's own log proves the non-standard command arrived byte-identical.
        received = _wait_until(
            lambda: [row for row in _peer_rows(log_base)
                     if row.get("dir") == "recv"
                     and row.get("frame", {}).get("method") == "session/prompt"
                     and row["frame"].get("params", {}).get("sessionId") == native_id],
            message="session/prompt at the native peer")
        assert received[0]["frame"]["params"]["prompt"] == [{"type": "text", "text": command}], \
            "the native command channel must carry the command as written; no core whitelist may rewrite it"

        # The peer's answer comes back on the same relay: the request id is answered by the native
        # result, never by a synthesized product-side refusal.
        answer = _wait_until(lambda: _response_for(relayed, "t706-prompt"), message="prompt answer")
        assert answer.get("result", {}).get("stopReason") == "end_turn", answer
        echo = _wait_until(
            lambda: [frame for frame in _frames(relayed)
                     if frame.get("method") == "session/update"
                     and frame.get("params", {}).get("update", {}).get("sessionUpdate") == "agent_message_chunk"
                     and frame["params"]["update"].get("content", {}).get("text") == f"got:{command}"],
            message="native echo of /workflow")
        assert len(echo) == 1
        assert records.finished == [] and records.failed == []
    finally:
        assert registry.release(opened["connectionId"])["released"] is True


# -- negative: repeated unknown event keeps concluded state -------------------


def test_repeated_unknown_event_changes_no_concluded_state_and_resends_nothing(tmp_path):
    registry, opened, channel, records, sent, callbacks = _fake_peer_rig(tmp_path)
    try:
        channel.transport.send_line(json.dumps({
            "jsonrpc": "2.0", "id": "new-1", "method": "session/new", "params": {"cwd": str(tmp_path)}}))
        callbacks[0](json.dumps({"jsonrpc": "2.0", "id": "new-1", "result": {"sessionId": "native-1"}}))
        concluded = registry.native_session_observation(opened["connectionId"], "native-1")
        assert concluded is not None

        relayed: list[str] = []
        channel.attach(ImmediateLoop(), relayed.append)
        before = list(sent)
        line = _unknown_update_line("native-1")
        for _ in range(3):
            callbacks[0](line)
        # A vendor request with no answer must not be answered or re-sent on the peer's behalf.
        callbacks[0](json.dumps({"jsonrpc": "2.0", "id": "vendor-9",
                                 "method": "vendor/unknown_request", "params": {}}))

        assert registry.native_session_observation(opened["connectionId"], "native-1") is concluded, \
            "a repeated unknown event must not clear or replace a concluded native observation"
        assert records.finished == [] and records.failed == []
        assert channel.ended is False
        assert sent == before, "missing ack must not trigger an auto-resend or a fabricated reply"
        # Both events are relayed as-is; the vendor request keeps its method (never an answer shape).
        methods = [json.loads(item).get("method") for item in relayed]
        assert methods == ["session/update", "session/update", "session/update", "vendor/unknown_request"]
        assert json.loads(relayed[0])["params"]["update"]["sessionUpdate"] == "vendor_extension_update"
    finally:
        registry.stop_all()


# -- missing condition: no surface consumer -----------------------------------


def test_unknown_event_without_surface_consumer_is_dropped_without_crash(tmp_path):
    registry, opened, channel, records, sent, callbacks = _fake_peer_rig(tmp_path)
    try:
        channel.transport.send_line(json.dumps({
            "jsonrpc": "2.0", "id": "new-1", "method": "session/new", "params": {"cwd": str(tmp_path)}}))
        callbacks[0](json.dumps({"jsonrpc": "2.0", "id": "new-1", "result": {"sessionId": "native-1"}}))
        concluded = registry.native_session_observation(opened["connectionId"], "native-1")
        assert concluded is not None
        before = list(sent)
        # No consumer is attached: every unknown arrival is dropped, not buffered.
        for index in range(64):
            callbacks[0](_unknown_update_line("native-1", {"n": index}))
        assert channel.ended is False
        assert registry.native_session_observation(opened["connectionId"], "native-1") is concluded
        assert records.finished == [] and records.failed == []

        # A consumer attaching later sees no replay of what it missed; the relay has no buffer.
        late: list[str] = []
        channel.attach(ImmediateLoop(), late.append)
        assert late == [], "no subscription buffer may replay unknown events delivered before attach"
        callbacks[0](_unknown_update_line("native-1", {"after": True}))
        assert len(late) == 1 and json.loads(late[0])["params"]["update"]["payload"] == {"after": True}
        assert sent == before, "dropping the event must not write anything back to the peer"
    finally:
        registry.stop_all()
