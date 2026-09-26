"""Order 128 — `seq` on the wire means one thing, and a gate keeps it that way.

`AUD-B-010` measured that four frame-producing kinds (`thought.delta`,
`plan.updated`, `mode.updated`, `usage.updated`) were never given a `wire_seq`,
while `event_frame` falls back to the storage `seq` when the number is missing
(`wire/projection.py:206`). So one stream carried two number spaces and a client
that sorts or de-duplicates by `seq` loses the body and the tool cards.

The fix is one line of set membership; the thing that keeps it from rotting is
Gate G2 below — the same lesson order 097 learned about `server.hello`, where a
declared list drifted from the real dispatch table by 37 methods.

Frames are read back through the real history face over HTTP, not by calling the
numbering helper (G3).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from ordessa_server.bootstrap import build_runtime
from ordessa_server_compat.sessions import repository as repo_module
from ordessa_server.transport.http import create_app
from ordessa_server.wire import projection as projection_module

#: Every kind the wire turns into a frame, with a payload shaped like the one
#: the real producer writes at its call site.
FRAME_KINDS = {
    "turn.accepted": {"state": "accepted"},
    "turn.state": {"state": "running"},
    "message.delta": {"text": "body chunk"},
    "message.final": {"text": "final"},
    "usage.updated": {"usage": {"inputTokens": 10, "outputTokens": 20}, "turn_id": "t1"},
    "thought.delta": {"text": "thinking"},
    "plan.updated": {"items": [{"text": "step", "state": "pending"}]},
    "mode.updated": {"mode": "default"},
    "tool.update": {"toolCallId": "t1", "title": "read", "status": "completed"},
    "approval.requested": {"approvalId": "a1", "tool": "write"},
    "approval.settled": {"approvalId": "a1", "decision": "deny"},
    "config.changed": {"effective_for": "next_send"},
    "queue.updated": {"item": {"id": "q1", "state": "pending"}},
    "workspace.connection": {"state": "connected"},
}

#: The four `AUD-B-010` names: they make frames, they were not numbered.
NEWLY_NUMBERED = ("thought.delta", "plan.updated", "mode.updated", "usage.updated")

#: The numbering set as it stood before order 128 — the counter-example's input.
PRE_128_NUMBERED = frozenset(set(FRAME_KINDS) - set(NEWLY_NUMBERED))


class _StubExecution:
    """An execution backend that accepts and never runs: this order is about numbering."""

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
    # The local placement asks the host whether it can run a room; this order is
    # about numbering, so the answer is supplied rather than inherited from
    # `bwrap` (which needs AGENT_BOX_SANDBOX_MODULE to resolve at all).
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


_COUNTER = {"n": 0}


def _session_with_turn(server) -> tuple[str, str]:
    """A Session and one turn to hang events on, through the product's own surface."""
    runtime, client, headers, tmp_path = server
    _COUNTER["n"] += 1
    ordinal = _COUNTER["n"]
    project = tmp_path / f"p128-{ordinal}"
    project.mkdir(exist_ok=True)
    opened = client.post("/wire/v1/workspaces.open", headers=headers, json={
        "jsonrpc": "2.0", "id": "open", "method": "workspaces.open",
        "params": {"requestId": f"p128-open-{ordinal}", "path": str(project),
                   "environment": {"kind": "local", "host": None, "user": None}}})
    workspace_id = opened.json()["result"]["workspace"]["id"]
    profile = client.post("/api/v1/profiles", headers={**headers, "Idempotency-Key": f"prof-{ordinal}"},
                          json={"name": f"p128-{ordinal}", "harness_type": "alpha",
                                "configuration": {}, "credential_id": None})
    profile_id = profile.json()["profile_id"]
    session = client.post("/api/v1/sessions", headers={**headers, "Idempotency-Key": f"s-{ordinal}"},
                          json={"workspace_id": workspace_id, "profile_id": profile_id})
    session_id = session.json()["session_id"]
    turn = client.post(f"/api/v1/sessions/{session_id}/turns",
                       headers={**headers, "Idempotency-Key": f"t-{ordinal}"},
                       json={"text": f"p128-turn-{ordinal}", "expected_profile_revision": 1})
    turn_body = turn.json()
    turn_id = turn_body.get("turn_id") or turn_body.get("id")
    assert turn_id, (turn.status_code, turn.text[:300])
    return session_id, turn_id


