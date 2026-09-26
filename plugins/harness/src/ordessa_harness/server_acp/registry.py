"""Ownership of live managed ACP channels, and the one run record each owns.

The registry is the only place that maps (harnessId, projectId) to a
connection: a re-acquire of a pair whose channel is still active returns that
same connection and never a second Agent, a second run, or a silently moved
binding.  Release and abnormal exit race through one lock-protected claim -
exactly one of them ends the run record, and each owns its ledger transition.

The registry never reads a frame.  It hands transport lines to whatever
sockets are currently attached (attaching and detaching is not a lifecycle
event: a client that goes quiet keeps its channel), and a finished connection
tells its sockets the channel ended - without answering anything for them.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from ordessa_harness.server_acp.runs import (
    end_run_failed, end_run_released, open_run,
)
from ordessa_server.ids import opaque_id


class _Channel:
    """One live connection: its transport, its run identity, its subscribers."""

    def __init__(self, *, connection_id: str, harness_id: str,
                 workspace_id: str, profile_id: str, cwd: str) -> None:
        self.connection_id = connection_id
        self.harness_id = harness_id
        self.workspace_id = workspace_id
        self.profile_id = profile_id
        self.cwd = cwd
        self.session_id: str | None = None
        self.execution_id: str | None = None
        self.binding: dict[str, Any] | None = None
        self.transport: Any = None
        self.exit_code: int | None = None
        self._lock = threading.Lock()
        self._subscribers: set[tuple[Any, Any]] = set()
        self._ended = False

    @property
    def pair(self) -> tuple[str, str]:
        return (self.harness_id, self.workspace_id)

    def public_result(self) -> dict[str, Any]:
        return {
            "connectionId": self.connection_id,
            "executionId": self.execution_id,
            "binding": dict(self.binding or {}),
        }

    def attach(self, loop: Any, sink: Callable[[Any], None]) -> None:
        """Subscribe one relay socket; the sink receives lines, then None once."""
        with self._lock:
            if self._ended:
                ended = True
            else:
                ended = False
                self._subscribers.add((loop, sink))
        if ended:
            sink(None)

    def detach(self, loop: Any, sink: Callable[[Any], None]) -> None:
        with self._lock:
            self._subscribers.discard((loop, sink))

    def deliver(self, line: str) -> None:
        with self._lock:
            if self._ended:
                return
            subscribers = list(self._subscribers)
        for loop, sink in subscribers:
            self._schedule(loop, sink, line)

    def finish(self) -> None:
        """Mark ended once; every attached socket then sees the channel close."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for loop, sink in subscribers:
            self._schedule(loop, sink, None)

    @property
    def ended(self) -> bool:
        with self._lock:
            return self._ended

    @staticmethod
    def _schedule(loop: Any, sink: Callable[[Any], None], item: Any) -> None:
        try:
            loop.call_soon_threadsafe(sink, item)
        except RuntimeError:
            pass  # the socket's own loop is gone; its detach is moot


