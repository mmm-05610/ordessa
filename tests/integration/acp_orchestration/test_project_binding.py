"""Requirement 1: a legal project cwd must reach every launch boundary, and a
project that is gone or changed must be refused before any Agent launch.

Boundaries pinned: Server -> worker process (`NativeProcessLauncher.cwd`), and
worker -> Agent (`session/new.cwd` ACP parameter plus the adapter's own
`process.cwd`).  Evidence comes from the controlled peer's own log, never from
a test-local relay.
"""
import os

import pytest

from tests.integration.acp_orchestration.conftest import session_new_events


def test_project_cwd_reaches_both_launch_boundaries(server, tmp_path):
    profile_id = server.native_profile_id()
    projects = {}
    for label in ("alpha", "beta"):
        project = tmp_path / f"project-{label}"
        project.mkdir()
        projects[label] = project
        workspace_id = server.open_workspace(project)
        sent = server.create_and_send(workspace_id, profile_id, f"first-{label}")
        row = server.settled(sent["session"]["id"], 1)
        assert row["turns"][-1]["state"] == "completed", row["turns"][-1]
        assert any(f"got:first-{label}" in str(frame)
                   for frame in server.frames(sent["session"]["id"])), row
        # Every project got its own channel pinned to that project's cwd.
        events = session_new_events(server.log_base)
        match = [event for event in events if event["cwdParam"] == str(project)]
        assert match, (label, events)
        assert match[0]["cwd"] == str(project), \
            "adapter process cwd must be the selected project, not the Server's"
    assert len(session_new_events(server.log_base)) == 2


def test_missing_project_refused_before_any_launch(server, tmp_path):
    profile_id = server.native_profile_id()
    project = tmp_path / "vanished"
    project.mkdir()
    workspace_id = server.open_workspace(project)
    os.rmdir(project)
    answer = server.wire("sessions.createAndSend", {
        "requestId": server.request_id("gone"), "workspaceId": workspace_id,
        "profileId": profile_id,
        "message": {"text": "must-not-run", "attachments": []},
        "overrides": [],
    })
    assert "error" in answer, answer
    assert session_new_events(server.log_base) == [], \
        "a refused send must not reach the launch boundary"


def test_project_replaced_by_different_tree_refused(server, tmp_path):
    profile_id = server.native_profile_id()
    original = tmp_path / "original"
    elsewhere = tmp_path / "elsewhere"
    original.mkdir()
    elsewhere.mkdir()
    workspace_id = server.open_workspace(original)
    sent = server.create_and_send(workspace_id, profile_id, "baseline")
    assert server.settled(sent["session"]["id"], 1)["turns"][-1]["state"] == "completed"
    baseline_new = len(session_new_events(server.log_base))

    os.rmdir(original)
    os.symlink(elsewhere, original)  # the selected path now resolves elsewhere
    row = sent["session"]["id"]
    answer = server.wire("sessions.send", {
        "requestId": server.request_id("retarget"), "sessionId": row,
        "message": {"text": "after-retarget", "attachments": []},
        "overrides": [],
    })
    refused = "error" in answer
    settled = None if refused else server.settled(row, 2)
    moved = refused or settled["turns"][-1]["state"] in {"failed", "unknown"}
    assert moved, (answer, settled and settled["turns"][-1])
    error = answer.get("error") or {}
    code = str((error.get("details") or {}).get("internalCode") or error.get("code") or "")
    if settled is not None:
        code += " " + str(settled["turns"][-1].get("error_code"))
    assert "NATIVE_PROJECT_CHANGED" in code or "LOCAL_PATH" in code, code
    assert len(session_new_events(server.log_base)) == baseline_new, \
        "a retargeted project must not spawn a new Agent session"
