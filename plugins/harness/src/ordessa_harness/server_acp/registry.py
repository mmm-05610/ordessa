"""Ownership of live managed ACP channels, and the one run record each owns.

The registry is the only place that maps (harnessId, projectId) to a
connection: a re-acquire of a pair whose channel is still active returns that
same connection and never a second Agent, a second run, or a silently moved
binding.  Release and abnormal exit race through one lock-protected claim -
exactly one of them ends the run record, and each owns its ledger transition.

Ordinary ACP traffic remains a line relay. The registry observes correlated
native session creation and owns a separate, explicit read-only configuration
query. Only replies to its reserved queries are intercepted; client requests
are never answered or replayed on their behalf. Attaching/detaching sockets
is not a lifecycle event, and ending a connection never fabricates a reply.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from uuid import uuid4
from typing import Any, Callable, Mapping

from ordessa_harness.server_acp.runs import (
    channel_run_view, end_run_failed, end_run_released, open_run,
)
from ordessa_server.ids import opaque_id

_OWNER_CONFIGURATION_METHODS = frozenset({
    '_ordessa/session/configuration',
    '_ordessa/session/configuration/apply',
    '_ordessa/session/configuration/operation',
})


@dataclass(frozen=True)
class NativeSessionObservation:
    """A live Agent response correlated to this channel's session/new request.

    This is not a runtime generation or a configuration confirmation.
    """

    connection_id: str
    execution_id: str
    ledger_session_id: str
    native_session_id: str


class NativeConfigurationUnavailable(RuntimeError):
    """No independent live configuration evidence; never an applied receipt."""


@dataclass(frozen=True)
class NativeConfigurationObservation:
    owner: NativeSessionObservation
    native_generation: str
    busy: bool
    config_options_json: str

    @property
    def config_options(self) -> list:
        # Keep the observation immutable even if a consumer edits its DTO.
        return json.loads(self.config_options_json)


@dataclass
class _ConfigurationQuery:
    ready: threading.Event
    response: dict | None = None


class _ObservedTransport:
    """Observe outgoing client requests without changing their wire bytes."""

    def __init__(self, connection: _Channel, inner: Any) -> None:
        self._connection = connection
        self._inner = inner

    def send_line(self, text: str) -> None:
        self._connection.observe_client_line(text)
        try:
            self._inner.send_line(text)
        except BaseException:
            self._connection.invalidate_client_line(text)
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _send_owner_query(self, text: str) -> None:
        # Already reserved by the channel; not a client-selected request ID.
        self._inner.send_line(text)


class _Channel:
    """One live connection: its transport, its run identity, its subscribers."""

    def __init__(self, *, connection_id: str, harness_id: str,
                 workspace_id: str, profile_id: str, cwd: str,
                 session_scope_id: str | None = None) -> None:
        self.connection_id = connection_id
        self.harness_id = harness_id
        self.workspace_id = workspace_id
        self.profile_id = profile_id
        self.cwd = cwd
        self.session_scope_id = session_scope_id
        self.session_id: str | None = None
        self.execution_id: str | None = None
        self.binding: dict[str, Any] | None = None
        self.transport: Any = None
        self.exit_code: int | None = None
        self._lock = threading.Lock()
        self._subscribers: set[tuple[Any, Any]] = set()
        self._ended = False
        self._seen_request_ids: set[tuple[type, str | int]] = set()
        self._pending_new: set[tuple[type, str | int]] = set()
        self._native_sessions: dict[str, NativeSessionObservation] = {}
        self._configuration_queries: dict[str, _ConfigurationQuery] = {}
        self._owner_query_ids: set[str] = set()

    @property
    def pair(self) -> tuple[str, ...]:
        base = (self.harness_id, self.workspace_id)
        return base if self.session_scope_id is None else (*base, self.session_scope_id)

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
            # Owner-only replies never reach attached chat relay sockets.
            if self._observe_configuration_reply(line):
                return
            self._observe_agent_line(line)
            subscribers = list(self._subscribers)
        for loop, sink in subscribers:
            self._schedule(loop, sink, line)

    def finish(self) -> None:
        """Mark ended once; every attached socket then sees the channel close."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
            self._pending_new.clear()
            self._native_sessions.clear()
            for pending in self._configuration_queries.values():
                pending.ready.set()
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for loop, sink in subscribers:
            self._schedule(loop, sink, None)

    @property
    def ended(self) -> bool:
        with self._lock:
            return self._ended

    @staticmethod
    def _request_id(frame: Mapping[str, Any]) -> tuple[type, str | int] | None:
        value = frame.get("id")
        if type(value) not in (str, int) or value == "":
            return None
        return (type(value), value)

    def observe_client_line(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            return
        if frame.get('method') in _OWNER_CONFIGURATION_METHODS:
            raise NativeConfigurationUnavailable('configuration RPC is reserved for the native owner')
        request_id = self._request_id(frame)
        if request_id is None or not isinstance(frame.get("method"), str):
            return
        with self._lock:
            if self._ended:
                return
            if frame.get('id') in self._owner_query_ids:
                raise NativeConfigurationUnavailable('client request conflicts with owner query')
            if request_id in self._seen_request_ids:
                # A reused ID makes even the first outstanding reply
                # ambiguous. Keep the ID spent and refuse that observation.
                self._pending_new.discard(request_id)
                return
            # Exhaustion disables new observations; it never promotes an
            # unbounded stream of client-selected request IDs into evidence.
            if len(self._seen_request_ids) >= 4096:
                return
            self._seen_request_ids.add(request_id)
            if frame["method"] == "session/new":
                self._pending_new.add(request_id)

    def invalidate_client_line(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(frame, dict):
            return
        request_id = self._request_id(frame)
        if request_id is not None:
            with self._lock:
                self._pending_new.discard(request_id)

    def _observe_agent_line(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0" or "method" in frame:
            return
        request_id = self._request_id(frame)
        if request_id is None or request_id not in self._pending_new:
            return
        self._pending_new.remove(request_id)
        result = frame.get("result")
        if ("error" in frame or not isinstance(result, dict) or
                type(result.get("sessionId")) is not str or not result["sessionId"] or
                result["sessionId"].strip() != result["sessionId"] or
                not self.execution_id or not self.session_id):
            return
        native_id = result["sessionId"]
        if len(self._native_sessions) >= 128 and native_id not in self._native_sessions:
            return
        self._native_sessions[native_id] = NativeSessionObservation(
            self.connection_id, self.execution_id, self.session_id, native_id)

    def native_session_observation(self, native_id: str) -> NativeSessionObservation | None:
        with self._lock:
            return None if self._ended else self._native_sessions.get(native_id)

    def _observe_configuration_reply(self, line: str) -> bool:
        """Called under the channel lock. Keep spent IDs to swallow late replies."""
        if not self._owner_query_ids:
            return False
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            return False
        # JSON-RPC is bidirectional: an Agent request can legally use the same
        # ID as our outstanding request. Only responses belong to our waiter.
        if not isinstance(frame, dict) or 'method' in frame or type(frame.get('id')) is not str:
            return False
        if frame['id'] not in self._owner_query_ids:
            return False
        pending = self._configuration_queries.get(frame['id'])
        if pending is not None and not pending.ready.is_set():
            if (len(line.encode('utf-8')) <= 262144 and frame.get('jsonrpc') == '2.0'
                    and 'method' not in frame and ('result' in frame) != ('error' in frame)):
                pending.response = frame
            pending.ready.set()
        return True

    def _configuration_rpc(self, native_id: str, method: str, params: Mapping[str, Any],
                           *, timeout: float = 10) -> tuple[NativeSessionObservation, dict]:
        """Internal bounded RPC. Admission/operation authority is a caller obligation.

        Only these native configuration methods exist; client relay cannot call
        them. A reply is native data, not a C4 permit or applied receipt.
        """
        if method not in _OWNER_CONFIGURATION_METHODS or params.get('sessionId') != native_id:
            raise ValueError('unsupported owner configuration RPC')
        try:
            payload = json.dumps(dict(params), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid owner configuration payload') from exc
        if len(payload.encode('utf-8')) > 65536:
            raise ValueError('owner configuration payload outside bounds')
        if type(native_id) is not str or not native_id or len(native_id) > 4096:
            raise ValueError('native session identity required')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise ValueError('configuration query timeout outside bounds')
        with self._lock:
            owner = self._native_sessions.get(native_id)
            if self._ended or owner is None or not isinstance(self.transport, _ObservedTransport):
                raise NativeConfigurationUnavailable('native session owner unavailable')
            if len(self._owner_query_ids) >= 4096 or len(self._configuration_queries) >= 16:
                raise NativeConfigurationUnavailable('configuration query capacity exhausted')
            for _ in range(8):
                request_id = f'ordessa-config-{uuid4().hex}'
                if (str, request_id) not in self._seen_request_ids and request_id not in self._owner_query_ids:
                    break
            else:
                raise NativeConfigurationUnavailable('configuration query identity collision')
            pending = _ConfigurationQuery(threading.Event())
            self._owner_query_ids.add(request_id)
            self._configuration_queries[request_id] = pending
        try:
            try:
                self.transport._send_owner_query(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                    'method': method, 'params': json.loads(payload)}))
            except Exception as exc:
                raise NativeConfigurationUnavailable('native configuration query transport failed') from exc
            if not pending.ready.wait(timeout):
                raise NativeConfigurationUnavailable('configuration query timed out')
            with self._lock:
                if self._ended or self._native_sessions.get(native_id) is not owner:
                    raise NativeConfigurationUnavailable('native session owner changed')
                response = pending.response
            if response is None or 'error' in response:
                raise NativeConfigurationUnavailable('native configuration query refused or unavailable')
            result = response['result']
            if not isinstance(result, dict) or result.get('sessionId') != native_id:
                raise NativeConfigurationUnavailable('malformed native configuration evidence')
            try:
                json.dumps(result, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise NativeConfigurationUnavailable('invalid native configuration JSON') from exc
            return owner, result
        finally:
            with self._lock:
                self._configuration_queries.pop(request_id, None)

    def query_native_configuration(self, native_id: str, *, timeout: float = 10) -> NativeConfigurationObservation:
        """Independent live configuration read; never a native effect."""
        owner, result = self._configuration_rpc(native_id, '_ordessa/session/configuration',
                                               {'sessionId': native_id}, timeout=timeout)
        if (result.get('sessionId') != native_id
                    or type(result.get('generation')) is not str or not result['generation']
                    or result['generation'].strip() != result['generation'] or len(result['generation']) > 4096
                    or type(result.get('busy')) is not bool or not isinstance(result.get('configOptions'), list)
                    or any(not isinstance(option, dict) or type(option.get('id')) is not str
                           or not option['id'] or 'currentValue' not in option for option in result['configOptions'])):
            raise NativeConfigurationUnavailable('malformed native configuration evidence')
        options_json = json.dumps(result['configOptions'], allow_nan=False)
        if len({option['id'] for option in result['configOptions']}) != len(result['configOptions']):
            raise NativeConfigurationUnavailable('duplicate native configuration options')
        return NativeConfigurationObservation(owner, result['generation'], result['busy'], options_json)

    @staticmethod
    def _schedule(loop: Any, sink: Callable[[Any], None], item: Any) -> None:
        try:
            loop.call_soon_threadsafe(sink, item)
        except RuntimeError:
            pass  # the socket's own loop is gone; its detach is moot


class SessionAcquisitionRefused(ValueError):
    """An invalid, exhausted or already terminal session acquisition nonce."""


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
        self._by_pair: dict[tuple[str, ...], _Channel] = {}
        self._scope_locks: dict[tuple[str, ...], threading.RLock] = {}
        self._spent_scopes: set[tuple[str, ...]] = set()
        self._by_id: dict[str, _Channel] = {}

    # -- lifecycle ---------------------------------------------------------

    def acquire(self, *, harness_id: str, workspace_id: str,
                profile_id: str, cwd: str, session_scope_id: str | None = None) -> dict[str, Any]:
        if session_scope_id is not None:
            if (type(session_scope_id) is not str or not session_scope_id
                    or len(session_scope_id) > 128 or session_scope_id.strip() != session_scope_id
                    or any(ord(char) < 32 for char in session_scope_id)):
                raise SessionAcquisitionRefused("invalid session acquisition scope")
            pair = (harness_id, workspace_id, session_scope_id)
            with self._lock:
                if pair not in self._scope_locks:
                    if len(self._scope_locks) >= 4096:
                        raise SessionAcquisitionRefused("session acquisition scope capacity exhausted")
                    self._scope_locks[pair] = threading.RLock()
                scope_lock = self._scope_locks[pair]
            # One scope is an acquisition identity, not a Profile/native UID.
            # Serialize its establishment to avoid speculative duplicate Agents.
            with scope_lock:
                with self._lock:
                    if pair in self._spent_scopes and pair not in self._by_pair:
                        raise SessionAcquisitionRefused("session acquisition scope is terminal")
                return self._acquire(harness_id=harness_id, workspace_id=workspace_id,
                                     profile_id=profile_id, cwd=cwd, session_scope_id=session_scope_id)
        return self._acquire(harness_id=harness_id, workspace_id=workspace_id,
                             profile_id=profile_id, cwd=cwd)

    def _acquire(self, *, harness_id: str, workspace_id: str, profile_id: str,
                 cwd: str, session_scope_id: str | None = None) -> dict[str, Any]:
        pair = ((harness_id, workspace_id) if session_scope_id is None
                else (harness_id, workspace_id, session_scope_id))
        with self._lock:
            existing = self._by_pair.get(pair)
            if existing is not None:
                return existing.public_result()
            connection = _Channel(
                connection_id=opaque_id("conn"), harness_id=harness_id,
                workspace_id=workspace_id, profile_id=profile_id, cwd=cwd,
                session_scope_id=session_scope_id,
            )
        # Launch first: a provider that refuses starts no process and records
        # no run.  The ledger row appears only for a channel that is up.
        transport = self._launch(
            harness_id=harness_id, cwd=cwd,
            on_line=connection.deliver,
            on_exit=lambda code: self._handle_exit(connection, code),
        )
        # A launched scope never creates a second execution, including after
        # failed ledger establishment. Reuse is only for its existing owner.
        if session_scope_id is not None:
            with self._lock:
                self._spent_scopes.add(pair)
        try:
            connection.session_id, connection.execution_id, connection.binding = open_run(
                session_records=self._records, profile_records=self._profiles,
                connection_id=connection.connection_id, harness_id=harness_id,
                workspace_id=workspace_id, profile_id=profile_id, cwd=cwd,
            )
        except BaseException:
            transport.terminate()
            raise
        connection.transport = _ObservedTransport(connection, transport)
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
            self._handle_exit(connection, connection.exit_code)
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

    def native_session_observation(self, connection_id: str,
                                   native_session_id: str) -> NativeSessionObservation | None:
        """Read only an Agent-confirmed native session on this live connection."""
        channel = self.get(connection_id)
        return None if channel is None else channel.native_session_observation(native_session_id)

    def query_native_configuration(self, connection_id: str, native_session_id: str,
                                   *, timeout: float = 10) -> NativeConfigurationObservation:
        """Plugin-internal control read; not a client wire method or a receipt."""
        channel = self.get(connection_id)
        if channel is None:
            raise NativeConfigurationUnavailable('channel owner unavailable')
        observation = channel.query_native_configuration(native_session_id, timeout=timeout)
        if (self.get(connection_id) is not channel or channel.ended
                or channel.native_session_observation(native_session_id) is not observation.owner):
            raise NativeConfigurationUnavailable('channel owner changed')
        return observation

    def recovery_view(self, *, connection_id: str, execution_id: str) -> dict[str, Any]:
        """Read a durable run and its exact live association without reviving it.

        A new registry after Server restart has no transport lease. The old
        ledger row remains inspectable, but even an in-flight row cannot make
        the old connection attachable. Terminal rows are never turned back
        into live channels, and a frame cannot create an execution here.
        """
        if not connection_id or not execution_id:
            raise ValueError("connection and execution identity required")
        row = self._records.get_turn_context(execution_id)
        if str(row["id"]) != execution_id:
            raise ValueError("ledger execution identity changed")
        run = channel_run_view(row)
        with self._lock:
            live = self._by_id.get(connection_id)
            attached = (live is not None and live.execution_id == execution_id
                        and live.session_id == run["sessionId"] and not live.ended
                        and run["inFlight"])
        return {"run": run, "connectionId": connection_id if attached else None,
                "attachable": attached}

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
