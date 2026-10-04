"""Consumer-side transport seam for harness native channels.

Frozen in N001 (night-harness-expansion/seams.md); family clients consume it
read-only. It speaks raw protocol framing only — it never interprets harness
semantics and never retries.

Invariants enforced here (see specs/030-native-harness-expansion/acceptance.md):

- G4 unknown preservation: messages the consumer does not recognise are
  surfaced verbatim, never dropped, never rewritten.
- G5 framing: frames are byte-terminated on b"\\n" only (U+2028/U+2029 are not
  separators), decoded with an incremental UTF-8 decoder so multi-byte
  characters may split across reads, bounded by a frame size cap; stderr is
  diagnostics and is never parsed as protocol.
- G6 lifecycle: an owned subprocess is cleaned up by identity, never by name.
- G11 lost receipt: a request that was written but never answered surfaces as
  LostReceipt (outcome unknown); nothing here ever re-sends.
"""

from __future__ import annotations

import codecs
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MAX_FRAME_BYTES = 8 * 1024 * 1024
JSONRPC_VERSION = "2.0"

#: Environment keys never inherited into an isolated launch (G12).
_TOKEN_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MOONSHOT_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "MISTRAL_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "COPILOT_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_API_KEY",
)


class ChannelFailure(Exception):
    """Typed transport failure. Callers must not blanket-retry these."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class FramingError(ChannelFailure):
    """Frame stream violated the framing contract (G5)."""

    def __init__(self, detail: str):
        super().__init__("FRAMING_ERROR", detail)


class RemoteFailure(ChannelFailure):
    """The peer answered with a JSON-RPC error object."""

    def __init__(self, detail: str, *, code: Any = None, data: Any = None):
        super().__init__("REMOTE_ERROR", detail)
        self.remote_code = code
        self.remote_data = data


class ChannelClosed(ChannelFailure):
    """Channel is closed before the request was written."""

    def __init__(self, detail: str = "channel closed"):
        super().__init__("CHANNEL_CLOSED", detail)


class LostReceipt(ChannelFailure):
    """Request was written but no receipt arrived; outcome is unknown (G11)."""

    def __init__(self, method: str, request_id: Any, detail: str = "sent without receipt"):
        super().__init__("LOST_RECEIPT", f"{method}#{request_id}: {detail}")
        self.method = method
        self.request_id = request_id


class RequestTimeout(ChannelFailure):
    """Deadline elapsed while waiting. The attempt outcome is unknown; never
    re-issue from here (G11)."""

    def __init__(self, method: str, request_id: Any, timeout: float):
        super().__init__("REQUEST_TIMEOUT", f"{method}#{request_id} after {timeout}s")
        self.method = method
        self.request_id = request_id
        self.timeout = timeout


@dataclass(frozen=True)
class Message:
    """One decoded protocol message. ``raw`` is preserved verbatim (G4)."""

    raw: Mapping[str, Any]

    @property
    def kind(self) -> str:
        if "method" in self.raw and "id" in self.raw:
            return "request"
        if "method" in self.raw:
            return "notification"
        return "response"

    @property
    def method(self) -> str | None:
        value = self.raw.get("method")
        return value if isinstance(value, str) else None

    @property
    def id(self) -> Any:
        return self.raw.get("id")


class FrameReader:
    """Byte-safe line framing for protocol streams (G5)."""

    def __init__(self, *, max_frame_bytes: int = MAX_FRAME_BYTES):
        self._max = max_frame_bytes
        self._buffer = bytearray()
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def feed(self, data: bytes) -> list[str]:
        """Consume bytes, return every complete frame decoded so far.

        Raises FramingError on oversize frames, invalid UTF-8 or a truncated
        final frame at EOF (via :meth:`close`).
        """
        self._buffer += data
        frames: list[str] = []
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                if len(self._buffer) > self._max:
                    raise FramingError(f"frame exceeded {self._max} bytes")
                break
            if index > self._max:
                raise FramingError(f"frame exceeded {self._max} bytes")
            chunk = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            frames.append(self._decode(chunk.rstrip(b"\r")))
        return frames

    def close(self) -> None:
        """EOF. Any undecoded remainder is a truncated frame (G5 counter-example:
        silently accepting a half frame would corrupt the message boundary)."""
        if self._buffer:
            raise FramingError("truncated frame at EOF")
        tail = self._decoder.decode(b"", final=True)
        if tail:
            raise FramingError("truncated UTF-8 sequence at EOF")

    def _decode(self, chunk: bytes) -> str:
        try:
            return self._decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise FramingError(f"invalid UTF-8 in frame: {exc.reason}") from exc


def isolated_env(
    home: str,
    *,
    path: str | None = None,
    extra: Mapping[str, str] | None = None,
    inherit: Sequence[str] = (),
) -> dict[str, str]:
    """Build a clean launch environment rooted at ``home`` (G12).

    Only explicitly listed keys are inherited, and inheritance never overrides
    the pinned identity keys (HOME/XDG/TMPDIR/LANG/LC_ALL) — a family that
    really needs a different value passes it through ``extra``. Token-shaped
    keys are dropped even when listed. No user login home, no credentials.
    """
    resolved_home = os.path.abspath(home)
    env: dict[str, str] = {
        "HOME": resolved_home,
        "XDG_CONFIG_HOME": os.path.join(resolved_home, "config"),
        "XDG_DATA_HOME": os.path.join(resolved_home, "data"),
        "XDG_STATE_HOME": os.path.join(resolved_home, "state"),
        "XDG_CACHE_HOME": os.path.join(resolved_home, "cache"),
        "TMPDIR": os.path.join(resolved_home, "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }
    pinned = set(env)
    env["PATH"] = path if path is not None else os.environ.get("PATH", "/usr/bin:/bin")
    for key in inherit:
        if key in _TOKEN_ENV_KEYS or key in pinned:
            continue
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for key in _TOKEN_ENV_KEYS:
        env.pop(key, None)
    if extra:
        for key, value in extra.items():
            if key in _TOKEN_ENV_KEYS:
                continue
            env[key] = value
    return env


@dataclass(frozen=True)
class LaunchSpec:
    """A fully resolved, isolated launch for one owned subprocess."""

    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str]

    @classmethod
    def build(
        cls,
        argv: Sequence[str],
        *,
        home: str,
        cwd: str,
        path: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        inherit: Sequence[str] = (),
    ) -> "LaunchSpec":
        return cls(
            argv=tuple(argv),
            cwd=os.path.abspath(cwd),
            env=isolated_env(home, path=path, extra=extra_env, inherit=inherit),
        )


class ProcessChannel:
    """JSON-RPC channel over an owned subprocess (stdio protocol / stderr
    diagnostics). Cleanup targets only this owned process (G8)."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        name: str,
        max_frame_bytes: int = MAX_FRAME_BYTES,
    ):
        self._process = process
        self.name = name
        self._reader = FrameReader(max_frame_bytes=max_frame_bytes)
        self._inbox: list[Message] = []
        self._inflight: dict[Any, str] = {}
        self._next_id = 0
        self._closed = False
        self._eof = False
        self._stderr_tail = bytearray()

    # -- construction -------------------------------------------------
    @classmethod
    def launch(cls, spec: LaunchSpec, *, name: str) -> "ProcessChannel":
        for directory in {spec.cwd, spec.env.get("HOME", spec.cwd)}:
            os.makedirs(directory, exist_ok=True)
        process = subprocess.Popen(  # noqa: S603 - argv is caller-resolved
            list(spec.argv),
            cwd=spec.cwd,
            env=dict(spec.env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return cls(process, name=name)

    # -- protocol I/O --------------------------------------------------
    def send_raw(self, payload: Mapping[str, Any]) -> None:
        self._ensure_open()
        frame = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        data = frame.encode("utf-8")
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(data)
            self._process.stdin.flush()
        except BrokenPipeError as exc:
            raise ChannelClosed("pipe closed while writing") from exc

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 10.0,
        on_request: Any = None,
    ) -> Any:
        """Send one request and wait for its response.

        ``on_request(channel, message)`` handles peer→client requests (approval
        callbacks) that arrive while waiting; without it they queue in the
        inbox untouched, so native identity is preserved either way (G4).
        Nothing here ever re-sends the request (G11).
        """
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        self.send_raw(payload)
        self._inflight[request_id] = method  # written; a lost receipt stays unknown
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout(method, request_id, timeout)
            try:
                message = self.next_message(timeout=remaining)
            except (ChannelClosed, FramingError) as exc:
                # Sent but never answered: outcome unknown, never re-sent (G11).
                raise LostReceipt(method, request_id, f"transport failure after send: {exc}") from exc
            if message.kind == "request" and on_request is not None:
                on_request(self, message)
                continue
            if message.id == request_id and message.kind == "response":
                del self._inflight[request_id]
                error = message.raw.get("error")
                if error is not None:
                    raise RemoteFailure(
                        str(error.get("message", error)),
                        code=error.get("code"),
                        data=error.get("data"),
                    )
                return message.raw.get("result")
            self._inbox.append(message)

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
        if params is not None:
            payload["params"] = params
        self.send_raw(payload)

    def reply(self, request_id: Any, result: Any) -> None:
        self.send_raw({"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result})

    def reply_error(self, request_id: Any, *, code: int, message: str, data: Any = None) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self.send_raw({"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error})

    def next_message(self, *, timeout: float = 10.0) -> Message:
        """Next server→client message in arrival order (unknown preserved).

        A closed channel stays closed: reads after :meth:`close` raise
        :class:`ChannelClosed` even when buffered frames remain (drain first;
        preserved records live in the client's own event lists).
        """
        self._ensure_open()
        if self._inbox:
            return self._inbox.pop(0)
        deadline = time.monotonic() + timeout
        assert self._process.stdout is not None
        while True:
            if self._eof:
                raise ChannelClosed("peer closed the protocol stream")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("<stream>", None, timeout)
            ready = _wait_readable(self._process.stdout, remaining)
            if not ready:
                raise RequestTimeout("<stream>", None, timeout)
            chunk = os.read(self._process.stdout.fileno(), 65536)
            if not chunk:
                self._eof = True
                self._drain_stderr()
                self._reader.close()
                raise ChannelClosed("peer closed the protocol stream")
            frames = self._reader.feed(chunk)
            if frames:
                messages = [self._decode_frame(frame) for frame in frames]
                first, *rest = messages
                self._inbox.extend(rest)
                return first

    def poll_message(self, *, timeout: float = 0.0) -> Message | None:
        try:
            return self.next_message(timeout=timeout)
        except (RequestTimeout, ChannelClosed):
            return None

    def drain(self) -> list[Message]:
        """Interleaved messages collected while a request was in flight."""
        collected = list(self._inbox)
        self._inbox.clear()
        return collected

    @property
    def inflight(self) -> dict[Any, str]:
        return dict(self._inflight)

    def stderr_tail(self) -> str:
        self._drain_stderr()
        return self._stderr_tail.decode("utf-8", errors="replace")[-4096:]

    def sigint(self) -> None:
        """Send SIGINT to the owned subprocess (documented turn-end for some
        families). Only the owned process is signalled (G8); the exit evidence
        stays observable via :meth:`close`."""
        import signal

        self._ensure_open()
        if self._process.poll() is None:
            self._process.send_signal(signal.SIGINT)

    # -- lifecycle ------------------------------------------------------
    def close(self, *, timeout: float = 5.0) -> int:
        """Release the owned subprocess only (G8). Pending requests become
        LostReceipt; nothing is re-sent."""
        if self._closed:
            return self._process.returncode if self._process.returncode is not None else -1
        self._closed = True
        exit_code: int
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            exit_code = self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                exit_code = self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                exit_code = self._process.wait(timeout=timeout)
        self._drain_stderr()
        return exit_code

    # -- internals ------------------------------------------------------
    def _ensure_open(self) -> None:
        if self._closed:
            raise ChannelClosed("channel already closed")

    def _decode_frame(self, frame: str) -> Message:
        try:
            payload = json.loads(frame)
        except ValueError as exc:
            raise FramingError(f"frame is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise FramingError("protocol frame must be a JSON object")
        return Message(raw=payload)

    def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            os.set_blocking(self._process.stderr.fileno(), False)
            while True:
                chunk = os.read(self._process.stderr.fileno(), 65536)
                if not chunk:
                    break
                self._stderr_tail += chunk
        except (BlockingIOError, OSError):
            pass


def _wait_readable(stream: Any, timeout: float) -> bool:
    import select

    readable, _, _ = select.select([stream], [], [], max(timeout, 0.0))
    return bool(readable)
