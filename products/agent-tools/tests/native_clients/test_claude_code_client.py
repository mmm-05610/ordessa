"""N005 Claude Code client tests — L1 fake upstream (scripted stream-json).

Proves client-side record handling only; no real claude binary exists here
(L2 untested, registered). Fake upstream marked in test names.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from ordessa_agent_tools.native_clients import (
    ChannelClosed,
    LaunchSpec,
    ProcessChannel,
    RequestTimeout,
)
from ordessa_agent_tools.native_clients.claude_code import ClaudeCodeClient

PEER = textwrap.dedent(
    """
    import json, sys, time
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    mode = sys.argv[1]
    send({"type": "system", "subtype": "init", "model": "fake", "capabilities": ["interrupt_receipt_v1"]})
    send({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 3})  # upstream retry fact
    send({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}, "parent_tool_use_id": None})
    send({"type": "stream_event", "event": {"type": "text_delta", "text": "h"}, "parent_tool_use_id": None})
    send({"type": "future/unknownRecord", "keep": "verbatim"})
    if mode == "finish":
        send({"type": "result", "subtype": "success", "result": "done", "session_id": "sess-9"})
    elif mode == "hang":
        time.sleep(60)
    while True:
        line = sys.stdin.readline()
        if not line:
            break
    """
)


def launch_client(tmp_path, mode):
    script = tmp_path / "fake_claude.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build([sys.executable, str(script), mode], home=str(tmp_path / "home"), cwd=str(tmp_path))
    channel = ProcessChannel.launch(spec, name=f"fake-claude-{mode}")
    return ClaudeCodeClient(channel), channel


def test_l1_initialize_reads_system_init_and_capabilities(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        init = client.initialize(timeout=5)
        assert init["model"] == "fake"
        assert client.capabilities == ("interrupt_receipt_v1",)
    finally:
        channel.close()


def test_l1_result_is_terminal_and_keeps_session_id(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        client.initialize(timeout=5)
        result = client.wait_result(timeout=5)
        assert result["session_id"] == "sess-9"
        assert result["result"] == "done"
    finally:
        channel.close()


def test_l1_unknown_records_and_api_retry_are_surfaced_verbatim(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    try:
        client.initialize(timeout=5)
        client.wait_result(timeout=5)
        types = [r.get("type") for r in client.records()]
        assert "future/unknownRecord" in types  # G4 unknown preserved
        retry = next(r for r in client.records() if r.get("subtype") == "api_retry")
        assert retry["attempt"] == 1  # upstream retry surfaced as a fact (G11: not hidden, not ours)
    finally:
        channel.close()


def test_l1_timeout_is_unknown_and_never_resends(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "hang")
    try:
        client.initialize(timeout=5)
        with pytest.raises(RequestTimeout):
            client.wait_result(timeout=1)
    finally:
        exit_code = channel.close()
        assert exit_code is not None  # owned process boundary is the evidence (G6)


def test_l1_close_then_use_is_channel_closed(tmp_path) -> None:
    client, channel = launch_client(tmp_path, "finish")
    client.initialize(timeout=5)
    channel.close()
    with pytest.raises(ChannelClosed):
        client.next_record(timeout=1)
