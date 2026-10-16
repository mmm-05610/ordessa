"""Thin asyncio adapters over the original infra-owned pipes; no spawn or fs.

Stdlib pipe transports drain stdout/stderr independently. No blocking read
worker survives cancellation; pending read cancellation leaves buffered bytes.
Bounded unread output faults explicitly instead of silently dropping data.
"""
import asyncio

from ordessa_environments import EnvironmentRefused, EnvironmentOperationUnknown, ProcessWaitTimeout


class _Output(asyncio.Protocol):
    def __init__(self, owner):
        self.owner=owner
        self.data=bytearray()
        self.eof=False
        self.error=False
        self.transport=None
        self.event=asyncio.Event()
        self.busy=False

    def connection_made(self,transport):
        self.transport=transport

    def data_received(self,data):
        if len(self.data)+len(data)>4*1024*1024:
            self.error=True
            self.owner._io_unknown=True
            self.transport.close()
        else:
            self.data.extend(data)
        self.event.set()

    def connection_lost(self,error):
        self.eof=True
        if error is not None:
            self.error=True
            self.owner._io_unknown=True
        self.event.set()

    async def read(self,max_bytes,timeout):
        if self.busy:
            raise EnvironmentRefused('concurrent reads on the same output are refused')
        self.busy=True
        deadline=None if timeout is None else asyncio.get_running_loop().time()+timeout
        try:
            while True:
                if self.owner.released:
                    raise EnvironmentRefused('process transport was released')
                if self.error:
                    raise EnvironmentOperationUnknown('owned output transport failed or exceeded bounded buffer',identity=self.owner.identity)
                if self.data:
                    count=min(max_bytes,len(self.data));result=bytes(self.data[:count]);del self.data[:count]
                    return result
                if self.eof:
                    return b''
                remaining=None if deadline is None else deadline-asyncio.get_running_loop().time()
                if remaining is not None and remaining<=0:
                    raise ProcessWaitTimeout('owned output read timed out')
                self.event.clear()
                try:
                    await asyncio.wait_for(self.event.wait(),remaining)
                except TimeoutError:
                    raise ProcessWaitTimeout('owned output read timed out') from None
        finally:
            self.busy=False


class _InputProtocol(asyncio.streams.FlowControlMixin):
    def __init__(self,loop):
        super().__init__(loop=loop)
        self.closed=loop.create_future()

    def connection_lost(self,error):
        super().connection_lost(error)
        if not self.closed.done():self.closed.set_result(None)

    def _get_close_waiter(self,stream):
        return self.closed


class PipeIO:
    def __init__(self,owner):
        self.owner=owner
        self.loop=asyncio.get_running_loop()
        self.stdout,self.stderr=_Output(owner),_Output(owner)
        self.writer=None
        self.transports=[]
        self.closed=False
        self.bind_task=None

    async def _bind(self):
        try:
            for raw,protocol in [(self.owner.popen.stdout,self.stdout),(self.owner.popen.stderr,self.stderr)]:
                transport,_=await self.loop.connect_read_pipe(lambda:protocol,raw)
                self.transports.append(transport)
            protocol=_InputProtocol(self.loop)
            transport,_=await self.loop.connect_write_pipe(lambda:protocol,self.owner.popen.stdin)
            self.transports.append(transport)
            self.writer=asyncio.StreamWriter(transport,protocol,None,self.loop)
            if self.closed:
                self.close_now()
                raise EnvironmentRefused('process transport released during IO binding')
        except BaseException:
            self.close_now()
            raise

    async def bind(self):
        if asyncio.get_running_loop() is not self.loop:
            raise EnvironmentRefused('process byte IO is bound to a different owner loop')
        if self.closed:raise EnvironmentRefused('process transport was released')
        if self.bind_task is None:
            self.bind_task=self.loop.create_task(self._bind())
            self.bind_task.add_done_callback(lambda task:task.exception() if not task.cancelled() else None)
        # Cancellation stops this waiter, not a hidden byte consumer. Binding
        # only installs the single owner transports and keeps bytes in buffers.
        await asyncio.shield(self.bind_task)

    def close_now(self):
        self.closed=True
        def close():
            for transport in self.transports:
                if transport.is_closing():continue
                if hasattr(transport,'abort'):transport.abort()
                else:transport.close()
            self.stdout.event.set();self.stderr.event.set()
        if self.loop.is_closed():
            # Stdlib already closed its transports on loop shutdown. Raw
            # descriptors are closed by owner release as well.
            return
        try:
            if asyncio.get_running_loop() is self.loop:close();return
        except RuntimeError:
            pass
        self.loop.call_soon_threadsafe(close)
