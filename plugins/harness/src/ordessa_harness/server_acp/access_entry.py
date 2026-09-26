"""The managed channel's transport, spoken through the plugin's access entry.

`plugins/harness/runtime/access-entry.mjs` is the plugin's one
production entry for connecting to a Harness: it launches the named adapter,
relays every ACP line byte-transparently, and releases what it started only
with an OS-confirmed receipt.  This class is the Server-side counterpart and
owns exactly the protocol needed to use it and nothing else:

  * a channel is not established until the entry's own `connect` has been
    confirmed - no ACP frame is ever written into a connection that was not
    established, and `connect` itself transmits no ACP frame, so the Server
    still never speaks `initialize`/`session/new`/`prompt` for the client;
  * control-plane messages - the entry's replies to our `connect`/`close`
    ops and its lifecycle events - are consumed here and never relayed.  An
    entry failure that carries the id of a client request must not reach the
    client dressed up as an Agent answer, and the receipt of our own close
    is not ACP;
  * the Agent's own end arrives as the entry's `transport_end` event, which
    fires even while the entry process is still alive, and the release path
    goes through the entry's `close` op so the Harness process tree is
    reclaimed by the component that owns it.

Like the direct NDJSON transport it wraps, this class never parses, tracks or
answers an ACP frame: relayed lines pass through byte-for-byte.
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable, Mapping

from ordessa_harness.server_acp.transport import NDJSONTransport, TransportClosed


class _PendingControl:
    """One outstanding control request awaiting the entry's own reply."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.reply: dict[str, Any] | None = None

    def resolve(self, reply: dict[str, Any] | None) -> None:
        self.reply = reply
        self.done.set()


