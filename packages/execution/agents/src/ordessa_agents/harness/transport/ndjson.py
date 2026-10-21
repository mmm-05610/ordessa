"""A NDJSON stdio transport that carries ACP frames verbatim and nothing else.

The transport is a byte-line pipe to one spawned peer process: every client
line goes out as given (plus the newline framing), every peer line arrives as
given.  It does not parse, track, answer, or synthesize frames - a channel
that ends with a request in flight leaves that request unanswered, which is
the honest outcome the seam contract pins.
"""
from __future__ import annotations

import subprocess
import threading
from typing import Callable


class TransportClosed(RuntimeError):
    """The peer is gone; a line can no longer enter the channel."""


class WriterLeaseRefused(TransportClosed):
    """Managed writer identity is absent, stale, revoked or unavailable."""


class WriterLease:
    """Opaque process-local lease; visible epoch facts are not credentials."""
    __slots__ = ("_epoch",)

    def __init__(self, *args, **kwargs):
        raise TypeError("writer leases are issued by the transport")

    def __setattr__(self, name, value):
        raise AttributeError("writer lease is immutable")

    @property
    def epoch(self):
        return self._epoch

    def __copy__(self):
        copied = object.__new__(type(self))
        object.__setattr__(copied, "_epoch", self._epoch)
        return copied

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __reduce__(self):
        raise TypeError("writer leases cannot be serialized")


