"""Regression: CodexAppServerClient.diagnostics must return bounded diagnostics."""
from __future__ import annotations

from pathlib import Path

from ordessa_harness_codex.app_server.provider import CodexAppServerClient


def _client(tmp_path: Path) -> CodexAppServerClient:
    # Bypass __init__: it starts reader threads over a real transport, which
    # this regression does not need.  diagnostics() reads only bounded
    # in-memory buffers.
    client = CodexAppServerClient.__new__(CodexAppServerClient)
    client.events_path = tmp_path / "events.jsonl"
    client.events = [
        {"method": "turn/completed", "params": {"turn": {"id": "t1", "status": "completed"}}},
        {"method": "turn/failed", "params": {"turn": {"id": "t2", "status": "failed"}}},
        {"method": "other", "params": {}},
    ]
    client.event_methods = ["initialize", "turn/start"]
    client.error_codes = ["E1"]
    client.file_change_statuses = ["applied"]
    client.server_request_methods = ["requestApproval"]
    client.approval_request_methods = ["requestApproval"]
    client.process_exit = None
    return client


def test_diagnostics_returns_bounded_public_dict(tmp_path):
    value = _client(tmp_path).diagnostics(("t1",))
    assert isinstance(value, dict)
    assert value["turn_terminal_statuses"] == ("completed",)
    assert set(value) == {
        "event_methods",
        "error_codes",
        "file_change_statuses",
        "server_request_methods",
        "approval_request_methods",
        "turn_terminal_statuses",
        "process_exit",
    }
    assert value["process_exit"] is None
    assert len(value["event_methods"]) <= 64
