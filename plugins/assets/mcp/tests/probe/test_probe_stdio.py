"""V03 stdio probe tests (upgraded legacy SC/assets/mcp_probe.py path).

Every test names its own short policy bound, so the suite stays
time-self-consistent (<5s per case). ``probe_primitives`` is requested only
by tests that must actually spawn; refusal-path tests run under the intact
package lockdown.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest
from backend import probe
from backend.errors import McpError
from backend.probe_policy import BASE_ENVIRONMENT, ProbePolicy
from helpers import stdio_canonical, wait_pids_gone

FAST = ProbePolicy(timeout=2.0, kill_grace=0.5)
BRIEF = ProbePolicy(timeout=1.0, kill_grace=0.5)


def _facts_keys():
    return {"status", "transport", "evidence", "serverInfo", "protocolVersion",
            "negotiation", "credentialScope", "credentialsExcluded", "proves", "doesNotProve"}


# -- handshake + negotiation ------------------------------------------------------


def test_stdio_handshake_facts_shape(probe_primitives):
    facts = probe.probe_stdio(stdio_canonical("ok"), policy=FAST)
    assert set(facts) == _facts_keys()
    assert facts["status"] == "ok" and facts["transport"] == "stdio"
    assert facts["evidence"] == "initialize-handshake"
    assert facts["serverInfo"] == {"name": "fake-mcp-t03", "version": "0.1"}
    assert facts["credentialScope"] == "unproven"
    assert facts["proves"] == ["initialize-handshake"]
    assert "tool-catalog" in facts["doesNotProve"]


def test_stdio_negotiation_recorded_from_response_echo(probe_primitives):
    # The fake echoes the request's protocolVersion, so this proves the
    # recorded negotiation comes from the *response*, and that the client
    # asked with its newest supported version (>= 2025-11-25 & 2024-11-05).
    facts = probe.probe_stdio(stdio_canonical("ok"), policy=FAST)
    assert facts["protocolVersion"] == "2025-11-25"
    assert facts["negotiation"] == {
        "requested": "2025-11-25",
        "supported": ["2025-11-25", "2024-11-05"],
        "negotiated": "2025-11-25",
    }


def test_stdio_downgrade_negotiation_not_inferred(probe_primitives):
    # Server answers 2024-11-05 to a 2025-11-25 request: the fact stored is
    # the negotiation outcome, not the client's wish and not any field read
    # from storage.
    facts = probe.probe_stdio(stdio_canonical("downgrade"), policy=FAST)
    assert facts["protocolVersion"] == "2024-11-05"
    assert facts["negotiation"]["requested"] == "2025-11-25"
    assert facts["negotiation"]["negotiated"] == "2024-11-05"


def test_stdio_unsupported_version_refused(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("mismatch"), policy=FAST)
    assert refused.value.code == probe.PROBE_PROTOCOL_MISMATCH


# -- FR-02: initialize is never a catalog ------------------------------------------


def test_initialize_tools_block_is_dropped(probe_primitives):
    facts = probe.probe_stdio(stdio_canonical("ok"), policy=FAST)
    encoded = json.dumps(facts)
    assert "unseen-tool" not in encoded  # fake stuffed a tools list in the answer
    assert "tools" not in facts
    assert facts["doesNotProve"] == [
        "tool-catalog", "credential-usability", "connection-lease", "tool-invocability"]


# -- typed refusals on hostile answers (legacy five, shapes kept) --------------------


def test_stdio_timeout_typed_and_bounded(probe_primitives):
    started = time.monotonic()
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("silent"), policy=BRIEF)
    assert refused.value.code == probe.PROBE_TIMEOUT
    assert str(refused.value) == f"{probe.PROBE_TIMEOUT}: the server did not answer in time"
    assert time.monotonic() - started < 2.0  # hard bound, not a hang


def test_stdio_oversized_frame_refused(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("oversized"), policy=FAST)
    assert refused.value.code == probe.PROBE_RESPONSE_TOO_LARGE


def test_stdio_garbage_line_format_invalid(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("garbage"), policy=FAST)
    assert refused.value.code == probe.PROBE_FORMAT_INVALID


def test_stdio_wrong_id_format_invalid(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("badid"), policy=FAST)
    assert refused.value.code == probe.PROBE_FORMAT_INVALID
    assert "id" in refused.value.message


def test_stdio_no_result_format_invalid(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("noresult"), policy=FAST)
    assert refused.value.code == probe.PROBE_FORMAT_INVALID


def test_stdio_exit_before_answer_format_invalid(probe_primitives):
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("exit"), policy=FAST)
    assert refused.value.code == probe.PROBE_FORMAT_INVALID


def test_stdio_spawn_failed_typed(probe_primitives):
    canonical = {"name": "t", "transport": {"stdio": {
        "command": "/nonexistent/mcp-server-t03", "args": []}}}
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(canonical, policy=FAST)
    assert refused.value.code == probe.PROBE_SPAWN_FAILED


def test_stdio_command_shape_refused_without_side_effect():
    relative = {"name": "t", "transport": {"stdio": {"command": "bin/thing", "args": []}}}
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(relative, policy=FAST)
    assert refused.value.code == probe.PROBE_COMMAND_INVALID
    nul = {"name": "t", "transport": {"stdio": {"command": "/x", "args": ["a\x00b"]}}}
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(nul, policy=FAST)
    assert refused.value.code == probe.PROBE_COMMAND_INVALID


# -- process-group discipline --------------------------------------------------------


def test_stdio_tree_reaped_on_success(probe_primitives, tmp_path):
    pids = str(tmp_path / "pids")
    facts = probe.probe_stdio(stdio_canonical("tree", pids), policy=FAST)
    assert facts["status"] == "ok"
    recorded = wait_pids_gone(pids, count=3)
    assert len(recorded) == 3  # server, child, grandchild - all dead
    with pytest.raises(ProcessLookupError):
        os.getpgid(recorded[0])  # group gone, no orphan keeps it alive


def test_stdio_tree_reaped_on_timeout(probe_primitives, tmp_path):
    pids = str(tmp_path / "pids")
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("treelate", pids), policy=BRIEF)
    assert refused.value.code == probe.PROBE_TIMEOUT
    recorded = wait_pids_gone(pids, count=3)
    with pytest.raises(ProcessLookupError):
        os.getpgid(recorded[0])


def test_stdio_cancel_kills_tree(probe_primitives, tmp_path):
    pids = str(tmp_path / "pids")
    cancel = threading.Event()
    # Give the fake time to register its whole tree (pidfile) before
    # cancelling, so the assertion covers child *and* grandchild.
    threading.Timer(0.8, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("treelate", pids), policy=FAST, cancel=cancel)
    assert refused.value.code == probe.PROBE_CANCELLED
    assert time.monotonic() - started < 1.9  # cancelled well before the 2.0s deadline
    recorded = wait_pids_gone(pids, count=3)
    with pytest.raises(ProcessLookupError):
        os.getpgid(recorded[0])


def test_stdio_cancel_before_spawn_starts_nothing(probe_primitives, tmp_path):
    pids = str(tmp_path / "pids")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(McpError) as refused:
        probe.probe_stdio(stdio_canonical("ok", pids), policy=FAST, cancel=cancel)
    assert refused.value.code == probe.PROBE_CANCELLED
    assert not os.path.exists(pids)  # the fake never ran


# -- credential-less scope (FR-02/FR-08) ----------------------------------------------


def test_stdio_environment_is_allowlist_plus_literals_only(probe_primitives, monkeypatch):
    monkeypatch.setenv("ORD_T03_AMBIENT", "ambient-leak")
    canonical = stdio_canonical("leakecho", env={
        "ORD_T03_LITERAL": {"literal": "literal-value"},
        "ORD_T03_SECRET_ENV": {"secretRef": "cred-t03"},
    })
    facts = probe.probe_stdio(canonical, policy=FAST)
    echoed = json.loads(facts["serverInfo"]["version"])
    assert echoed["ambient"] == "absent"      # caller env never inherited
    assert echoed["secretish"] == "absent"    # secretRef never resolved
    assert echoed["literal"] == "literal-value"  # literal subset does run
    assert echoed["path"] == BASE_ENVIRONMENT["PATH"]
    assert facts["credentialScope"] == "unproven"
    assert facts["credentialsExcluded"] == ["ORD_T03_SECRET_ENV"]
    assert "cred-t03" not in json.dumps(facts)  # the reference id itself stays out


# -- dispatch / storage-free surface ---------------------------------------------------


def test_probe_definition_dispatches_stdio(probe_primitives):
    facts = probe.probe_definition(stdio_canonical("ok"), policy=FAST)
    assert facts["transport"] == "stdio"


def test_probe_definition_unknown_transport_refused():
    unknown = {"name": "t", "transport": {"sse": {"url": "http://127.0.0.1:1"}}}
    with pytest.raises(McpError) as refused:
        probe.probe_definition(unknown, policy=FAST)
    assert refused.value.code == "MCP_TRANSPORT_UNSUPPORTED"
