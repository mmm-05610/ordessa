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


class NDJSONTransport:
    """Spawned subprocess + line framing, with one reader thread.

    `on_line` receives every peer line (without its newline) from the reader
    thread; `on_exit` fires exactly once, with the process return code, after
    the peer's stdout ends.  Both callbacks must be thread-safe; neither may
    block on this transport.
    """

    def __init__(self, *, argv: list[str], cwd: str, on_line: Callable[[str], None],
                 on_exit: Callable[[int | None], None],
                 environment: dict[str, str] | None = None) -> None:
        self._argv = list(argv)
        self._cwd = cwd
        self._environment = environment
        self._on_line = on_line
        self._on_exit = on_exit
        self._write_lock = threading.Lock()
        self._exit_delivered = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None

    @property
    def pid(self) -> int | None:
        process = self._process
        return process.pid if process is not None else None

    def start(self) -> "NDJSONTransport":
        if self._process is not None:
            raise RuntimeError("transport already started")
        self._process = subprocess.Popen(
            self._argv, cwd=self._cwd, env=self._environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return self

    def send_line(self, text: str) -> None:
        """Write exactly one client frame; the newline is framing, not content."""
        process = self._process
        if process is None or process.stdin is None:
            raise TransportClosed("transport was never started")
        payload = (text + "\n").encode("utf-8")
        with self._write_lock:
            if self._exit_delivered.is_set():
                raise TransportClosed("the peer has exited")
            try:
                process.stdin.write(payload)
                process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError) as lost:
                raise TransportClosed("the peer's stdin is gone") from lost

    def terminate(self, *, timeout: float = 5.0) -> None:
        """Release the owned process: stop its input, then stop the process.

        Idempotent, and safe to call from the exit callback's own chain.
        """
        process = self._process
        if process is None:
            return
        with self._write_lock:
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

    def _read_loop(self) -> None:
        process = self._process
        returncode: int | None = None
        try:
            assert process is not None and process.stdout is not None
            for raw in process.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                try:
                    self._on_line(line)
                except Exception:  # noqa: BLE001 - a dead consumer cannot stop reading
                    continue
            returncode = process.wait()
        except (OSError, ValueError):
            returncode = process.wait() if process is not None else None
        finally:
            if not self._exit_delivered.is_set():
                self._exit_delivered.set()
                try:
                    self._on_exit(returncode)
                except Exception:  # noqa: BLE001 - the reader must never raise through
                    pass
