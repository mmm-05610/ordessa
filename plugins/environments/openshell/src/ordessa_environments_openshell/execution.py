"""One async ProcessHandle over official bidirectional non-PTY RPC.

No durable per-exec kill/reconnect claim. Cancellation/release affect this RPC
transport only; only a real exit event confirms process termination.
"""
import asyncio
import queue
import threading
import uuid
from datetime import datetime, timezone

from openshell._proto import datamodel_pb2, openshell_pb2 as pb
from ordessa_environments import (EnvironmentRefused, EnvironmentOperationUnknown,
    ProcessWaitTimeout, ProcessRequest, ProcessObservation, ProcessCancellation)
from ordessa_environments.definitions.io import validate_timeout, validate_read_size


def _wake(watchers):
    for loop,event in watchers:
        if not loop.is_closed():
            try:loop.call_soon_threadsafe(event.set)
            except RuntimeError:pass


class _Output:
    def __init__(self,owner):
        self.owner=owner
        self.data=bytearray()
        self.eof=False
        self.error=False
        self.lock=threading.Lock()
        self.watchers=set()
        self.busy=False

    def put(self,data):
        with self.lock:
            if len(self.data)+len(data)>4*1024*1024:
                self.error=True
                raise BufferError('unread output exceeds bounded channel')
            self.data.extend(data)
            watchers=tuple(self.watchers)
        _wake(watchers)

    def finish(self):
        with self.lock:
            self.eof=True;watchers=tuple(self.watchers)
        _wake(watchers)

    async def read(self,max_bytes,timeout):
        loop=asyncio.get_running_loop()
        deadline=None if timeout is None else loop.time()+timeout
        event=asyncio.Event();watcher=(loop,event)
        with self.lock:
            if self.busy:raise EnvironmentRefused('concurrent reads on the same output are refused')
            self.busy=True;self.watchers.add(watcher)
        try:
            while True:
                with self.lock:
                    if self.owner._released:raise EnvironmentRefused('process transport was released')
                    if self.error:raise EnvironmentOperationUnknown('bounded RPC output failed',identity=self.owner.identity)
                    if self.data:
                        count=min(max_bytes,len(self.data));result=bytes(self.data[:count]);del self.data[:count]
                        return result
                    if self.eof:
                        if self.owner.observe().state!='exited':
                            raise EnvironmentOperationUnknown('RPC lost without exit receipt',identity=self.owner.identity)
                        return b''
                    event.clear()
                remaining=None if deadline is None else deadline-loop.time()
                if remaining is not None and remaining<=0:raise ProcessWaitTimeout('owned RPC output read timed out')
                try:await asyncio.wait_for(event.wait(),remaining)
                except TimeoutError:raise ProcessWaitTimeout('owned RPC output read timed out') from None
        finally:
            with self.lock:self.busy=False;self.watchers.discard(watcher)


