"""Local development process over frozen infrastructure spawn and owned pipes.

The single managed contract is async ProcessHandle. Concrete inherited Popen
attributes remain solely on the explicit Local development entry; managed Use
never forwards those attributes. This provider offers no isolation and is never
an implicit OpenShell fallback. Pipe adaptation adds no second spawn path.
"""
from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone
from typing import Mapping

from ordessa_environments import (
    EnvironmentRefused,
    ProcessHandleStale,
    ProcessRequest,
    ProcessStartFailed,
    ProcessObservation,
    ProcessCancellation,
    ProcessWaitTimeout,
    EnvironmentOperationUnknown,
)
from ordessa_infrastructure.process.spawn import SubprocessHandle, spawn_process
from ordessa_environments.definitions.io import validate_timeout, validate_read_size
from ._pipe_io import PipeIO

#: Opaque identity prefix for a locally owned process handle.
IDENTITY_PREFIX = "local-process"


class LocalProcessHandle(SubprocessHandle):
    """One real OS process owned by the local environment.

    Release idempotently closes owned IO, without stopping or claiming exit.
    The creator explicitly cancels/waits when process termination is required.
    """

    __slots__ = ("_identity", "_released", "generation", "_io", "_io_unknown", "_write_busy", "_release_receipt")

    def __init__(self, popen, *, identity: str, generation: int = 0):
        super().__init__(popen)
        self._identity = identity
        self._released = False
        self.generation = generation
        self._io = None
        self._io_unknown = False
        self._write_busy = False
        self._release_receipt = None

    # -- generic contract --------------------------------------------------
    @property
    def identity(self) -> str:
        return self._identity

    @property
    def released(self) -> bool:
        return self._released

    def _check_io(self):
        if self.released:raise ProcessHandleStale('process transport was released')

    def _get_io(self):
        self._check_io()
        if self._io is None:self._io=PipeIO(self)
        return self._io

    async def read_stdout(self,max_bytes=65536,*,timeout=None):
        validate_read_size(max_bytes);timeout=validate_timeout(timeout)
        io=self._get_io();await io.bind()
        return await io.stdout.read(max_bytes,timeout)

    async def read_stderr(self,max_bytes=65536,*,timeout=None):
        validate_read_size(max_bytes);timeout=validate_timeout(timeout)
        io=self._get_io();await io.bind()
        return await io.stderr.read(max_bytes,timeout)

    async def write_stdin(self,data,*,timeout=None):
        return await self._write_stdin(data, timeout=timeout)

    async def write_stdin_guarded(self,data,*,timeout=None,write_guard):
        if not callable(write_guard):
            raise EnvironmentRefused('restricted synchronous write guard required')
        return await self._write_stdin(data, timeout=timeout, write_guard=write_guard)

    async def _write_stdin(self,data,*,timeout=None,write_guard=None):
        timeout=validate_timeout(timeout);self._check_io()
        if not isinstance(data,bytes):raise EnvironmentRefused('stdin accepts bytes only')
        if self._write_busy:raise EnvironmentRefused('concurrent stdin writes are refused')
        if not data:return 0
        self._write_busy=True;dispatched=False
        loop=asyncio.get_running_loop();deadline=None if timeout is None else loop.time()+timeout
        try:
            io=self._get_io();await io.bind()
            if io.writer.is_closing():raise EnvironmentRefused('stdin is closed')
            if write_guard is None:
                dispatched=True
                io.writer.write(data)
            else:
                if deadline is not None and loop.time() >= deadline:
                    raise EnvironmentRefused('guarded write deadline elapsed before dispatch')
                # The original physical writer invokes the restricted guard in
                # this same task/thread. No drain or response await holds it.
                with write_guard():
                    dispatched=True
                    io.writer.write(data)
            if not io.writer._protocol._paused:
                await io.writer.drain()
                return len(data)
            remaining=None if deadline is None else max(0,deadline-loop.time())
            await asyncio.wait_for(io.writer.drain(),remaining)
            return len(data)
        except (TimeoutError,asyncio.CancelledError):
            if dispatched:
                self._io_unknown=True
                raise EnvironmentOperationUnknown('stdin write uncertain after acceptance; no replay',identity=self.identity) from None
            raise
        except EnvironmentRefused:
            raise
        except Exception:
            self._io_unknown=dispatched
            if dispatched:raise EnvironmentOperationUnknown('stdin write transport failed after dispatch; no replay',identity=self.identity) from None
            raise EnvironmentRefused('stdin transport unavailable before dispatch') from None
        finally:
            self._write_busy=False

    async def close_stdin(self):
        if self._write_busy:raise EnvironmentRefused('stdin write is in progress')
        io=self._get_io();await io.bind()
        io.writer.close()  # Requests EOF after queued bytes; does not wait for exit.

    def observe(self):
        code=self.popen.poll()
        state='exited' if code is not None else 'running'
        io_state='unknown' if self._io_unknown else 'closed' if self.released else 'open'
        return ProcessObservation(self.identity,state,datetime.now(timezone.utc).isoformat(),code,io_state)

    async def wait_exit(self,*,timeout=None):
        timeout=validate_timeout(timeout)
        if not self.released:
            io=self._get_io();await io.bind()  # Drains both outputs, including stderr.
        loop=asyncio.get_running_loop();deadline=None if timeout is None else loop.time()+timeout
        while True:
            observation=self.observe()
            if observation.state=='exited':return observation
            remaining=None if deadline is None else deadline-loop.time()
            if remaining is not None and remaining<=0:raise ProcessWaitTimeout('process has no exit evidence before deadline')
            await asyncio.sleep(0.01 if remaining is None else min(0.01,remaining))

    async def cancel(self,*,force=False):
        return self._cancel_now(force=force)

    async def cancel_guarded(self,*,force=False,guard_effect):
        if not callable(guard_effect):raise EnvironmentRefused('synchronous lifecycle guard required')
        with guard_effect():return self._cancel_now(force=force)

    def _cancel_now(self,*,force=False):
        if type(force) is not bool:raise EnvironmentRefused('force must be boolean')
        observation=self.observe()
        if observation.state=='exited':return ProcessCancellation('requested',observation)
        try:
            if force:self.popen.kill()
            else:self.popen.terminate()
        except OSError:
            return ProcessCancellation('unknown',self.observe())
        return ProcessCancellation('requested',self.observe())

    def release_guarded(self,*,guard_effect) -> Mapping[str,object]:
        if not callable(guard_effect):raise EnvironmentRefused('synchronous lifecycle guard required')
        with guard_effect():return self.release()

    def release(self) -> Mapping[str, object]:
        if self._release_receipt is not None:return dict(self._release_receipt)
        self._released=True
        if self._io is not None:self._io.close_now()
        self.close_streams()
        observation=self.observe()
        receipt={'processIdentity':self.identity,'transportReleased':True,'processState':observation.state,'ioState':observation.io_state}
        if observation.exit_code is not None:receipt['exitCode']=str(observation.exit_code)
        self._release_receipt=receipt
        return dict(receipt)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<LocalProcessHandle {self._identity} pid={self.pid}>"


def spawn(request: ProcessRequest, *, identity_prefix: str = IDENTITY_PREFIX, generation: int = 0) -> LocalProcessHandle:
    """Perform the real spawn for one fully resolved request.

    The working directory and the ``HOME`` directory named by the request are
    provisioned first, matching the isolation contract the callers already rely
    on. On failure nothing is owned and no handle is handed back.
    """
    if not isinstance(request, ProcessRequest):
        raise EnvironmentRefused("local execution space accepts a ProcessRequest only")
    try:
        os.makedirs(request.cwd, exist_ok=True)
        home = request.env.get("HOME")
        if isinstance(home, str) and home:
            os.makedirs(home, exist_ok=True)
    except OSError as error:
        raise ProcessStartFailed(f"launch directories could not be provisioned: {error}") from error
    try:
        process = spawn_process(request.argv, cwd=request.cwd, env=request.env)
    except OSError as error:
        raise ProcessStartFailed(f"local process could not be spawned: {error}") from error
    return LocalProcessHandle(process.popen, identity=f"{identity_prefix}/{process.pid}",generation=generation)


__all__ = ["IDENTITY_PREFIX", "LocalProcessHandle", "spawn"]