class AcpChannelRegistry:
    """`launch` is the composition's transport provider (seam doc section 5).

    `launch(harness_id, cwd, on_line, on_exit)` must return a started
    transport or raise without having started anything.  A Harness plugin's
    transparent-transport entry plugs in at this callback; the Server side of
    the channel is identical whichever provider is composed.
    """

    def __init__(self, *, session_records, profile_records,
                 launch: Callable[..., Any]) -> None:
        self._records = session_records
        self._profiles = profile_records
        self._launch = launch
        self._lock = threading.RLock()
        self._by_pair: dict[tuple[str, str], _Channel] = {}
        self._by_id: dict[str, _Channel] = {}

    # -- lifecycle ---------------------------------------------------------

    def acquire(self, *, harness_id: str, workspace_id: str,
                profile_id: str, cwd: str) -> dict[str, Any]:
        with self._lock:
            existing = self._by_pair.get((harness_id, workspace_id))
            if existing is not None:
                return existing.public_result()
            connection = _Channel(
                connection_id=opaque_id("conn"), harness_id=harness_id,
                workspace_id=workspace_id, profile_id=profile_id, cwd=cwd,
            )
        # Launch first: a provider that refuses starts no process and records
        # no run.  The ledger row appears only for a channel that is up.
        transport = self._launch(
            harness_id=harness_id, cwd=cwd,
            on_line=connection.deliver,
            on_exit=lambda code: self._handle_exit(connection, code),
        )
        try:
            connection.session_id, connection.execution_id, connection.binding = open_run(
                session_records=self._records, profile_records=self._profiles,
                connection_id=connection.connection_id, harness_id=harness_id,
                workspace_id=workspace_id, profile_id=profile_id, cwd=cwd,
            )
        except BaseException:
            transport.terminate()
            raise
        connection.transport = transport
        with self._lock:
            racer = self._by_pair.get(connection.pair)
            if racer is not None:
                winner = racer
            else:
                winner = None
                self._by_pair[connection.pair] = connection
                self._by_id[connection.connection_id] = connection
        if winner is not None:
            # Same pair, concurrent open: the other connection owns the run
            # now; this one is released with that real reason, not hidden.
            end_run_released(self._records, connection.execution_id, reason="superseded")
            connection.finish()
            transport.terminate()
            return winner.public_result()
        if connection.exit_code is not None:
            # The Agent died in the launch window; the same claim that would
            # have run on exit applies retroactively before anything attached.
            self._end_exit(connection)
        return connection.public_result()

    def release(self, connection_id: str, *, reason: str = "released") -> dict[str, Any] | None:
        """Stand a channel down - and claim the release only on proof.

        A transport that can be asked (`request_release`) answers with the
        owning entry's OS-confirmed receipt; until that confirmation arrives
        nothing here is settled: the ownership record and the run record stay
        exactly where they are, so the same release can be retried and can
        still honestly succeed later.  The transport ending (relay, sockets)
        and the resource release (ledger, ownership) are deliberately separate
        events; a `released: True` answer is only ever built from the first.
        """
        with self._lock:
            connection = self._by_id.get(connection_id)
            if connection is None:
                return None
        transport = connection.transport
        if transport is not None:
            request_release = getattr(transport, "request_release", None)
            if callable(request_release):
                outcome = request_release()
                if not (isinstance(outcome, dict) and outcome.get("confirmed") is True):
                    return {
                        "released": False, "connectionId": connection_id,
                        "executionId": connection.execution_id,
                        "sessionId": connection.session_id,
                        "reason": str((outcome or {}).get("reason")
                                      or "release-unconfirmed"),
                    }
            else:
                transport.terminate()
        with self._lock:
            # Exactly one caller wins the claim; a concurrent release that
            # arrives after the settlement never re-writes the ledger.
            registered = self._by_id.pop(connection_id, None) is connection
            if registered:
                self._by_pair.pop(connection.pair, None)
        if registered:
            end_run_released(self._records, str(connection.execution_id), reason=reason)
        connection.finish()
        return {
            "released": True, "connectionId": connection_id,
            "executionId": connection.execution_id, "sessionId": connection.session_id,
            "endReason": reason,
        }

    def stop_all(self) -> None:
        for connection_id in list(self._by_id):
            result = self.release(connection_id, reason="server-stop")
            if result is not None and result.get("released") is not True:
                # Shutdown cannot leave a managed process behind on an
                # unproven release: force the entry's own reclaim path
                # (stdin EOF -> OS-confirmed release), then settle the run
                # with this real ending reason.  That is a server-stop
                # termination, not a claimed release.
                connection = self.get(connection_id)
                if connection is None:
                    continue
                if connection.transport is not None:
                    connection.transport.terminate()
                with self._lock:
                    registered = (self._by_id.pop(connection_id, None) is connection)
                    if registered:
                        self._by_pair.pop(connection.pair, None)
                if registered:
                    end_run_released(self._records, str(connection.execution_id),
                                     reason="server-stop")
                connection.finish()

    # -- reads (route/admission side) ---------------------------------------

    def get(self, connection_id: str) -> _Channel | None:
        with self._lock:
            return self._by_id.get(connection_id)

    # -- the Agent's own exit ------------------------------------------------

    def _handle_exit(self, connection: _Channel, code: int | None) -> None:
        connection.exit_code = code
        with self._lock:
            registered = self._by_id.get(connection.connection_id) is connection
            if registered:
                self._by_id.pop(connection.connection_id, None)
                self._by_pair.pop(connection.pair, None)
        if registered:
            self._end_exit(connection)
        else:
            # Released (or superseded) already wrote the terminal transition;
            # the sockets still deserve the honest "channel ended".
            connection.finish()

    def _end_exit(self, connection: _Channel) -> None:
        end_run_failed(
            self._records, str(connection.execution_id),
            f"ACP_AGENT_EXITED-{connection.exit_code}",
        )
        connection.finish()
