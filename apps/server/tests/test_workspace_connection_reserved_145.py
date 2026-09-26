"""Order 145: `workspace.connection` is declared and numbered, and has no producer.

`AUD-B-011` (needs_validation) asked which of two things is true. The
three-source reconciliation, run here rather than remembered:

  declared   `wire/projection.py` lists the name in the wire kind set and maps
             internal -> wire; `sessions/repository.py` numbers it (order 128's
             14-member set), so a row of this kind would take a line number.
  produced   no call site anywhere in `src/agent_box` appends it. The one place
             that appends events by variable kind is
             `execution/sidecar_backend.py::_native_event`, and its branch list
             does not name it. **Zero producers.**
  delivered  the projection *can* render it (`projection.py:342`), and a hand
             written row does come back as a frame over the real history face.

So the档 is **2(b)**: keep the id, state that the Server does not emit it today,
and gate the absence. Why not 2(a) (delete the name): a wire kind is
client-visible vocabulary, and the reason it cannot fire today is structural -
`server_session_events.session_id` is NOT NULL and `EventFrame.sessionId` is
required, so a session-less "browsing" phase has no stream to carry the frame.
Removing the name would hide a question that belongs to the contract line
(ops's own account, `agent-box-server-round1` status: 需前端在合同层裁决).

The gate is not "we grepped once": the counter-example writes the row by hand
and shows a frame *does* arrive, so the absence assertion can only stay green
while the producer stays missing.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "packages" / "pacthold" / "src" / "pacthold"

from ordessa_server.bootstrap import build_runtime
from ordessa_server.transport.http import create_app
from ordessa_server.wire import projection as projection_module

KIND = "workspace.connection"

#: The neighbours a real session actually produces, with payloads shaped like
#: the producers' own call sites. Absence of `workspace.connection` is only
#: meaningful next to kinds that do arrive.
NEIGHBOURS = {
    "message.delta": {"text": "body"},
    "config.changed": {"effective_for": "next_send"},
    "queue.updated": {"item": {"id": "q145", "state": "pending"}},
}


class _StubExecution:
    def accept(self, execution_id):
        return None

    def cancel(self, execution_id):
        return True

    def cancel_execution(self, execution_id):
        from ordessa_server_compat.execution import CancelOutcome
        return (CancelOutcome.CONFIRMED_STOPPED if self.cancel(execution_id)
                else CancelOutcome.REFUSED_NO_ACTIVE_RUN)


@pytest.fixture
def server(tmp_path, monkeypatch):
    from ordessa_workspace import local_environment as local_env

    monkeypatch.setattr(local_env.LocalEnvironmentProvider, "sandbox_available",
                        lambda self: True)
    from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry

    registry = HarnessRegistry()
    registry.register(HarnessDescriptor("alpha", capability_claims={"stream": True}))
    runtime = build_runtime(tmp_path / "data", harnesses=registry, execution=_StubExecution())
    with TestClient(create_app(runtime), base_url="http://127.0.0.1",
                    raise_server_exceptions=False) as client:
        yield runtime, client, {"Authorization": f"Bearer {runtime.token}"}, tmp_path


def _session_with_turn(server, label):
    runtime, client, headers, tmp_path = server
    project = tmp_path / label
    project.mkdir(exist_ok=True)
    workspace = client.post("/wire/v1/workspaces.open", headers=headers, json={
        "jsonrpc": "2.0", "id": "open", "method": "workspaces.open",
        "params": {"requestId": f"p145-open-{label}", "path": str(project),
                   "environment": {"kind": "local", "host": None, "user": None}},
    }).json()["result"]["workspace"]["id"]
    profile = client.post("/api/v1/profiles",
                          headers={**headers, "Idempotency-Key": f"p145-prof-{label}"},
                          json={"name": label, "harness_type": "alpha",
                                "configuration": {}, "credential_id": None}).json()["profile_id"]
    session_id = client.post("/api/v1/sessions",
                             headers={**headers, "Idempotency-Key": f"p145-sess-{label}"},
                             json={"workspace_id": workspace,
                                   "profile_id": profile}).json()["session_id"]
    turn = client.post(f"/api/v1/sessions/{session_id}/turns",
                       headers={**headers, "Idempotency-Key": f"p145-turn-{label}"},
                       json={"text": label, "expected_profile_revision": 1}).json()
    return runtime, session_id, turn.get("turn_id") or turn["id"]


def _frames(client, headers, session_id):
    body = client.post("/wire/v1/history.snapshot", headers=headers, json={
        "jsonrpc": "2.0", "id": "hist", "method": "history.snapshot",
        "params": {"sessionId": session_id}}).json()
    frames = (body.get("result") or {}).get("frames") or []
    assert frames, body
    return [frame["event"] for frame in frames]


# -- stage 1: the three sources, checked rather than quoted -----------------

def test_the_name_is_declared_and_numbered_but_nothing_appends_it():
    assert KIND in projection_module.WIRE_EVENT_KINDS or KIND in getattr(
        projection_module, "EVENT_KINDS", ()), "the declared set moved - re-read 145"
    assert projection_module._EVENT_KIND_MAP.get(KIND) == KIND  # noqa: SLF001

    producers = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'append_turn_event\(([^)]*)\)', text, re.S):
            if KIND in match.group(1):
                producers.append(f"{path.relative_to(REPO)}")
    assert producers == [], f"someone wired a producer: {producers}"


def test_the_sidecar_event_vocabulary_does_not_name_it():
    """The one call site that appends by *variable* kind is the native-event
    bridge; if this list ever grows the name, 145's档 changes with it."""
    text = (REPO / "plugins" / "server-compat" / "src" / "ordessa_server_compat" / "execution" / "sidecar_backend.py").read_text(encoding="utf-8")
    bridge = text[text.index("def _native_event("):]
    bridge = bridge[:bridge.index("\n    def ")] if "\n    def " in bridge else bridge
    assert KIND not in bridge, "the native bridge now routes this kind - recheck 145"


