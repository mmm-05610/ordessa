"""ACP framing over opaque async environment channels; no spawn or host IO.

Owned by the Unit composition layer: agents' transport seam stays independent
of ``ordessa_environments``; units bind an environment ``ProcessHandle`` to the
agents ``ProcessChannel`` contract here.
"""
import asyncio
import json

from ordessa_environments import ProcessHandle, ProcessWaitTimeout
from ordessa_agents.harness.transport import (
    ProcessChannel, ChannelClosed, RequestTimeout, FramingError,
    WriterLeaseRefused, EffectWriteGuard, EffectWriteRefused, NativeWriteProgress,
)


class EnvironmentProcessChannel(ProcessChannel):
    def __init__(self, process, **kwargs):
        if not isinstance(process, ProcessHandle):
            raise ValueError('frozen async ProcessHandle required')
        super().__init__(process, **kwargs)
        self._async_write_lock = asyncio.Lock()
        self._stderr_task = None
        self._stderr_error = None

    def _process_running(self):
        return self._process.observe().state == 'running'

    def _unknown(self):
        with self._write_lock:
            self._unresolved = True
            if self._managed:
                self.fence_all()

    async def _stderr(self):
        try:
            while True:
                chunk = await self._process.read_stderr()
                if not chunk:
                    return
                self._stderr_tail.extend(chunk)
                del self._stderr_tail[:-65536]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stderr_error = error
            self._unknown()

    def _start_stderr(self):
        if self._stderr_task is None:
            self._stderr_task = asyncio.create_task(self._stderr())

    async def send_payload_async(self, payload, lease):
        data = (json.dumps(dict(payload), ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf8')
        return await self._write_async(data, lease)

    async def send_frame_async(self, data, lease, *, before_write, effect_write_guard=None,
                               on_write_boundary=None):
        if not callable(before_write):
            raise ValueError('explicit native write guard required')
        if effect_write_guard is not None and type(effect_write_guard) is not EffectWriteGuard:
            raise EffectWriteRefused('trusted operation write guard required')
        return await self._write_async(data, lease, before_write=before_write,
            effect_write_guard=effect_write_guard, on_write_boundary=on_write_boundary)

    async def _write_async(self, data, lease, *, before_write=None, effect_write_guard=None,
                           on_write_boundary=None):
        if not isinstance(data, bytes) or not data.endswith(b'\n') or b'\n' in data[:-1] or b'\r' in data:
            raise FramingError('native frame must be one complete UTF-8 JSONL record')
        if len(data)-1 > self._reader._max:
            raise FramingError('native frame exceeds byte limit')
        native = self._decode_frame(self._reader._decode(data[:-1])).raw
        key = None
        if before_write is not None:
            request_id = native.get('id')
            if type(request_id) not in (str, int) or request_id == '':
                raise FramingError('frozen native request must carry its original ID')
            key = type(request_id).__name__, request_id
        if effect_write_guard is not None:
            progress = NativeWriteProgress(data, effect_write_guard, on_write_boundary)
            try:
                # Enter the authority guard before any native writer lock.
                # The same deadline bounds writer contention and byte writing.
                progress.mark(phase='effect_guard_acquire')
                async with effect_write_guard.hold(data) as deadline:
                    remaining = max(0, deadline-asyncio.get_running_loop().time())
                    progress.mark(phase='writer_lock_acquire')
                    await asyncio.wait_for(self._async_write_lock.acquire(), remaining)
                    try:
                        await self._admit_and_write(data, lease, key, before_write, deadline, progress)
                    finally:
                        self._async_write_lock.release()
                    progress.mark(phase='guard_release')
                progress.mark(phase='write_acknowledged')
            except BaseException as error:
                progress.attach(error)
                self._unknown()
                raise
        else:
            progress = NativeWriteProgress(data, None, on_write_boundary)
            try:
                progress.mark(phase='writer_lock_acquire')
                async with self._async_write_lock:
                    await self._admit_and_write(data, lease, key, before_write, progress=progress)
            except BaseException as error:
                progress.attach(error)
                raise

    async def _admit_and_write(self, data, lease, key, before_write, deadline=None, progress=None):
        if progress is not None:
            progress.mark(phase='writer_admission')
        with self._write_lock:
            self._ensure_open()
            if self._managed:
                self._validate_writer(lease)
            if self._unresolved or key is not None and key in self._prepared_inflight:
                raise WriterLeaseRefused('original native input remains pending')
            if before_write is not None:
                try:
                    if progress is not None:
                        progress.mark(phase='before_write', before_write='entered')
                    before_write()
                    if progress is not None:
                        progress.mark(before_write='completed', phase='writer_admission')
                    if self._managed:
                        self._validate_writer(lease)
                except BaseException:
                    self._unknown()
                    raise
                self._prepared_inflight[key] = lease
        self._start_stderr()
        try:
            if progress is not None:
                progress.mark(phase='write_stdin', write_stdin='entered')
            if deadline is None:
                count = await self._process.write_stdin(data)
            else:
                remaining = max(0, deadline-asyncio.get_running_loop().time())
                count = await asyncio.wait_for(self._process.write_stdin(data, timeout=remaining), remaining)
            if progress is not None:
                progress.mark(write_stdin='returned',
                    acknowledged_bytes=count if type(count) is int and 0 <= count <= len(data) else None,
                    phase='write_acknowledged' if type(count) is int and count == len(data) else 'write_stdin')
            if count != len(data):
                raise ChannelClosed('native write partially accepted')
        except BaseException:
            self._unknown()
            raise

    async def next_message_async(self, *, timeout=10.0):
        self._ensure_open()
        self._start_stderr()
        if self._inbox:
            return self._inbox.pop(0)
        deadline = asyncio.get_running_loop().time()+timeout
        while True:
            if self._eof:
                raise ChannelClosed('peer closed protocol stream; process exit unproven')
            try:
                chunk = await self._process.read_stdout(timeout=max(0, deadline-asyncio.get_running_loop().time()))
            except ProcessWaitTimeout:
                raise RequestTimeout('<stream>', None, timeout) from None
            except asyncio.CancelledError:
                raise
            except Exception:
                self._unknown()
                raise
            if not chunk:
                self._eof = True
                self._unknown()
                self._reader.close()
                raise ChannelClosed('peer closed protocol stream; process exit unproven')
            try:
                messages = [self._decode_frame(frame) for frame in self._reader.feed(chunk)]
            except FramingError:
                self._unknown()
                raise
            if messages:
                self._inbox.extend(messages[1:])
                return messages[0]

    async def close_async(self, *, timeout=5):
        self._closed = True
        if self._managed:
            self.fence_all()
        try:
            await self._process.close_stdin()
        except Exception:
            # Failed IO is not termination evidence. Cleanup still asks the
            # process owner, never assumes EOF/cancellation means exit.
            pass
        try:
            observation = await self._process.wait_exit(timeout=timeout)
        except ProcessWaitTimeout:
            await self._process.cancel()
            try:
                observation = await self._process.wait_exit(timeout=timeout)
            except ProcessWaitTimeout:
                await self._process.cancel(force=True)
                observation = await self._process.wait_exit(timeout=timeout)
        if observation.state != 'exited' or observation.exit_code is None:
            raise ChannelClosed('owned process exit remains unknown')
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        return observation.exit_code

    # The attached surface has exactly one IO path. Legacy brand launch still
    # has its original synchronous implementation on ProcessChannel itself.
    def _send(self, *args, **kwargs):
        raise TypeError('attached environment IO must be awaited')

    def _send_frame(self, *args, **kwargs):
        raise TypeError('attached environment IO must be awaited')

    def next_message(self, **kwargs):
        raise TypeError('attached environment IO must be awaited')

    def close(self, **kwargs):
        raise TypeError('attached environment cleanup must be awaited')

    def stderr_tail(self):
        return self._stderr_tail.decode("utf8", errors="replace")[-4096:]

    def sigint(self):
        raise TypeError('opaque process has no host signal capability')
