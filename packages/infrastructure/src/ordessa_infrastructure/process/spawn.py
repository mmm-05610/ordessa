"""Neutral process-spawn primitive: one real OS process with real byte streams.

Nothing here knows about agents, environments, leases, writer admission,
receipts or instances. Business owners keep those and bind them over this
primitive — the environment provider owns the process, the transport owns
framing and fencing, the records owner owns the receipts.

Importing this module opens nothing; only :func:`spawn_process` starts a
process. This module must not import any product package.
"""
from __future__ import annotations

import subprocess
from typing import Any, Mapping, Sequence


class SubprocessHandle:
    """One real OS process with piped, bidirectional byte streams.

    The surface is deliberately ``Popen``-compatible, because the existing
    transport binds to exactly these attributes and the termination evidence
    records the real PID:

    - ``stdin`` / ``stdout`` / ``stderr`` — the real pipe objects (with real
      descriptors), never wrapped or replaced;
    - ``poll`` / ``wait`` / ``terminate`` / ``kill`` / ``send_signal`` — the OS
      lifecycle. ``wait`` propagates :class:`subprocess.TimeoutExpired`
      unchanged, so a caller's terminate/kill escalation keeps its semantics;
    - ``pid`` / ``returncode`` — the OS-level identity and outcome.

    No environment, lease, receipt or instance semantics live on this class.
    """

    __slots__ = ("_popen",)

    def __init__(self, popen: "subprocess.Popen[bytes]"):
        self._popen = popen

    @property
    def popen(self) -> "subprocess.Popen[bytes]":
        """The underlying process object (owner-side access only)."""
        return self._popen

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    @property
    def stdin(self):
        return self._popen.stdin

    @property
    def stdout(self):
        return self._popen.stdout

    @property
    def stderr(self):
        return self._popen.stderr

    def poll(self) -> int | None:
        return self._popen.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._popen.wait(timeout=timeout)

    def terminate(self) -> None:
        self._popen.terminate()

    def kill(self) -> None:
        self._popen.kill()

    def send_signal(self, sig: int) -> None:
        self._popen.send_signal(sig)

    def close_streams(self) -> None:
        """Close this process's own pipes. Never touches another process."""
        for stream in (self._popen.stdin, self._popen.stdout, self._popen.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<SubprocessHandle pid={self._popen.pid} rc={self._popen.returncode}>"


def spawn_process(
    argv: Sequence[str],
    *,
    cwd: str,
    env: Mapping[str, str],
) -> SubprocessHandle:
    """Start one real process with piped stdio.

    Raises :class:`OSError` when the process cannot be started; the caller maps
    that onto its own typed failure. Nothing is created or cleaned up here beyond
    the process itself: directory provisioning is the caller's responsibility.
    """
    popen = subprocess.Popen(  # noqa: S603 - argv is caller-resolved and validated
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return SubprocessHandle(popen)


__all__ = ["SubprocessHandle", "spawn_process"]