class OpenShellProcess:
    # The physical write is the enqueued frame that the request generator sends
    # to the official bidirectional RPC; the owner may therefore guard it.
    guarded_write_supported = True
    # A remote sandbox has no per-process signal RPC; termination runs a kill in
    # the sandbox against the pid recorded at launch, then waits for the exit
    # event on the official interactive stream. The synchronous guard covers the
    # kill dispatch cut.
    guarded_termination_supported = True

    def __init__(self,rpc,*,workspace,sandbox_name,request,generation=0,file_root='/sandbox'):
        if not isinstance(request,ProcessRequest):raise EnvironmentRefused('OpenShell execution requires ProcessRequest')
        request_id=str(uuid.uuid4())
        self.identity='openshell-exec/'+request_id
        self._rpc=rpc
        self._workspace,self._name=workspace,sandbox_name
        self.generation=generation
        self._input=queue.Queue(maxsize=256)
        self._finished=threading.Event()
        self._state_lock=threading.Lock()
        self._input_watchers=set();self._finish_watchers=set()
        self._queued_bytes=0;self._stdin_closed=False
        self._exit_code=None;self._io_unknown=False;self._released=False
        # True only when this owner terminated the process and then positively
        # observed that it no longer exists in the sandbox.
        self._terminated_absent=False
        self._loop=None;self._write_busy=False;self._release_receipt=None
        self._stdout,self._stderr=_Output(self),_Output(self)
        # The launch argv is used verbatim: wrapping it in a shell changed how the
        # harness identified its own process and broke its ACP startup. A remote
        # sandbox has no per-process signal RPC, so termination later matches the
        # harness' real command line instead of a recorded pid.
        self._argv=tuple(request.argv)
        start=pb.ExecSandboxRequest(workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=workspace),
            sandbox=sandbox_name,command=list(request.argv),workdir=request.cwd,
            environment=dict(request.env),tty=False,no_login_shell=True,request_id=request_id)
        self._input.put(pb.ExecSandboxInput(start=start))
        try:self._call=rpc.ExecSandboxInteractive(self._requests())
        except Exception:raise EnvironmentOperationUnknown('exec admission outcome unknown',identity=self.identity) from None
        self._reader=threading.Thread(target=self._receive,name='ordessa-openshell-exec-output',daemon=True)
        self._reader.start()

    def _bind_loop(self):
        loop=asyncio.get_running_loop()
        if self._loop is None:self._loop=loop
        if self._loop is not loop:raise EnvironmentRefused('process byte IO belongs to a different owner loop')
        return loop

    def _check_io(self):
        if self._released:raise EnvironmentRefused('process transport was released')

    def _requests(self):
        while not self._finished.is_set():
            try:value=self._input.get(timeout=0.1)
            except queue.Empty:
                if self._stdin_closed:return
                continue
            if value is None:return
            if value.WhichOneof('payload')=='stdin':
                with self._state_lock:
                    self._queued_bytes-=len(value.stdin);watchers=tuple(self._input_watchers)
                _wake(watchers)
            yield value

    def _receive(self):
        try:
            for event in self._call:
                kind=event.WhichOneof('payload')
                if kind=='stdout':self._stdout.put(bytes(event.stdout.data))
                elif kind=='stderr':self._stderr.put(bytes(event.stderr.data))
                elif kind=='exit':
                    with self._state_lock:self._exit_code=int(event.exit.exit_code)
                    break
        except Exception:
            with self._state_lock:self._io_unknown=True
            self._call.cancel()
        finally:
            with self._state_lock:
                self._stdin_closed=True
                if self._exit_code is None:self._io_unknown=True
                self._finished.set();watchers=tuple(self._finish_watchers|self._input_watchers)
            self._stdout.finish();self._stderr.finish();_wake(watchers)

    async def read_stdout(self,max_bytes=65536,*,timeout=None):
        validate_read_size(max_bytes);timeout=validate_timeout(timeout)
        self._check_io();self._bind_loop()
        return await self._stdout.read(max_bytes,timeout)

    async def read_stderr(self,max_bytes=65536,*,timeout=None):
        validate_read_size(max_bytes);timeout=validate_timeout(timeout)
        self._check_io();self._bind_loop()
        return await self._stderr.read(max_bytes,timeout)

    async def write_stdin(self,data,*,timeout=None):
        timeout=validate_timeout(timeout);self._check_io();loop=self._bind_loop()
        if not isinstance(data,bytes):raise EnvironmentRefused('stdin accepts bytes only')
        if len(data)>1024*1024:raise EnvironmentRefused('stdin frame exceeds bounded channel')
        if self._write_busy:raise EnvironmentRefused('concurrent stdin writes are refused')
        if not data:return 0
        self._write_busy=True
        deadline=None if timeout is None else loop.time()+timeout
        event=asyncio.Event();watcher=(loop,event)
        with self._state_lock:self._input_watchers.add(watcher)
        try:
            while True:
                with self._state_lock:
                    if self._released or self._stdin_closed or self._finished.is_set():raise EnvironmentRefused('stdin is closed')
                    if self._queued_bytes+len(data)<=4*1024*1024:
                        try:self._input.put_nowait(pb.ExecSandboxInput(stdin=data))
                        except queue.Full:pass
                        else:
                            self._queued_bytes+=len(data)
                            # No await after acceptance: cancellation while waiting
                            # cannot silently dispatch later or consume queue data.
                            return len(data)
                    event.clear()
                remaining=None if deadline is None else deadline-loop.time()
                if remaining is not None and remaining<=0:raise ProcessWaitTimeout('stdin admission timed out before dispatch')
                try:await asyncio.wait_for(event.wait(),remaining)
                except TimeoutError:raise ProcessWaitTimeout('stdin admission timed out before dispatch') from None
        finally:
            with self._state_lock:self._input_watchers.discard(watcher)
            self._write_busy=False

    async def write_stdin_guarded(self,data,*,timeout=None,write_guard=None):
        """Write one frame with the caller's synchronous physical-write guard.

        The guard is entered exactly once, and the frame becomes dispatchable
        inside that cut (no await between the guard and the enqueue).
        """
        timeout=validate_timeout(timeout);self._check_io();loop=self._bind_loop()
        if not callable(write_guard):
            raise EnvironmentRefused('restricted synchronous write guard required')
        if not isinstance(data,bytes):raise EnvironmentRefused('stdin accepts bytes only')
        if len(data)>1024*1024:raise EnvironmentRefused('stdin frame exceeds bounded channel')
        if self._write_busy:raise EnvironmentRefused('concurrent stdin writes are refused')
        if not data:return 0
        self._write_busy=True
        deadline=None if timeout is None else loop.time()+timeout
        event=asyncio.Event();watcher=(loop,event)
        with self._state_lock:self._input_watchers.add(watcher)
        try:
            while True:
                if deadline is not None and deadline-loop.time()<=0:
                    raise ProcessWaitTimeout('stdin admission timed out before dispatch')
                with self._state_lock:
                    if self._released or self._stdin_closed or self._finished.is_set():
                        raise EnvironmentRefused('stdin is closed')
                    admitted=self._queued_bytes+len(data)<=4*1024*1024
                if admitted:
                    with write_guard():
                        with self._state_lock:
                            if self._released or self._stdin_closed or self._finished.is_set():
                                raise EnvironmentRefused('stdin is closed')
                            if self._queued_bytes+len(data)>4*1024*1024:
                                raise EnvironmentRefused('stdin queue is full at dispatch')
                            try:self._input.put_nowait(pb.ExecSandboxInput(stdin=data))
                            except queue.Full:raise EnvironmentRefused('stdin queue is full at dispatch') from None
                            self._queued_bytes+=len(data)
                    return len(data)
                event.clear()
                remaining=None if deadline is None else deadline-loop.time()
                try:await asyncio.wait_for(event.wait(),remaining)
                except TimeoutError:raise ProcessWaitTimeout('stdin admission timed out before dispatch') from None
        finally:
            with self._state_lock:self._input_watchers.discard(watcher)
            self._write_busy=False

    async def close_stdin(self):
        if self._write_busy:raise EnvironmentRefused('stdin write is in progress')
        self._check_io();self._bind_loop()
        with self._state_lock:
            self._stdin_closed=True
            try:self._input.put_nowait(None)
            except queue.Full:pass
            watchers=tuple(self._input_watchers)
        _wake(watchers)

    def observe(self):
        with self._state_lock:
            code=self._exit_code
            state='exited' if code is not None else 'unknown' if self._finished.is_set() or self._io_unknown else 'running'
            io_state='unknown' if self._io_unknown else 'closed' if self._released else 'open'
        return ProcessObservation(self.identity,state,datetime.now(timezone.utc).isoformat(),code,io_state)

    async def wait_exit(self,*,timeout=None):
        timeout=validate_timeout(timeout);loop=self._bind_loop()
        event=asyncio.Event();watcher=(loop,event)
        with self._state_lock:
            if self._finished.is_set():return self.observe_unlocked()
            self._finish_watchers.add(watcher)
        try:
            if timeout==0:raise ProcessWaitTimeout('remote exit has not been observed')
            try:await asyncio.wait_for(event.wait(),timeout)
            except TimeoutError:raise ProcessWaitTimeout('remote exit has not been observed before deadline') from None
            return self.observe()
        finally:
            with self._state_lock:self._finish_watchers.discard(watcher)

    def observe_unlocked(self):
        code=self._exit_code
        state='exited' if code is not None else 'unknown' if self._finished.is_set() or self._io_unknown else 'running'
        io='unknown' if self._io_unknown else 'closed' if self._released else 'open'
        return ProcessObservation(self.identity,state,datetime.now(timezone.utc).isoformat(),code,io)

    def _kill(self, signal):
        """Terminate the harness inside the sandbox when its pid is unambiguous.

        A sandbox has no per-process signal RPC. The launched argv is used as the
        match pattern; if more than one process matches (a shared sandbox with
        another live Use of the same harness), nothing is killed and the caller
        keeps the honest unknown.
        """
        import re as _re
        # A node harness runs as ``node .../kilocode/cli/... acp``, so the tokens
        # are matched in order across the real command line. Only an unambiguous
        # single match may be killed; two live Uses of the same harness in one
        # shared sandbox therefore stay an honest unknown.
        pattern='.*'.join(_re.escape(token) for token in self._argv if token)
        # The match pattern travels through the environment: a pattern placed in
        # the shell's own argv would match itself and break the unique-match rule.
        script=('pids=$(pgrep -f "$ORDESSA_MATCH" 2>/dev/null || true); '
                'count=$(printf "%s" "$pids" | wc -w); '
                '[ "$count" -eq 1 ] && kill -'+signal+' $pids')
        request=pb.ExecSandboxRequest(workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=self._workspace),
            sandbox=self._name,command=['/bin/sh','-c',script],
            environment={'ORDESSA_MATCH':pattern,'PATH':'/usr/local/bin:/usr/bin:/bin'},
            workdir='/',tty=False,no_login_shell=True,request_id=str(uuid.uuid4()))
        code=None
        try:
            for event in self._rpc.ExecSandbox(request,timeout=15):
                if event.WhichOneof('payload')=='exit':code=int(event.exit.exit_code)
        except Exception:
            return False
        return code==0

    def _present(self):
        pattern='.*'.join(__import__('re').escape(token) for token in self._argv if token)
        script='pgrep -f "$ORDESSA_MATCH" 2>/dev/null | wc -w'
        request=pb.ExecSandboxRequest(workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=self._workspace),
            sandbox=self._name,command=['/bin/sh','-c',script],
            environment={'ORDESSA_MATCH':pattern,'PATH':'/usr/local/bin:/usr/bin:/bin'},
            workdir='/',tty=False,no_login_shell=True,request_id=str(uuid.uuid4()))
        data=bytearray()
        try:
            for event in self._rpc.ExecSandbox(request,timeout=15):
                if event.WhichOneof('payload')=='stdout':data.extend(event.stdout.data)
        except Exception:
            return None
        try:return int(data.decode('utf-8','replace').strip() or '0')!=0
        except ValueError:return None

    async def _terminate(self,force,guard_effect=None):
        observation=self.observe()
        if observation.state=='exited':return ProcessCancellation('requested',observation)
        def dispatch(signal):
            if guard_effect is None:return self._kill(signal)
            with guard_effect():return self._kill(signal)
        if guard_effect is None:await asyncio.to_thread(dispatch,'TERM')
        else:dispatch('TERM')
        # A harness may shut down slowly after SIGTERM; the exit receipt is what
        # makes the outcome confirmed, so wait well past the usual teardown.
        try:observation=await self.wait_exit(timeout=20)
        except ProcessWaitTimeout:observation=self.observe()
        if observation.state=='exited':return ProcessCancellation('requested',observation)
        # An external kill may terminate the process without an exit event on the
        # interactive stream. Half-closing stdin lets the supervisor finalize the
        # exec session, which is where the exit receipt belongs.
        try:
            await self.close_stdin()
        except Exception:
            pass
        try:observation=await self.wait_exit(timeout=20)
        except ProcessWaitTimeout:observation=self.observe()
        if observation.state=='exited':return ProcessCancellation('requested',observation)
        if force:
            if guard_effect is None:await asyncio.to_thread(dispatch,'KILL')
            else:dispatch('KILL')
            try:observation=await self.wait_exit(timeout=15)
            except ProcessWaitTimeout:observation=self.observe()
            if observation.state=='exited':return ProcessCancellation('requested',observation)
        # Without an exit receipt the outcome must stay unknown: a fixed process
        # observation requires an integer exit code for `exited`, so "process
        # absent" alone can never be promoted to a confirmed exit.
        try:self._call.cancel()
        except Exception:pass
        with self._state_lock:self._io_unknown=self._exit_code is None
        return ProcessCancellation('unknown',self.observe())

    async def cancel(self,*,force=False):
        if type(force) is not bool:raise EnvironmentRefused('force must be boolean')
        self._check_io();self._bind_loop()
        return await self._terminate(force)

    async def cancel_guarded(self,*,force=False,guard_effect=None):
        if type(force) is not bool:raise EnvironmentRefused('force must be boolean')
        if not callable(guard_effect):raise EnvironmentRefused('mandatory synchronous termination guard required')
        self._check_io();self._bind_loop()
        return await self._terminate(force,guard_effect)

    def release(self):
        if self._release_receipt is not None:return dict(self._release_receipt)
        self._released=True
        if self.observe().state!='exited':
            self._call.cancel()
            with self._state_lock:self._io_unknown=self._exit_code is None
        self._reader.join(timeout=1)
        self._stdout.finish();self._stderr.finish()
        observation=self.observe()
        receipt={'processIdentity':self.identity,'transportReleased':not self._reader.is_alive(),
            'processState':observation.state,'ioState':observation.io_state}
        if observation.exit_code is not None:receipt['exitCode']=str(observation.exit_code)
        self._release_receipt=receipt
        return dict(receipt)


class OpenShellExecution:
    def __init__(self,rpc,*,workspace,sandbox_name,validate=None,generation=0,file_root='/sandbox'):
        self._rpc,self._workspace,self._name=rpc,workspace,sandbox_name
        self._validate,self._generation=validate,generation
        self._file_root=file_root

    def start(self,request):
        if self._validate is not None:self._validate()
        return OpenShellProcess(self._rpc,workspace=self._workspace,sandbox_name=self._name,request=request,
            generation=self._generation,file_root=self._file_root)