class NDJSONTransport:
    """Spawned subprocess + line framing, with one reader thread.

    `on_line` receives every peer line (without its newline) from the reader
    thread; `on_exit` fires exactly once, with the process return code, after
    the peer's stdout ends.  Both callbacks must be thread-safe; neither may
    block on this transport.
    """

    def __init__(self, *, argv: list[str], cwd: str, on_line: Callable[[str], None],
                 on_exit: Callable[[int | None], None],
                 environment: dict[str, str] | None = None,
                 managed: bool = False, max_frame_bytes: int = 8 * 1024 * 1024) -> None:
        if type(managed) is not bool:
            raise ValueError("managed must be an explicit boolean")
        if type(max_frame_bytes) is not int or not 1 <= max_frame_bytes <= 8 * 1024 * 1024:
            raise ValueError("managed frame limit must be between 1 and 8388608 bytes")
        self._managed = managed
        self._max_frame_bytes = max_frame_bytes
        self._writer_epoch = 0
        self._active_writer = None
        self._unresolved = False
        self._terminating = False
        self._argv = list(argv)
        self._cwd = cwd
        self._environment = environment
        self._on_line = on_line
        self._on_exit = on_exit
        self._write_lock = threading.RLock()
        self._exit_delivered = threading.Event()
        self._protocol_ended = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None

    @property
    def pid(self) -> int | None:
        process = self._process
        return process.pid if process is not None else None

    def start(self) -> "NDJSONTransport":
        with self._write_lock:
            if self._process is not None or self._terminating:
                raise RuntimeError("transport already started or terminated")
            self._process = subprocess.Popen(
                self._argv, cwd=self._cwd, env=self._environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            return self

    def _ensure_live_locked(self):
        process = self._process
        if (process is None or process.stdin is None or self._terminating
                or self._exit_delivered.is_set() or process.poll() is not None
                or (self._managed and self._protocol_ended.is_set())):
            raise TransportClosed("transport has no live owned stdin")
        return process

    def _require_managed_locked(self):
        if not self._managed:
            raise WriterLeaseRefused("writer leases require explicit managed mode")

    def _validate_writer_locked(self, lease):
        self._require_managed_locked()
        if (type(lease) is not WriterLease or self._active_writer is not lease
                or lease.epoch != self._writer_epoch or self._unresolved):
            raise WriterLeaseRefused("writer lease is absent, revoked or unresolved")
        self._ensure_live_locked()

    def _fence_locked(self):
        self._active_writer = None
        self._writer_epoch += 1
        return self._writer_epoch

    def acquire_writer(self):
        """One in-process writer for this actual stdin, without expiry takeover."""
        with self._write_lock:
            self._require_managed_locked()
            self._ensure_live_locked()
            if self._unresolved or self._active_writer is not None:
                raise WriterLeaseRefused("writer is held or an unresolved effect requires termination")
            lease = object.__new__(WriterLease)
            object.__setattr__(lease, "_epoch", self._writer_epoch)
            self._active_writer = lease
            return lease

    def fence_writer(self, lease):
        """Synchronous write barrier; native effects already sent are unaffected."""
        with self._write_lock:
            self._validate_writer_locked(lease)
            return self._fence_locked()

    def fence_all(self):
        """Trusted owner revokes every writer, without clearing unknown facts."""
        with self._write_lock:
            self._require_managed_locked()
            return self._fence_locked()

    def mark_unresolved(self, lease):
        """No replacement writer until this owned transport ends; no resend."""
        with self._write_lock:
            self._validate_writer_locked(lease)
            self._unresolved = True
            self._fence_locked()

    def send_line_for(self, lease, text):
        """Transfer exactly one bounded UTF-8 frame under the lease barrier."""
        if not isinstance(text, str) or "\n" in text or "\r" in text:
            raise ValueError("managed input must be one unmodified text frame")
        try:
            payload = (text + "\n").encode("utf-8")
        except UnicodeError:
            raise ValueError("managed frame must be valid UTF-8") from None
        if len(payload) - 1 > self._max_frame_bytes:
            raise ValueError("managed frame exceeds the byte limit")
        with self._write_lock:
            self._validate_writer_locked(lease)
            self._write_locked(payload)

    def send_line(self, text: str) -> None:
        """Legacy write; managed mode has no unleased write bypass."""
        with self._write_lock:
            if self._managed:
                raise WriterLeaseRefused("managed transport requires send_line_for with its current lease")
            self._write_locked((text + "\n").encode("utf-8"))

    def _write_locked(self, payload):
        process = self._ensure_live_locked()
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as lost:
            if self._managed:
                self._unresolved = True
                self._fence_locked()
            raise TransportClosed("the peer's stdin is gone; partial delivery may have occurred") from lost

    def terminate(self, *, timeout: float = 5.0) -> None:
        """Release the owned process: stop its input, then stop the process.

        Idempotent, and safe to call from the exit callback's own chain.
        """
        with self._write_lock:
            process = self._process
            if process is None and not self._managed:
                return
            self._terminating = True
            self._fence_locked()
            if process is None:
                return
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)

    def _output_ended(self):
        # Stdout EOF is loss of the protocol even if the process is still alive.
        # Do not let a new writer dispatch into a channel without receipts.
        with self._write_lock:
            self._protocol_ended.set()
            if self._managed:
                self._unresolved = True
                self._fence_locked()

    def _read_loop(self) -> None:
        process = self._process
        returncode: int | None = None
        try:
            assert process is not None and process.stdout is not None
            source = (iter(lambda: process.stdout.readline(self._max_frame_bytes + 2), b"")
                      if self._managed else process.stdout)
            for raw in source:
                if self._managed:
                    if not raw.endswith(b"\n"):
                        raise ValueError("managed peer frame is oversized or truncated")
                    content = raw[:-1]
                    if content.endswith(b"\r"):
                        content = content[:-1]
                    if len(content) > self._max_frame_bytes:
                        raise ValueError("managed peer frame exceeds byte limit")
                    line = content.decode("utf-8", errors="strict")
                else:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                try:
                    self._on_line(line)
                except Exception:  # noqa: BLE001 - a dead consumer cannot stop reading
                    continue
            self._output_ended()
            returncode = process.wait()
        except (OSError, ValueError):
            self._output_ended()
            returncode = process.wait() if process is not None else None
        finally:
            with self._write_lock:
                deliver_exit = not self._exit_delivered.is_set()
                self._fence_locked()
                self._exit_delivered.set()
            if deliver_exit:
                try:
                    self._on_exit(returncode)
                except Exception:  # noqa: BLE001 - the reader must never raise through
                    pass
