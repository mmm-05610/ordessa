"""Requirement 3: two live connections that use the same JSON-RPC ids (and even
the same native session id) must not cross-talk.

Both peers answer prompts, raise their permission request under the identical
JSON-RPC id 7777, and are forced to report the identical native session id.
The Server must still route each approval decision, each event stream and each
terminal state to its own session.
"""
import time

import pytest

from tests.acp_orchestration.conftest import peer_events, session_new_events


def _pid_for_project(log_base: str, project) -> int:
    def produce():
        for row in peer_events(log_base):
            if row.get("event") == "session-new" and row.get("cwdParam") == str(project):
                return row["pid"]
        return None
    from tests.acp_orchestration.conftest import wait_until
    return wait_until(produce, timeout=30, message=f"peer for {project}")


def test_two_channels_same_jsonrpc_ids_and_same_native_id_do_not_cross(server, tmp_path, monkeypatch):
    monkeypatch.setenv("HD003_FORCE_SESSION_ID", "shared-native-id-hd003")
    profile_id = server.native_profile_id()
    handles = {}
    for label, decision in (("alpha", "allow"), ("beta", "deny")):
        project = tmp_path / f"project-{label}"
        project.mkdir()
        workspace_id = server.open_workspace(project)
        sent = server.create_and_send(
            workspace_id, profile_id, f"scenario:permission marker-{label}")
        handles[label] = {"session": sent["session"]["id"], "decision": decision,
                          "project": project}

    # Both reverse requests must be pending, with the same wire-side id 7777 on
    # both peers, before any decision is made.
    approvals = {}
    for label, handle in handles.items():
        def produce(h=handle):
            matches = [event["approval"] for event in server.frames(h["session"])
                       if event.get("kind") == "approval.requested"]
            return matches[-1] if matches else None
        from tests.acp_orchestration.conftest import wait_until
        approvals[label] = wait_until(produce, timeout=30,
                                      message=f"approval for {label}")

    # No fabricated answers while decisions are still with the client.
    time.sleep(0.5)
    assert not [row for row in peer_events(server.log_base)
                if row.get("event") == "permission-answer"]

    for label, handle in handles.items():
        approval = approvals[label]
        decided = server.wire("approvals.decide", {
            "requestId": server.request_id(f"decide-{label}"),
            "approvalId": approval["approvalId"],
            "decision": handle["decision"], "scope": {"kind": "once"},
            "expectedVersion": approval["version"],
        })
        assert decided["result"]["outcome"] == "recorded", (label, decided)

    for label, handle in handles.items():
        row = server.settled(handle["session"], 1)
        assert row["turns"][-1]["state"] == "completed", (label, row["turns"][-1])
        assert row["checkpoint"]["native_id"] == "shared-native-id-hd003", row["checkpoint"]
        # Each session's stream only mentions its own marker.
        stream = str(server.frames(handle["session"]))
        assert f"marker-{label}" in stream, (label, stream)
        assert f"marker-{'beta' if label == 'alpha' else 'alpha'}" not in stream, (label, stream)

    # And the decisions landed on the right channels: each peer logged its own
    # answer, with the option kind its session's client chose.
    pids = {label: _pid_for_project(server.log_base, handle["project"])
            for label, handle in handles.items()}
    assert len(set(pids.values())) == 2, pids
    answers = {row["pid"]: row["frame"] for row in peer_events(server.log_base)
               if row.get("event") == "permission-answer"}
    assert set(answers) == set(pids.values()), answers.keys()
    for label, pid in pids.items():
        outcome = answers[pid]["result"]["outcome"]
        prefix = "grant-" if handles[label]["decision"] == "allow" else "reject-"
        assert outcome["outcome"] == "selected" and outcome["optionId"].startswith(prefix), \
            (label, outcome)
    assert len(session_new_events(server.log_base)) == 2
