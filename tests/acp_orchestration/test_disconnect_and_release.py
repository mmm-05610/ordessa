"""Requirements 7-9: a dead connection is never judged as a completed or
cancelled conversation; releasing one execution must only touch resources that
execution owns; and nothing may auto-replay a prompt or create a replacement
session after a disconnect.
"""
import os
import time

import pytest

from tests.acp_orchestration.conftest import (
    peer_events, pid_alive, session_new_events, wait_until,
)
from ordessa_server_compat.execution.sidecar import SidecarError


# -- requirement 7 ------------------------------------------------------------


def test_channel_death_during_prompt_is_not_success_or_cancel(ports, project):
    handle = ports(project)
    handle.open()
    with pytest.raises(SidecarError) as caught:
        handle.port.prompt("execution-1", "scenario:die")
    error = caught.value
    assert "end_turn" not in error.message and "cancelled" not in str(error.args), error
    # The partial stream that arrived before death does not become a result:
    assert handle.event_for("message.delta", "pre-death-chunk")
    # and death itself is reported as a failure fact, not a clean close.
    failed = [event for event in handle.events if event[1] == "failed"]
    assert failed or error.code, (handle.kinds(), error)
    assert not any(kind == "completed" for _, kind, _ in handle.events)


def test_full_stack_death_settles_failed_not_completed_or_cancelled(server, tmp_path):
    profile_id = server.native_profile_id()
    project = tmp_path / "dying"
    project.mkdir()
    workspace_id = server.open_workspace(project)
    sent = server.create_and_send(workspace_id, profile_id, "scenario:die")
    row = server.settled(sent["session"]["id"], 1)
    state = row["turns"][-1]["state"]
    assert state == "failed", (state, row["turns"][-1])
    assert row["turns"][-1].get("error_code"), row["turns"][-1]


# -- requirement 8 ------------------------------------------------------------


def _peer_pid_for(log_base, cwd):
    def produce():
        for row in peer_events(log_base):
            if row.get("event") == "peer-start" and row.get("cwd") == str(cwd):
                return row["pid"]
        return None
    return wait_until(produce, timeout=30, message=f"peer started in {cwd}")


def test_release_only_touches_the_owned_channel(ports, tmp_path):
    a = tmp_path / "project-a"
    b = tmp_path / "project-b"
    a.mkdir()
    b.mkdir()
    first = ports(a)
    second = ports(b)
    first.open("exec-a")
    second.open("exec-b")
    assert first.port.prompt("exec-a", "alpha-round")
    assert second.port.prompt("exec-b", "beta-round")
    pid_a = _peer_pid_for(first.log_base, a)
    pid_b = _peer_pid_for(second.log_base, b)
    assert pid_a != pid_b

    first.port.stop()  # release only what this port owns
    wait_until(lambda: not pid_alive(pid_a), timeout=15,
               message=f"peer {pid_a} to exit with its own channel")
    assert pid_alive(pid_b), "releasing one execution killed a process it does not own"
    # and the untouched channel still answers, with its session unchanged
    assert second.port.prompt("exec-b", "beta-round-2")
    assert second.port._native_sessions["exec-b"]  # private but decisive: same id
    assert not [row for row in session_new_events(second.log_base)
                if row["cwdParam"] == str(b)][1:], "release forced a replacement session"


# -- requirement 9 ------------------------------------------------------------


def test_no_reprompt_no_replacement_session_after_death(ports, project):
    handle = ports(project)
    handle.open()
    with pytest.raises(SidecarError):
        handle.port.prompt("execution-1", "scenario:die")
    baseline_new = len(session_new_events(handle.log_base))
    baseline_starts = len([row for row in peer_events(handle.log_base)
                           if row.get("event") == "peer-start"])

    # A follow-up on the dead execution must fail, not replay.
    with pytest.raises(SidecarError):
        handle.port.prompt("execution-1", "follow-up")
    # A new execution bound to the same (dead-adapter) channel must fail
    # rather than spawn or reuse a replacement native conversation.
    with pytest.raises(SidecarError):
        handle.open("execution-2")
        handle.port.prompt("execution-2", "follow-up-2")

    assert len(session_new_events(handle.log_base)) == baseline_new, \
        "a replacement native session was created after the disconnect"
    assert len([row for row in peer_events(handle.log_base)
                if row.get("event") == "peer-start"]) == baseline_starts, \
        "an Agent process was re-launched without being asked"
    # Nothing new was ever handed to the peer after its death.
    prompts = [row for row in peer_events(handle.log_base)
               if row.get("dir") == "recv"
               and row.get("frame", {}).get("method") == "session/prompt"]
    assert len(prompts) == 1, prompts
