"""Thin task handles over the single Decision runner and evidence authority."""
import asyncio
from collections.abc import Mapping

from ordessa_decision.definitions.errors import EvidenceUnknown
from ordessa_decision.definitions.models import DecisionResult
from .runner import _execute_decision, read_result


class DecisionManagerError(RuntimeError):
    """A bounded public Manager lifecycle refusal with a fixed safe code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class DecisionRun:
    """Live task handle or read-only handle to an existing evidence run."""

    __slots__ = ('_services', '_run_id', '_task')

    def __init__(self, services, run_id, task=None):
        self._services = services
        self._run_id = run_id
        self._task = task

    @property
    def run_id(self):
        return self._run_id

    async def snapshot(self):
        """Return the current public projection from the original evidence port."""
        return await read_result(self._run_id, services=self._services)

    async def evidence(self):
        """Return the evidence events from the original public read projection."""
        snapshot = await self.snapshot()
        if not isinstance(snapshot, Mapping) or snapshot.get('status') not in (
            'running', 'completed', 'interrupted'
        ):
            raise EvidenceUnknown(self._run_id)
        events = snapshot.get('events')
        if not isinstance(events, (list, tuple)):
            raise EvidenceUnknown(self._run_id)
        return tuple(events)

    async def result(self):
        """Return the live DecisionResult, or reconstruct its committed history."""
        if self._task is not None:
            result = await asyncio.shield(self._task)
            if result.run_id != self._run_id:
                raise EvidenceUnknown(self._run_id)
            return result
        snapshot = await self.snapshot()
        terminal = snapshot.get('terminal') if isinstance(snapshot, Mapping) else None
        if (not isinstance(snapshot, Mapping) or snapshot.get('status') != 'completed'
                or not isinstance(terminal, Mapping)
                or terminal.get('run_id') != self._run_id
                or terminal.get('status') not in (
                    'completed', 'failed', 'cancelled', 'budget_exhausted'
                )
                or not isinstance(terminal.get('result'), Mapping)):
            raise EvidenceUnknown(self._run_id)
        try:
            result = DecisionResult.from_dict(terminal['result'])
            terminal_digest = terminal.get('terminal_digest', terminal.get('result_digest'))
            if (result.run_id != self._run_id or terminal.get('status') != result.status
                    or terminal_digest != result.result_digest
                    or terminal.get('result_digest', terminal_digest) != terminal_digest):
                raise ValueError()
            return result
        except (TypeError, ValueError):
            raise EvidenceUnknown(self._run_id) from None


class DecisionManager:
    """Owns only its submitted tasks; provider and evidence services are borrowed."""

    def __init__(self, services):
        self._services = services
        self._active = set()
        self._owned = {}
        self._closed = False

    async def submit(self, request, flow):
        """Start a run and return only after the runner verifies run.started."""
        self._require_open()
        loop = asyncio.get_running_loop()
        started = loop.create_future()
        task = None

        def announce(run_id):
            self._owned[run_id] = task
            if not started.done():
                started.set_result(run_id)

        task = asyncio.create_task(_execute_decision(
            request, flow=flow, services=self._services, on_started=announce))
        self._active.add(task)

        def completed(done):
            self._active.discard(done)
            for run_id, owned_task in tuple(self._owned.items()):
                if owned_task is done:
                    del self._owned[run_id]
            if not done.cancelled():
                done.exception()

        task.add_done_callback(completed)
        try:
            done, _ = await asyncio.wait((task, started), return_when=asyncio.FIRST_COMPLETED)
            if started in done:
                return DecisionRun(self._services, started.result(), task)
            # Surface pre-start ContractError/EvidenceUnknown; never invent a handle.
            task.result()
            raise EvidenceUnknown()
        except asyncio.CancelledError as cancellation:
            # Do not await a cancellation-resistant flow here. The Manager keeps
            # ownership until the task actually finishes, so close still refuses.
            if not task.done():
                task.cancel()
            if started.done() and not started.cancelled():
                run_id = started.result()
                cancellation.run_id = run_id
                if hasattr(cancellation, 'add_note'):
                    cancellation.add_note('decision run_id=' + run_id)
            raise

    def get(self, run_id):
        """Return a read-only handle; this does not adopt or resume a task."""
        self._require_open()
        return DecisionRun(self._services, run_id)

    async def cancel(self, run_id):
        """Request cancellation of an active task submitted by this Manager."""
        self._require_open()
        task = self._owned.get(run_id)
        if task is None or task.done():
            raise DecisionManagerError('run_not_owned_or_active')
        if not task.cancel():
            raise DecisionManagerError('run_not_owned_or_active')
        return True

    async def close(self):
        """Close this idle Manager; borrowed services remain open."""
        self._require_open()
        if any(not task.done() for task in self._active):
            raise DecisionManagerError('manager_active_runs')
        self._closed = True

    def _require_open(self):
        if self._closed:
            raise DecisionManagerError('manager_closed')
