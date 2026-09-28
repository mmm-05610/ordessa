"""The Python transport must opt in before a controlled ACP peer can launch."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from ordessa_harness.server_acp.access_entry import AccessEntryTransport


ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plugins/harness/runtime/access-entry.mjs"
PEER = ROOT / "tests/acp_orchestration/fixtures/bidirectional_acp_peer.mjs"


def _transport(tmp_path: Path, *, controlled: bool) -> AccessEntryTransport:
    node = shutil.which("node")
    assert node is not None
    return AccessEntryTransport(
        node=node,
        entry=str(ENTRY),
        harness_id="pi",
        cwd=str(tmp_path),
        adapter={"command": node, "args": [str(PEER)]},
        on_line=lambda _line: None,
        on_exit=lambda _status: None,
        environment={**os.environ, "HD003_LOG": str(tmp_path / "peer")},
        controlled_test_peer=controlled,
    )


def test_orchestration_peer_is_refused_by_production_launch(tmp_path: Path) -> None:
    transport = _transport(tmp_path, controlled=False)
    with pytest.raises(RuntimeError, match="ACP_CHANNEL_CONNECT_REFUSED-ADAPTER_LAUNCH_MISMATCH"):
        transport.start()
    assert not list(tmp_path.glob("peer.*"))


def test_explicit_controlled_mode_connects_and_releases_the_peer(tmp_path: Path) -> None:
    transport = _transport(tmp_path, controlled=True).start()
    assert transport.established
    deadline = time.monotonic() + 3
    while not list(tmp_path.glob("peer.*")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert list(tmp_path.glob("peer.*")), "the controlled peer must really execute"
    released = transport.request_release()
    assert released["confirmed"] is True
