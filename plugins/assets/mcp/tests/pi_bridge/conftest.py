"""Fixtures for the Q4 T10 Pi managed-lane bridge tests.

The Pi side of this lane is an *extension*: executable code loaded by a
real Pi process. This directory never pretends otherwise - the two proof
levels here are explicit:

* **L2 (Python peer)**: :mod:`fake_pi_extension.FakePiExtension` is an
  in-test Python peer that mimics the *behaviour* of
  ``adapters/pi/ordessa-mcp-bridge.ts`` (hello/ready/call/bye over a real
  loopback socket). It is a channel peer, **not** a loaded Pi extension;
  the real-CLI loading evidence lives in
  ``specs/011-q4-mcp/reports/t10-pi-probe.md`` and no test here claims it.
* **source-scan**: :mod:`test_source_scan` reads the actual extension
  source and mechanically rejects any construction that could dial a
  non-loopback address or speak MCP directly.

Primitive lockdown: like ``tests/managed_client``, this directory really
uses loopback sockets (the bridge channel is a socket by nature), so the
package-level autouse lockdown is *explicitly lifted* here - re-binding
the real ``socket``/``Popen`` entry points and nothing else. No test here
spawns a process; sockets are loopback-only.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_TESTS = _HERE.parent
for _directory in (_HERE, _TESTS / "managed"):
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

# Captured at import time, before any monkeypatch can be in effect.
_REAL_SOCKET = socket.socket
_REAL_POPEN = subprocess.Popen
_REAL_RUN = subprocess.run
_REAL_CALL = subprocess.call


@pytest.fixture(autouse=True)
def bridge_primitives(monkeypatch, no_side_effect_primitives):
    """Lift the lockdown for the channel tests; the autouse guard ran first."""
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(subprocess, "Popen", _REAL_POPEN)
    monkeypatch.setattr(subprocess, "run", _REAL_RUN)
    monkeypatch.setattr(subprocess, "call", _REAL_CALL)


from managed_helpers import TOOLS_TWO, ALLOWING, ManagedHarness  # noqa: E402
from backend.managed.pi_bridge import bind_bridge  # noqa: E402

#: the bridge-visible subset for the standard fixture: only "echo" is
#: approved; "list" exists in the catalog but must never be registerable.
BRIDGE_TOOLS = [tool for tool in TOOLS_TWO if tool["name"] == "echo"]


@dataclass
class LiveBridge:
    """A started :class:`PiBridgeServer` on a live, approved lease."""
    harness: ManagedHarness
    manager: object
    caller: object
    owner_id: str
    lease_id: str
    server: object

    def tools(self):
        return self.server.bridge.tools

    def close(self):
        return self.server.close()


@pytest.fixture
def live(tmp_path) -> LiveBridge:
    """install -> lease -> connect -> observe -> approve("echo") -> bridge up."""
    harness = ManagedHarness(tmp_path)
    revision = harness.install_remote()
    harness.factory.set("sess-a", "srv-a", tools=TOOLS_TWO)
    manager = harness.manager(authority=ALLOWING())
    caller = harness.caller()
    lease, _catalog, _client = harness.bring_up(manager, caller, "srv-a", revision)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    server = bind_bridge(
        manager=manager, caller=caller, owner_id=lease.owner_id,
        lease_id=lease.lease_id, tools=[dict(tool) for tool in BRIDGE_TOOLS],
        bridge_id="pib-test", audit_sink=harness.sink)
    return LiveBridge(harness=harness, manager=manager, caller=caller,
                      owner_id=lease.owner_id, lease_id=lease.lease_id,
                      server=server)
