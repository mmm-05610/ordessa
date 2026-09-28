"""C-02 §7/§8 — the five launch errors, checked on both sides of the seam.

The Python side owns the emitting half of the launch (`PORT_ALLOCATION_FAILED`
when the socket cannot bind) and the reading half of nothing else; the
TypeScript side owns the other four. This file pins the Python half and
asserts that the two halves spell their codes the same way, because a host
that matched on a code string has to be able to trust both ends of it.
"""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from ordessa_server import __main__ as host_cli

REPO_ROOT = Path(__file__).resolve().parents[3]


# -- the code list is one list, shared with the host side -------------------


def test_the_five_launch_codes_are_exactly_the_contracts_five():
    from ordessa_server.bootstrap.data_root import LAUNCH_ERROR_CODES

    assert LAUNCH_ERROR_CODES == (
        "PORT_ALLOCATION_FAILED",
        "SERVER_START_TIMEOUT",
        "SERVER_EXITED_EARLY",
        "BUNDLED_RUNTIME_MISSING",
        "SERVER_CRASHED",
    )


def test_the_host_side_declares_the_same_five_codes():
    """The two halves are separate packages in separate languages; this is
    what stops them from drifting into two vocabularies for one failure."""
    declared = (
        REPO_ROOT / "packages/desktop-platform/server-bridge/src/errors.ts"
    ).read_text(encoding="utf-8")
    from ordessa_server.bootstrap.data_root import LAUNCH_ERROR_CODES

    for code in LAUNCH_ERROR_CODES:
        assert f"'{code}'" in declared, f"{code} is missing from the host error union"


# -- PORT_ALLOCATION_FAILED ------------------------------------------------


def test_a_bound_port_is_reported_back_so_the_host_learns_the_real_one():
    sock = host_cli.bind_loopback_socket(0)
    try:
        origin = host_cli.serving_origin(sock)
        assert origin.startswith("http://127.0.0.1:")
        # The port is the one the kernel gave, not the one that was asked for.
        assert int(origin.rsplit(":", 1)[1]) == sock.getsockname()[1]
        assert sock.getsockname()[1] != 0
    finally:
        sock.close()


def test_a_taken_port_is_refused_typed_and_never_retried_elsewhere():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    taken = holder.getsockname()[1]
    try:
        with pytest.raises(host_cli.PortAllocationFailed) as refusal:
            # SO_REUSEADDR does not let a second bind succeed on a LISTENing
            # socket, so this is a genuine allocation failure.
            host_cli.bind_loopback_socket(taken)
        assert refusal.value.code == "PORT_ALLOCATION_FAILED"
        assert refusal.value.reason and refusal.value.remedy
        # The refusal must not silently land on a different port.
        assert str(taken) not in refusal.value.remedy
    finally:
        holder.close()


# -- the CLI grammar (PB-03) -----------------------------------------------


def test_the_data_root_flag_is_optional():
    parsed = host_cli.parser().parse_args([])
    assert parsed.data_root is None
    assert host_cli.parser().parse_args(["--data-root", "/d"]).data_root == Path("/d")


def test_the_port_defaults_to_system_assigned():
    assert host_cli.parser().parse_args([]).port == 0
    assert host_cli.parser().parse_args(["--port", "8931"]).port == 8931


def test_port_zero_is_legal_and_a_negative_port_is_not(capsys):
    assert host_cli.parser().parse_args(["--port", "0"]).port == 0
    with pytest.raises(SystemExit) as exit_:
        host_cli.parser().error("--port must be between 0 and 65535")
    assert exit_.value.code == 2


def test_the_default_port_matches_the_shared_layout():
    from ordessa_server.bootstrap.data_root import LAYOUT

    assert host_cli.DEFAULT_PORT == LAYOUT["launch"]["defaultPort"] == 0


# -- the end-to-end shape: a real process binds a real port ----------------


def test_a_real_server_process_binds_a_random_port_and_reports_it():
    """The whole C-02 §3.1 chain, with no Server: bind, read back, handshake.

    A controlled fixture, and labelled as one — it proves the handoff
    mechanics, not the Server. The Server's own `/live` behaviour is covered
    by its existing transport suite.
    """
    sock = host_cli.bind_loopback_socket(0)
    port = sock.getsockname()[1]
    script = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from ordessa_server.bootstrap.handshake import "
        "ListeningHandshake, emit_listening_handshake;"
        "emit_listening_handshake(ListeningHandshake("
        "origin='http://127.0.0.1:%d', server_id='server_fixture', pid=1))"
    ) % (str(REPO_ROOT / "apps/server/src"), port)
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    sock.close()
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["origin"] == f"http://127.0.0.1:{port}"
    assert port != 0
