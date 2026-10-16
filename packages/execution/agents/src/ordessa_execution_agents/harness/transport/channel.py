"""Provider-side transport seam for harness native channels.

Frozen in N001 (night-harness-expansion/seams.md); family clients consume it
read-only. It speaks raw protocol framing only — it never interprets harness
semantics and never retries.

Invariants enforced here (see docs/implementation/specifications/030-native-harness-expansion/acceptance.md):

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

import json
import math
import os
import subprocess
import time
from threading import RLock
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from .ndjson import WriterLease, WriterLeaseRefused
from ordessa_infrastructure.process.framing import (
    MAX_FRAME_BYTES, ChannelFailure, FrameReader, FramingError, Message,
)
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
    "AWS_ACCESS_KEY_ID",
    "AZURE_API_KEY",
    "COPILOT_GITHUB_TOKEN",
    "COPILOT_SDK_AUTH_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "NETRC",
    "SSH_AUTH_SOCK",
    "KIMI_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "MISTRAL_API_KEY",
    "VIBE_API_KEY",
    "GOOSE_API_KEY",
)


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
        managed: bool = False,
    ):
        if type(managed) is not bool:
            raise ValueError('managed must be an explicit boolean')
        self._process = process
        self.name = name
        self._reader = FrameReader(max_frame_bytes=max_frame_bytes)
        self._inbox: list[Message] = []
        self._inflight: dict[Any, str] = {}
        self._prepared_inflight = {}  # actual written frame IDs and original writer, not durable truth
        self._next_id = 0
        self._closed = False
        self._eof = False
        self._stderr_tail = bytearray()
        self._managed = managed
        self._write_lock = RLock()
        self._active_writer = None
        self._writer_epoch = 0
        self._unresolved = False

    # -- construction -------------------------------------------------
    @classmethod
    def launch(cls, spec: LaunchSpec, *, name: str, managed=False) -> "ProcessChannel":
        if type(managed) is not bool:
            raise ValueError('managed must be an explicit boolean')
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
        return cls(process, name=name, managed=managed)

    @classmethod
    def attach(cls, process_handle, *, name: str, managed=False) -> "ProcessChannel":
        """Attach the frozen async ProcessHandle; never require host descriptors."""
        from .environment_channel import EnvironmentProcessChannel
        return EnvironmentProcessChannel(process_handle, name=name, managed=managed)

    def _process_running(self):
        return self._process.poll() is None

    # -- protocol I/O --------------------------------------------------
    def send_raw(self, payload: Mapping[str, Any]) -> None:
        if self._managed:
            raise WriterLeaseRefused('managed channel requires a writer lease')
        self._send(payload,None)

    def _validate_writer(self, lease):
        if (not self._managed or type(lease) is not WriterLease
                or self._active_writer is not lease or lease.epoch != self._writer_epoch
                or self._unresolved or self._closed or self._eof or not self._process_running()):
            raise WriterLeaseRefused('writer is absent, revoked, unresolved or disconnected')

    def acquire_writer(self):
        with self._write_lock:
            if (not self._managed or self._active_writer is not None or self._unresolved
                    or self._closed or self._eof or not self._process_running()):
                raise WriterLeaseRefused('writer unavailable')
            lease=object.__new__(WriterLease)
            object.__setattr__(lease,'_epoch',self._writer_epoch)
            self._active_writer=lease
            return lease

    def fence_all(self):
        with self._write_lock:
            if not self._managed:
                raise WriterLeaseRefused('writer fencing requires managed mode')
            if self._prepared_inflight:
                self._unresolved = True
            self._active_writer=None
            self._writer_epoch+=1
            return self._writer_epoch

    def fence_writer(self, lease):
        with self._write_lock:
            self._validate_writer(lease)
            return self.fence_all()

    def mark_unresolved(self, lease):
        with self._write_lock:
            self._validate_writer(lease)
            self._unresolved=True
            self.fence_all()

    def bind_writer(self, lease):
        with self._write_lock:
            self._validate_writer(lease)
            return LeaseBoundChannel(self,lease)

    def send_raw_for(self, lease, payload):
        self._send(payload,lease)

    def send_frame(self, frame_bytes, *, before_write):
        """One already frozen native frame, with the guard at the write barrier."""
        self._send_frame(frame_bytes, None, before_write=before_write)

    def _send_frame(self, frame_bytes, lease, *, before_write):
        if not callable(before_write):
            raise ValueError('explicit native write guard required')
        if (not isinstance(frame_bytes, bytes) or not frame_bytes.endswith(b'\n')
                or b'\n' in frame_bytes[:-1] or b'\r' in frame_bytes):
            raise FramingError('native frame must be one complete UTF-8 JSONL record')
        if len(frame_bytes) - 1 > self._reader._max:
            raise FramingError('native frame exceeds byte limit')
        native = self._decode_frame(self._reader._decode(frame_bytes[:-1])).raw
        request_id = native.get('id')
        if type(request_id) not in (str, int) or isinstance(request_id, str) and not request_id:
            raise FramingError('frozen native request must carry its original ID')
        request_key = type(request_id).__name__, request_id
        with self._write_lock:
            self._ensure_open()
            if self._managed:
                self._validate_writer(lease)
            if self._unresolved:
                raise WriterLeaseRefused('original input remains unresolved')
            if request_key in self._prepared_inflight:
                raise WriterLeaseRefused('original native request ID remains pending')
            try:
                before_write()
                # Guard callbacks can revoke the same writer under this RLock.
                if self._managed:
                    self._validate_writer(lease)
                self._ensure_open()
                if self._unresolved:
                    raise WriterLeaseRefused('original input remains unresolved')
            except BaseException:
                # The original valid writer reached this admitted attempt's
                # guard. Fence here before releasing the barrier: afterwards
                # a revoked view cannot latch unknown on its old lease.
                self._unresolved = True
                if self._managed:
                    self.fence_all()
                raise
            assert self._process.stdin is not None
            self._prepared_inflight[request_key] = lease
            try:
                count = self._process.stdin.write(frame_bytes)
                if count != len(frame_bytes):
                    raise OSError('partial delivery')
                self._process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                self._unresolved = True
                if self._managed:
                    self.fence_all()
                raise ChannelClosed('native write lost; partial delivery possible, outcome unknown') from None
            except BaseException:
                self._unresolved = True
                if self._managed:
                    self.fence_all()
                raise

    def acknowledge_frame(self, request_id):
        self._acknowledge_frame(request_id, None)

    def _acknowledge_frame(self, request_id, lease):
        """Trusted family verified its original RPC receipt, not task completion.

        A late known receipt removes live IO metadata only. It never clears an
        unknown latch or grants a replacement writer after a revocation.
        """
        if type(request_id) not in (str, int) or isinstance(request_id, str) and not request_id:
            raise ValueError('original native request ID required')
        with self._write_lock:
            key = type(request_id).__name__, request_id
            if key not in self._prepared_inflight or self._prepared_inflight[key] is not lease:
                raise WriterLeaseRefused('receipt differs from original actual writer')
            del self._prepared_inflight[key]

    def mark_input_unknown(self):
        """Unmanaged compatibility cut; managed writers use their bound view."""
        with self._write_lock:
            if self._managed:
                raise WriterLeaseRefused('managed unknown cut requires original writer lease')
            self._unresolved = True

    def _send(self,payload,lease):
        if not isinstance(payload,Mapping):
            raise FramingError('native frame must be a JSON object')
        try:
            data=(json.dumps(dict(payload),ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')
        except (ValueError,UnicodeError,TypeError):
            raise FramingError('native frame must be finite UTF-8 JSON') from None
        if len(data)-1 > self._reader._max:
            raise FramingError('native frame exceeds byte limit')
        with self._write_lock:
            self._ensure_open()
            if self._managed: self._validate_writer(lease)
            if self._unresolved:
                raise WriterLeaseRefused('original input remains unresolved')
            assert self._process.stdin is not None
            try:
                count=self._process.stdin.write(data)
                if count != len(data):
                    raise OSError('partial delivery')
                self._process.stdin.flush()
            except (BrokenPipeError,OSError,ValueError):
                if self._managed:
                    self._unresolved=True
                    self.fence_all()
                raise ChannelClosed('native write lost; partial delivery possible, outcome unknown') from None

    def request(self,method,params=None,*,timeout=10.0,on_request=None):
        return self._request(method,params,timeout=timeout,on_request=on_request,lease=None)

    def _request(self,method,params=None,*,timeout=10.0,on_request=None,lease=None):
        self._next_id+=1
        request_id=self._next_id
        payload={"jsonrpc":JSONRPC_VERSION,"id":request_id,"method":method}
        if params is not None: payload['params']=params
        self._send(payload,lease)
        self._inflight[request_id]=method
        deadline=time.monotonic()+timeout
        deferred=[]
        try:
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0: raise RequestTimeout(method,request_id,timeout)
                try:
                    message=self.next_message(timeout=remaining)
                except (ChannelClosed,FramingError) as exc:
                    raise LostReceipt(method,request_id,'transport failed after native send') from exc
                if message.kind=='request' and on_request is not None:
                    on_request(self if lease is None else self.bind_writer(lease),message)
                    continue
                if message.id==request_id and message.kind=='response':
                    del self._inflight[request_id]
                    error=message.raw.get('error')
                    if error is not None:
                        raise RemoteFailure(str(error.get('message',error)),code=error.get('code'),data=error.get('data'))
                    return message.raw.get('result')
                # Keep interleaved frames separately until the request ends;
                # immediately requeuing would consume the same frame forever.
                deferred.append(message)
        except (RequestTimeout,LostReceipt):
            if self._managed:
                with self._write_lock:
                    self._unresolved=True
                    self.fence_all()
            raise
        finally:
            self._inbox=deferred+self._inbox

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
                with self._write_lock:
                    self._eof = True
                    if self._managed:
                        self._unresolved=True
                        self.fence_all()
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
        with self._write_lock:
            if self._closed:
                code = self._process.poll()
                return code if code is not None else -1
            self._closed = True
            if self._managed: self.fence_all()
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
        def invalid_constant(value):
            raise ValueError('non-finite JSON')
        def finite_float(value):
            decoded = float(value)
            if not math.isfinite(decoded):
                raise ValueError('non-finite JSON number')
            return decoded
        try:
            payload = json.loads(frame,parse_constant=invalid_constant,parse_float=finite_float)
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


class LeaseBoundChannel:
    """Native channel view tied to one actual stdin lease.

    Platform authority remains a separate provider check. close disconnects
    this view; it never terminates the Unit or clears an unknown effect.
    """
    def __init__(self,channel,lease):
        self._channel,self._lease,self._closed=channel,lease,False
        self.name=channel.name

    def _check(self):
        if self._closed: raise ChannelClosed('connection disconnected')

    def send_raw(self,payload):
        self._check()
        return self._channel.send_raw_for(self._lease,payload)

    def send_frame(self, frame_bytes, *, before_write):
        self._check()
        return self._channel._send_frame(frame_bytes, self._lease, before_write=before_write)

    async def send_raw_async(self, payload):
        self._check()
        return await self._channel.send_payload_async(payload, self._lease)

    async def send_frame_async(self, frame_bytes, *, before_write, effect_write_guard=None):
        self._check()
        if effect_write_guard is None:
            return await self._channel.send_frame_async(frame_bytes, self._lease, before_write=before_write)
        return await self._channel.send_frame_async(frame_bytes, self._lease,
            before_write=before_write, effect_write_guard=effect_write_guard)

    async def next_message_async(self, *, timeout=10.0):
        self._check()
        return await self._channel.next_message_async(timeout=timeout)

    def mark_input_unknown(self):
        self._check()
        return self._channel.mark_unresolved(self._lease)

    def acknowledge_frame(self, request_id):
        self._check()
        return self._channel._acknowledge_frame(request_id, self._lease)

    def request(self,method,params=None,*,timeout=10.0,on_request=None):
        self._check()
        return self._channel._request(method,params,timeout=timeout,on_request=on_request,lease=self._lease)

    def notify(self,method,params=None):
        payload={'jsonrpc':JSONRPC_VERSION,'method':method}
        if params is not None: payload['params']=params
        self.send_raw(payload)

    def reply(self,request_id,result):
        self.send_raw({'jsonrpc':JSONRPC_VERSION,'id':request_id,'result':result})

    def reply_error(self,request_id,*,code,message,data=None):
        error={'code':code,'message':message}
        if data is not None: error['data']=data
        self.send_raw({'jsonrpc':JSONRPC_VERSION,'id':request_id,'error':error})

    def next_message(self,*,timeout=10.0):
        self._check()
        return self._channel.next_message(timeout=timeout)

    def poll_message(self,*,timeout=0.0):
        self._check()
        return self._channel.poll_message(timeout=timeout)

    def drain(self):
        self._check()
        return self._channel.drain()

    @property
    def inflight(self): return self._channel.inflight

    def stderr_tail(self): return self._channel.stderr_tail()

    def sigint(self):
        self._check()
        with self._channel._write_lock:
            self._channel._validate_writer(self._lease)
            return self._channel.sigint()

    def close(self,*,timeout=5.0):
        if not self._closed:
            with self._channel._write_lock:
                if self._channel._active_writer is self._lease:
                    self._channel.fence_all()
                self._closed=True
        return None
