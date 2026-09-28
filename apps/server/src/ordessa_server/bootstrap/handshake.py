"""C-02 §3.1 — the one handoff that tells the host which port it really got.

The Server binds its own socket, so the port is a fact the Server observes
and the host has to be told. This module owns that one sentence and nothing
else: after the socket is bound, one line of JSON goes to the stdout the
host spawned, and every other line of Server output goes to
`$DATA_ROOT/logs/server.log` (C-04). Mixing a log line into this stream
would make "the first line is the handshake" untrue, so the emitter flushes
and is called from exactly one place.

There is deliberately no second mechanism. C-02 §3.1 allows an
`instance.json` variant only for platforms without a usable stdout, and
"implement one, not both" is cheaper to keep true than to police later.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import sys
from typing import Any, TextIO

from .data_root import LAYOUT

#: The event name the host waits for; the host refuses any other line.
LISTENING_EVENT: str = LAYOUT["launch"]["handshakeEvent"]

#: `http://127.0.0.1:<port>` and nothing else — the same shape the TypeScript
#: side accepts, so the two never disagree about what a handshake is.
_LOOPBACK_ORIGIN = re.compile(r"http://127\.0\.0\.1:\d+")


@dataclass(frozen=True)
class ListeningHandshake:
    """The facts the host needs to address THIS Server process."""

    origin: str
    server_id: str
    pid: int

    def as_line(self) -> str:
        """One line, no trailing newline: the host reads lines, not records."""
        payload: "dict[str, Any]" = {
            "event": LISTENING_EVENT,
            "origin": self.origin,
            "serverId": self.server_id,
            "pid": self.pid,
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def parse_listening_line(line: str) -> "ListeningHandshake | None":
    """Read a candidate handshake line, or answer None if it is not one.

    The host treats "not a well-formed listening line" as
    `SERVER_HANDSHAKE_MALFORMED` rather than as a timeout, so this returns
    a strict answer: any extra key, a non-loopback origin, a missing field
    or unparsable JSON is None. Nothing here raises into the host's face.
    """
    try:
        payload = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("event") != LISTENING_EVENT:
        return None
    if set(payload) != {"event", "origin", "serverId", "pid"}:
        return None
    origin, server_id, pid = payload["origin"], payload["serverId"], payload["pid"]
    if not isinstance(origin, str) or not isinstance(server_id, str) or not server_id:
        return None
    # The origin must be the loopback address this process bound. Accepting a
    # routable host here would let a tampered line point the host at another
    # machine, so the shape is checked, not trusted.
    if not _LOOPBACK_ORIGIN.fullmatch(origin):
        return None
    if type(pid) is not int or pid <= 0:
        return None
    return ListeningHandshake(origin=origin, server_id=server_id, pid=pid)


def emit_listening_handshake(
    handshake: ListeningHandshake, stream: "TextIO | None" = None
) -> None:
    """Write the single handshake line and flush it.

    Flushing is not tidiness: a host blocked in `probing` on a pipe that
    Python has not flushed yet would read a timeout for a Server that is
    already listening. A broken stdout (the Server was started detached
    with no reader) is not fatal — the process still serves; the host just
    learns the port the usual way it spawns anything else.
    """
    target = sys.stdout if stream is None else stream
    try:
        target.write(handshake.as_line() + "\n")
        target.flush()
    except (OSError, ValueError):  # pragma: no cover - depends on the spawn shape
        pass


def loopback_origin(port: int) -> str:
    """`http://127.0.0.1:<port>` — the origin and nothing else.

    The connectors refuse an origin carrying a path, a query, a fragment or
    credentials, so this builds the one spelling they accept instead of
    letting a caller hand-assemble one.
    """
    return f"http://127.0.0.1:{port}"


def current_pid() -> int:
    return os.getpid()