class AccessEntryTransport:
    """A started plugin entry carrying one ACP channel behind the registry.

    `entry` is the access-entry module path, `node` the interpreter, and
    `adapter` the declared launch reference (`{"command", "args"}`) the entry
    spawns once `connect` names it.  `on_line` receives only the Agent's own
    frames; `on_exit` fires exactly once with a real ending - the entry
    process's return code when the entry itself dies, or the entry's
    `transport_end` reason when the Harness does - and never fabricates a
    frame for requests still in flight.
    """

    def __init__(self, *, node: str, entry: str, harness_id: str, cwd: str,
                 adapter: Mapping[str, Any], on_line: Callable[[str], None],
                 on_exit: Callable[[Any], None],
                 environment: dict[str, str] | None = None,
                 connect_timeout: float = 60.0, close_timeout: float = 12.0) -> None:
        self._harness_id = harness_id
        self._cwd = cwd
        self._adapter = {"command": str(adapter["command"]),
                         "args": [str(arg) for arg in adapter.get("args", [])]}
        self._on_line = on_line
        self._on_exit = on_exit
        self._connect_timeout = connect_timeout
        self._close_timeout = close_timeout
        self._inner = NDJSONTransport(
            argv=[node, entry, "--native"], cwd=cwd, environment=environment,
            on_line=self._classify, on_exit=self._entry_exit,
        )
        self._control_lock = threading.Lock()
        self._control: dict[str, _PendingControl] = {}
        self._end_lock = threading.Lock()
        self._end_reported = False
        self._terminated = False
        self._established = False
        self._fatal_refusal: dict[str, Any] | None = None
        self._events_seen: list[str] = []
        #: The entry's own release report from the last `close` (OS-confirmed or not).
        self.release_report: Any = None
        self._release_lock = threading.Lock()
        self._pending_close: _PendingControl | None = None
        #: Only a confirmed release is cached; a failure stays re-askable.
        self._release_confirmed: dict[str, Any] | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> "AccessEntryTransport":
        """Spawn the entry and establish the connection before anything rides it.

        A refused or unanswered `connect` reclaims the entry process (which
        reclaims any half-spawned Harness with it) and raises: the registry's
        zero-launch order is kept at this layer too.
        """
        self._inner.start()
        pending = self._request_control({
            "op": "connect", "harness": self._harness_id,
            "launch": dict(self._adapter), "directory": self._cwd,
        })
        if not pending.done.wait(self._connect_timeout):
            self.terminate()
            raise TransportClosed(
                "the access entry never answered its connect request")
        reply = pending.reply
        if reply is None or reply.get("ok") is not True:
            code = ((reply or self._fatal_refusal or {}).get("error") or {}).get(
                "code", "ACP_CONNECT_NO_REPLY")
            self.terminate()
            raise RuntimeError(f"ACP_CHANNEL_CONNECT_REFUSED-{code}")
        self._established = True
        return self

    @property
    def pid(self) -> int | None:
        """The entry process; the Harness it owns is released through `close`."""
        return self._inner.pid

    @property
    def established(self) -> bool:
        return self._established

    def send_line(self, text: str) -> None:
        """One client ACP frame, forwarded as written - the entry relays it."""
        self._inner.send_line(text)

    def terminate(self) -> None:
        """Force the ending: ask the entry's release once, then stop the entry
        whatever it answered.

        This is the crash/server-stop cleanup path.  The client-visible
        release answer is `request_release`, which never trades a missing (or
        negative) receipt for a success claim - here the channel is already
        over on the Agent's side, and leaving the entry running behind it is
        not an option either.
        """
        with self._end_lock:
            self._end_reported = True  # this is our own ending, not a crash report
        with self._release_lock:
            if self._established and self._release_confirmed is None:
                if self._pending_close is None:
                    self._pending_close = self._request_control({"op": "close"})
                pending = self._pending_close
                if pending is not None and pending.done.wait(self._close_timeout):
                    self._pending_close = None
                    self._record_receipt(pending.reply)
        self._stop_entry()

    def request_release(self) -> dict[str, Any]:
        """Ask the entry to release what it started, and answer honestly.

        Confirmation is the entry's own OS-confirmed receipt
        (`ok:true` carrying `released:true`): a refusal, a receipt that
        admits a survivor, or silence is returned as `confirmed: False` -
        never as success, because the component that owns the Harness process
        tree has not proved it is gone.  Only a confirmed release is kept: a
        failed receipt leaves the next explicit retry free to ask the entry
        again, which is the whole point of a retryable release.  A close that
        was never answered keeps its pending request - the retry waits on the
        same one, so a late receipt can still confirm and no second close is
        written behind the first.  The entry - the only manager of the
        Harness it owns - is never destroyed for answering badly or being
        slow.
        """
        with self._release_lock:
            if self._release_confirmed is not None:
                return self._release_confirmed
            if not self._established:
                return {"confirmed": False, "reason": "never-established",
                        "report": None}
            pending = self._pending_close
            if pending is None:
                with self._end_lock:
                    self._end_reported = True  # from here this is our own ending
                pending = self._request_control({"op": "close"})
                if pending is None:
                    return {"confirmed": False, "reason": "entry-unreachable",
                            "report": None}
                self._pending_close = pending
            if not pending.done.wait(self._close_timeout):
                # Not cached and the pending is kept: the receipt may still be
                # on its way, and a retry waits on the same request.
                return {"confirmed": False, "reason": "close-timeout",
                        "report": None}
            self._pending_close = None
            outcome = self._record_receipt(pending.reply)
            if outcome["confirmed"]:
                self._stop_entry()
            return outcome

    def _record_receipt(self, reply: dict[str, Any] | None) -> dict[str, Any]:
        """Turn one `close` reply into the honest release outcome.

        Only the confirmation is cached; every failure shape is recomputed
        per attempt, so a later retry can genuinely ask again.
        """
        if self._release_confirmed is not None:
            return self._release_confirmed
        if reply is None:
            return {"confirmed": False, "reason": "entry-exited-without-receipt",
                    "report": None}
        report = reply.get("result") if isinstance(reply.get("result"), dict) \
            else (reply.get("error") or reply)
        self.release_report = report
        if reply.get("ok") is True and report.get("released") is True:
            self._release_confirmed = {
                "confirmed": True, "reason": "released", "report": report}
            return self._release_confirmed
        if reply.get("ok") is not True:
            code = str(((reply.get("error") or {}).get("code")) or "unknown")
            return {"confirmed": False, "reason": f"close-refused-{code}",
                    "report": report}
        return {"confirmed": False, "reason": "release-unconfirmed",
                "report": report}

    def _stop_entry(self) -> None:
        """Stop the entry process exactly once (stdin EOF, then escalation)."""
        with self._end_lock:
            if self._terminated:
                return
            self._terminated = True
        self._inner.terminate()

    # -- the entry's stdout, classified ---------------------------------------

    def _classify(self, line: str) -> None:
        text = line.strip()
        if text.startswith("{"):
            try:
                message = json.loads(text)
            except ValueError:
                message = None
            if isinstance(message, dict) and "jsonrpc" not in message:
                if message.get("ok") is True or message.get("ok") is False:
                    self._resolve_control(message)
                    return
                if isinstance(message.get("event"), str):
                    self._handle_event(message)
                    return
        # Anything that declares itself part of the JSON-RPC conversation -
        # and every line the entry cannot be speaking as itself - is the
        # Agent's frame, relayed exactly as it arrived.
        self._on_line(line)

    def _request_control(self, request: dict[str, Any]) -> _PendingControl | None:
        control_id = uuid.uuid4().hex
        pending = _PendingControl()
        with self._control_lock:
            self._control[control_id] = pending
        try:
            self._inner.send_line(json.dumps({"id": control_id, **request}))
        except TransportClosed:
            with self._control_lock:
                self._control.pop(control_id, None)
            return None
        return pending

    def _resolve_control(self, message: dict[str, Any]) -> None:
        control_id = message.get("id")
        pending = None
        with self._control_lock:
            if isinstance(control_id, str):
                pending = self._control.pop(control_id, None)
        if pending is None:
            # A reply to a request we never made (or an entry-wide failure):
            # control-plane, never an Agent answer - kept only as evidence.
            if message.get("ok") is False and self._fatal_refusal is None:
                self._fatal_refusal = message
            return
        pending.resolve(message)

    def _abandon_control(self) -> None:
        with self._control_lock:
            outstanding, self._control = self._control, {}
        for pending in outstanding.values():
            pending.resolve(None)

    def _handle_event(self, message: dict[str, Any]) -> None:
        event = str(message.get("event"))
        self._events_seen.append(event)
        if event == "transport_end":
            # The entry stays alive after its Harness dies, so a `close` asked
            # of it is still answerable: control waiters are abandoned only
            # when the entry process itself is gone (`_entry_exit`).
            reason = str((message.get("data") or {}).get("reason")
                         or "transport-end")
            self._report_end(reason)
        # `process_release_unconfirmed` is the entry saying it could not prove
        # the OS stopped a process it owns: kept as evidence, never relayed,
        # and never rewritten into a claim that the release succeeded.
        # `stderr`/`transport_malformed` are the Agent's diagnostics on the
        # control plane - the ACP relay stays frame-only.

    def _entry_exit(self, code: int | None) -> None:
        # The inner reader already proved the entry process gone; anything it
        # was asked to release is now unrecoverable, so no waiter stays parked.
        self._abandon_control()
        self._report_end(code)

    def _report_end(self, code: Any) -> None:
        with self._end_lock:
            if self._end_reported:
                return
            self._end_reported = True
        try:
            self._on_exit(code)
        except Exception:  # noqa: BLE001 - the ledger owner must not be re-entered
            pass
        # The entry may still be running behind a dead Harness (that is the
        # normal crash shape); its release is this transport's to ask for, off
        # the reader thread so the entry's own answer can arrive.
        threading.Thread(target=self.terminate, daemon=True).start()
