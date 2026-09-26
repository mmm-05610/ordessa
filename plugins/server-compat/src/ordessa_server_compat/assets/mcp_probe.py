"""Order 58 G6: one bounded, cancellable MCP handshake probe.

The probe answers exactly one question - "does this stdio server start and
answer an initialize request" - and it is shaped like order 55's endpoint
probes: a hard timeout, a hard response bound, a typed refusal per failure
mode, **no credential material** in the environment it hands the child, no
config writes anywhere, and no model call of any kind. Anything the server
prints beyond the first bounded line is discarded, and the child is killed on
every exit path.
"""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from typing import Any, Mapping, Sequence


class McpProbeError(RuntimeError):
    """A typed refusal of one probe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _initialize_request() -> bytes:
    return (json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "capabilities": {},
                   "clientInfo": {"name": "agent-box-probe", "version": "1"}},
    }, sort_keys=True) + "\n").encode("utf-8")


def probe_stdio(
    command: str, *, args: Sequence[str] = (), timeout: float = 5.0,
    max_bytes: int = 64 * 1024,
) -> dict[str, Any]:
    """Start one stdio server, read one initialize answer, kill it.

    Returns ``{"status": "ok", "serverName": ..., "serverVersion"?,
    "protocolVersion"?}`` on success. Every failure mode is typed:
    ``PROBE_SPAWN_FAILED`` / ``PROBE_TIMEOUT`` / ``PROBE_FORMAT_INVALID`` /
    ``PROBE_RESPONSE_TOO_LARGE``. The environment is minimal on purpose: the
    probe never proves a server works *with credentials*, only that it answers.
    """
    if not isinstance(command, str) or not command.startswith("/"):
        raise McpProbeError("PROBE_COMMAND_INVALID", "the command must be an absolute path")
    if any(not isinstance(item, str) or "\x00" in item for item in args):
        raise McpProbeError("PROBE_COMMAND_INVALID", "arguments must be plain strings")
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp"}
    try:
        process = subprocess.Popen(  # noqa: S603 - the caller stored this command
            [command, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True,
        )
    except OSError as exc:
        raise McpProbeError("PROBE_SPAWN_FAILED", f"the server did not start: {exc}") from exc

    deadline = time.monotonic() + timeout
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(_initialize_request())
        process.stdin.flush()
        collected = bytearray()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while b"\n" not in collected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise McpProbeError("PROBE_TIMEOUT", "the server did not answer in time")
                if not selector.select(timeout=remaining):
                    raise McpProbeError("PROBE_TIMEOUT", "the server did not answer in time")
                chunk = process.stdout.read1(min(4096, max_bytes + 1 - len(collected)))
                if not chunk:
                    raise McpProbeError(
                        "PROBE_FORMAT_INVALID", "the server closed before answering")
                collected.extend(chunk)
                if len(collected) > max_bytes:
                    raise McpProbeError(
                        "PROBE_RESPONSE_TOO_LARGE", "the answer exceeds the read bound")
        finally:
            selector.close()
        line = bytes(collected).split(b"\n", 1)[0]
        try:
            response = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise McpProbeError(
                "PROBE_FORMAT_INVALID", "the first line is not a JSON-RPC object") from exc
        result = response.get("result") if isinstance(response, dict) else None
        if not isinstance(result, dict):
            raise McpProbeError("PROBE_FORMAT_INVALID", "the answer carries no result object")
        info = result.get("serverInfo") if isinstance(result.get("serverInfo"), dict) else {}
        facts: dict[str, Any] = {
            "status": "ok",
            "serverName": info.get("name"),
            "serverVersion": info.get("version"),
            "protocolVersion": result.get("protocolVersion"),
        }
        return facts
    finally:
        _shutdown(process)


def _shutdown(process: subprocess.Popen) -> None:
    """Kill the probe's child on every exit path, session included."""
    try:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if process.poll() is None:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