def _append_alternating(runtime, session_id: str, turn_id: str, kinds) -> None:
    """Two passes over the kinds, interleaved, through the durable write path."""
    for _round in (1, 2):
        for kind in kinds:
            runtime.repository.append_turn_event(turn_id, kind, dict(FRAME_KINDS[kind]))


def _frames(client, headers, session_id: str) -> list[dict]:
    body = client.post("/wire/v1/history.snapshot", headers=headers, json={
        "jsonrpc": "2.0", "id": "history.snapshot", "method": "history.snapshot",
        "params": {"sessionId": session_id},
    }).json()
    result = body.get("result") or {}
    frames = result.get("frames") or []
    assert frames, body
    return frames


def _assert_one_number_space(frames: list[dict]) -> dict:
    """What a client needs: strictly increasing, gap-free, and nothing dropped."""
    seqs = [frame["seq"] for frame in frames]
    kinds = [frame["event"]["kind"] for frame in frames]
    assert seqs == sorted(seqs), f"frames arrive out of order: {seqs}"
    assert len(set(seqs)) == len(seqs), f"`seq` means two things at once: {seqs}"
    assert set(seqs) == set(range(min(seqs), min(seqs) + len(seqs))), f"gaps: {seqs}"
    # Frames carry the *wire* names (`turn.accepted`/`turn.state` both become
    # `execution.state`), so the expectation is the mapped set, not the internal one.
    expected = {projection_module._EVENT_KIND_MAP[kind]  # noqa: SLF001
                for kind in FRAME_KINDS}
    assert expected <= set(kinds), f"kinds lost from the stream: {sorted(expected - set(kinds))}"
    return {"frames": len(frames), "seqRange": [min(seqs), max(seqs)],
            "kinds": len(set(kinds)), "duplicateSeqs": len(seqs) - len(set(seqs))}


# -- G2: the number means one thing, and the sets cannot drift again --------

def test_the_numbered_set_is_exactly_the_frame_set():
    """`097`'s lesson, applied to numbering: a declared list drifts from the real
    table unless the drift itself is a failure. This is the gate that would have
    caught `AUD-B-010` the day the four kinds started producing frames."""
    frame_kinds = set(projection_module._EVENT_KIND_MAP)  # noqa: SLF001
    numbered = repo_module.WIRE_VISIBLE_EVENT_KINDS
    assert frame_kinds - numbered == set(), sorted(frame_kinds - numbered)
    assert numbered - frame_kinds == set(), sorted(numbered - frame_kinds)
    # The same drift, one layer further out: the wire's declared kind list must
    # be exactly what the internal kinds project onto (097's lesson again).
    assert set(projection_module._EVENT_KIND_MAP.values()) == projection_module.WIRE_EVENT_KINDS


def test_the_four_kinds_aud_b_010_named_are_numbered_now(server):
    runtime, client, headers, _tmp = server
    session_id, turn_id = _session_with_turn(server)
    _append_alternating(runtime, session_id, turn_id, NEWLY_NUMBERED)
    frames = _frames(client, headers, session_id)
    for kind in NEWLY_NUMBERED:
        matching = [frame for frame in frames if frame["event"]["kind"] == kind]
        assert matching, kind
        assert all(isinstance(frame["seq"], int) for frame in matching), (kind, matching[:2])


# -- G1: an alternating stream loses nothing when sorted or de-duplicated ---

