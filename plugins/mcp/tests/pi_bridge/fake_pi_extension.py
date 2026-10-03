"""A Python behavioural peer of the Pi bridge extension (**L2 witness only**).

This class replays, over a real loopback socket, exactly what
``adapters/pi/ordessa-mcp-bridge.ts`` does: env contract -> TCP connect to
the *host from the env, verified loopback* -> hello with the one-shot
token -> ready -> call/result -> bye. It is an in-test channel peer for
exercising the Python side end to end. It is **not** a loaded Pi
extension and nothing here may be reported as proof that Pi itself
loaded anything - the real-CLI evidence (or its honest absence) is the
job of ``real_pi_probe.py`` and ``specs/011-q4-mcp/reports/t10-pi-probe.md``.
"""
from __future__ import annotations

import json
import socket
from typing import Any, Optional


def _connect(env: dict, *, timeout: float = 5.0) -> socket.socket:
    host = env.get("ORDESSA_PI_BRIDGE_HOST")
    if host != "127.0.0.1":
        raise AssertionError(f"the bridge env must be loopback-only, got {host!r}")
    conn = socket.create_connection((host, int(env["ORDESSA_PI_BRIDGE_PORT"])),
                                    timeout=timeout)
    return conn


class FrameStream:
    """Line reader over a socket (newline-delimited JSON, shared shape)."""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn
        self._buf = b""

    def read(self, timeout: Optional[float] = None) -> Optional[dict]:
        if timeout is not None:
            self._conn.settimeout(timeout)
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                return json.loads(line.decode("utf-8"))
            try:
                chunk = self._conn.recv(65536)
            except (ConnectionResetError, socket.timeout):
                # a gate teardown can arrive as RST or as timeout; both mean
                # the channel is gone - the peer never invents a frame.
                return None
            if not chunk:
                return None
            self._buf += chunk

    def send(self, frame: dict) -> None:
        self._conn.sendall(
            (json.dumps(frame, separators=(",", ":")) + "\n").encode("utf-8"))


class FakePiExtension:
    """Scripted mirror of the managed extension's channel behaviour."""

    def __init__(self, env: dict) -> None:
        self.env = env
        self.conn: Optional[socket.socket] = None
        self.stream: Optional[FrameStream] = None
        self.tools: list = []
        self.ready: Optional[dict] = None

    # -- the honest path (what the extension does) -----------------------------

    def start(self, ready_timeout: float = 5.0) -> dict:
        self.conn = _connect(self.env)
        self.stream = FrameStream(self.conn)
        self.stream.send({
            "type": "hello", "proto": 1,
            "token": self.env["ORDESSA_PI_BRIDGE_TOKEN"], "pid": 0,
        })
        frame = self.stream.read(timeout=ready_timeout)
        if frame is None or frame.get("type") != "ready":
            raise AssertionError(f"expected a ready frame, got {frame!r}")
        self.ready = frame
        self.tools = [tool["name"] for tool in frame.get("tools", [])]
        return frame

    def call(self, tool: str, params: dict, call_id: str = "c-1") -> dict:
        assert self.stream is not None, "start() first"
        self.stream.send({"type": "call", "id": call_id, "tool": tool,
                          "params": params, "toolCallId": f"pi-{call_id}"})
        frame = self.stream.read(timeout=10.0)
        assert frame is not None and frame.get("id") == call_id, frame
        return frame

    def close(self) -> dict:
        assert self.stream is not None
        self.stream.send({"type": "bye"})
        self.conn.close()
        return {"sent": "bye"}

    # -- adversarial plumbing for the counterexamples ---------------------------

    @classmethod
    def raw(cls, env: dict, *, timeout: float = 5.0) -> "FakePiExtension":
        peer = cls(env)
        peer.conn = _connect(env, timeout=timeout)
        peer.stream = FrameStream(peer.conn)
        return peer

    def send_raw(self, frame: Any) -> None:
        assert self.stream is not None
        self.stream.send(frame if isinstance(frame, dict) else frame)

    def send_text(self, text: str) -> None:
        assert self.conn is not None
        self.conn.sendall(text.encode("utf-8"))

    def read(self, timeout: float = 5.0) -> Optional[dict]:
        assert self.stream is not None
        return self.stream.read(timeout=timeout)