# -- 2(b), landed: the reservation is written where the name lives ----------

def test_the_reservation_is_written_next_to_the_name():
    source = (REPO / "apps/server/src/ordessa_server/wire/projection.py").read_text(encoding="utf-8")
    declared = source[source.index(KIND):source.index(KIND) + 900]
    assert "145" in declared and "producer" in declared.lower(), declared[:300]


def test_the_numbering_set_still_carries_it_unchanged():
    """128's invariant, reasserted: 145 changes no vocabulary and no numbering,
    and the one-line exception the order offered was **not used**."""
    from ordessa_server_compat.sessions import repository as repo_module

    assert KIND in repo_module.WIRE_VISIBLE_EVENT_KINDS
    assert len(repo_module.WIRE_VISIBLE_EVENT_KINDS) == 14


# -- stage 4: the gate, over the real history face -------------------------

def test_a_real_session_never_shows_the_reserved_kind(server):
    runtime, client, headers, _tmp = server
    runtime, session_id, turn_id = _session_with_turn(server, "role-145")
    for kind, payload in NEIGHBOURS.items():
        runtime.repository.append_turn_event(turn_id, kind, dict(payload))
    frames = _frames(client, headers, session_id)
    kinds = {frame["kind"] for frame in frames}
    assert {"message.delta", "config.changed", "queue.updated"} <= kinds, kinds
    assert KIND not in kinds, f"the reserved kind appeared without a producer: {frames}"


def test_counter_example_a_hand_written_row_does_produce_a_frame(server):
    """The absence above has teeth: the pipe works, only the water is missing.

    If someone later wires a producer, `test_a_real_session_never_shows_the_reserved_kind`
    goes red by itself - which is the point of choosing 2(b) with a gate instead
    of a comment.
    """
    runtime, client, headers, _tmp = server
    runtime, session_id, turn_id = _session_with_turn(server, "hand-145")
    runtime.repository.append_turn_event(turn_id, KIND, {
        "workspace_id": "ws_145", "connection": {"state": "disconnected"}})
    frames = [frame for frame in _frames(client, headers, session_id) if frame["kind"] == KIND]
    assert len(frames) == 1, frames
    assert frames[0]["workspaceId"] == "ws_145", frames[0]
    assert frames[0]["connection"] == {"state": "disconnected"}, frames[0]
    assert json.dumps(frames).count(KIND) == 1


def test_the_frame_shape_is_the_one_the_projection_defines(server):
    """Not invented here: the reserved kind's frame is what `projection.py`
    already writes, and a missing `connection` falls back to `connecting`."""
    runtime, client, headers, _tmp = server
    runtime, session_id, turn_id = _session_with_turn(server, "shape-145")
    runtime.repository.append_turn_event(turn_id, KIND, {"workspace_id": "ws_shape"})
    frame = [f for f in _frames(client, headers, session_id) if f["kind"] == KIND][0]
    assert frame["connection"] == {"state": "connecting"}, frame
    assert set(frame) == {"kind", "workspaceId", "connection"}, frame