def test_alternating_frames_survive_a_clients_sort_and_dedupe(server):
    runtime, client, headers, _tmp = server
    session_id, turn_id = _session_with_turn(server)
    _append_alternating(runtime, session_id, turn_id, list(FRAME_KINDS))
    frames = _frames(client, headers, session_id)
    measured = _assert_one_number_space(frames)
    # The client-side rule, exercised rather than described: sort by `seq`,
    # de-duplicate by `seq`, keep everything.
    ordered = sorted(frames, key=lambda frame: frame["seq"])
    deduped = {frame["seq"]: frame for frame in ordered}
    assert len(deduped) == len(frames), measured
    expected = {projection_module._EVENT_KIND_MAP[kind] for kind in FRAME_KINDS}  # noqa: SLF001
    assert expected <= {frame["event"]["kind"] for frame in deduped.values()}, measured


def test_counter_example_the_pre_128_numbering_breaks_the_same_assertion(server, monkeypatch):
    """G1/G2's falsifier: put the old numbering set back and the same stream has
    to stop being a single number space."""
    runtime, client, headers, _tmp = server
    monkeypatch.setattr(repo_module, "WIRE_VISIBLE_EVENT_KINDS", PRE_128_NUMBERED)
    assert repo_module.WIRE_VISIBLE_EVENT_KINDS is PRE_128_NUMBERED
    session_id, turn_id = _session_with_turn(server)
    _append_alternating(runtime, session_id, turn_id, list(FRAME_KINDS))
    frames = _frames(client, headers, session_id)
    with pytest.raises(AssertionError) as raised:
        _assert_one_number_space(frames)
    assert "two things" in str(raised.value) or "out of order" in str(raised.value), str(raised.value)


def test_the_history_face_rejects_a_second_row_with_the_same_number(server):
    """The other half of the mixing: `server_session_wire_order` is UNIQUE, so a
    stream that reuses a number is not merely ugly to a client — it collides."""
    runtime, client, headers, _tmp = server
    # The constant is restored by hand, not by `monkeypatch.undo()`: that would
    # also take back the `sandbox_available` stub the fixture installed through
    # the same function-scoped object, and the second leg's `workspaces.open`
    # would then be refused for a reason that has nothing to do with numbering.
    original = repo_module.WIRE_VISIBLE_EVENT_KINDS
    try:
        repo_module.WIRE_VISIBLE_EVENT_KINDS = PRE_128_NUMBERED
        session_id, turn_id = _session_with_turn(server)
        _append_alternating(runtime, session_id, turn_id, ["message.delta"] + list(NEWLY_NUMBERED))
        frames = _frames(client, headers, session_id)
        reused = len(frames) - len({frame["seq"] for frame in frames})
        assert reused > 0, f"the pre-128 shape produced no reuse at all: {frames[:3]}"
    finally:
        repo_module.WIRE_VISIBLE_EVENT_KINDS = original
    fresh_session, fresh_turn = _session_with_turn(server)
    _append_alternating(runtime, fresh_session, fresh_turn, list(FRAME_KINDS))
    assert _assert_one_number_space(_frames(client, headers, fresh_session))


# -- G4: the surface itself did not move -----------------------------------

def test_no_event_kind_or_payload_was_invented(server):
    """128 normalises numbering and nothing else: the kind set, the frame map and
    `server.hello`'s method list are the ones this order inherited."""
    assert set(projection_module._EVENT_KIND_MAP) == set(FRAME_KINDS)  # noqa: SLF001
    _runtime, client, headers, _tmp = server
    hello = client.post("/wire/v1/server.hello", headers=headers, json={
        "jsonrpc": "2.0", "id": "hello", "method": "server.hello",
        "params": {"clientVersions": ["1.0"], "clientPresentationSupports": []},
    }).json()["result"]
    assert len(hello["capabilities"]) == 67, len(hello["capabilities"])


def test_the_gate_reads_frames_over_http_and_not_the_helper(server):
    """G3: every assertion above came out of `history.snapshot` over the socket."""
    runtime, client, headers, _tmp = server
    session_id, turn_id = _session_with_turn(server)
    _append_alternating(runtime, session_id, turn_id, ["thought.delta"])
    frames = _frames(client, headers, session_id)
    thought = [frame for frame in frames if frame["event"]["kind"] == "thought.delta"]
    assert thought and isinstance(thought[0]["seq"], int)
    assert json.dumps(thought[0]).count("wire_seq") == 0, "the internal column name leaked"
