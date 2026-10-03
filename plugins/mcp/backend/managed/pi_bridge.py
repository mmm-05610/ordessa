"""Q4 T10 Pi managed lane: the Server-side peer of the managed Pi bridge.

The Pi side (``adapters/pi/ordessa-mcp-bridge.ts``) is a *managed
extension*: executable code loaded by the fixed Pi CLI that may only
register tool bridges the Server has validated
(docs/design/mcp/harness-adapters.md「Managed lane」, contracts.md §3).
This module is the other half of that promise:

* a loopback control channel (TCP, bind pinned to ``127.0.0.1``) with a
  **one-shot binding token** handed to the extension through the
  environment of the Pi process - the same shape as the server-compat
  subagent bridge's ``AGENTBOX_BRIDGE_URL``/``AGENTBOX_BRIDGE_TOKEN``
  (composition.py order-65 precedent), independently implemented here;
* **registration-time validation against the live observation**: the tool
  descriptors an extension may register are frozen at bind time from the
  lease's approved subset plus the current ``McpToolCatalog`` observation
  (name set AND per-tool schema digests - a descriptor that does not match
  the observation is refused with ``MCP_VERIFICATION_MISMATCH``; the
  definition record alone is never a catalog, contracts.md §1);
* **call-time double gate**: every ``call`` frame first re-checks the
  frozen binding (unregistered tool -> ``MCP_TOOL_NOT_APPROVED``, catalog
  digest drift -> ``CATALOG_CHANGED`` - both with *zero* forwarding), then
  delegates to :meth:`ManagedSessionManager.call_tool`, which runs the
  canonical ``check_tool_callable`` double gate (catalog subset +
  PermissionAuthority) before the managed client is touched. The bridge
  adds no second permission model and forwards nothing around it;
* **no credentials ever flow this way**: the ``ready`` frame carries only
  non-secret tool descriptors (name/label/description/inputSchema).

Error codes stay inside the closed vocabulary of ``backend.errors`` (T014
converge): channel-gate refusals use ``PERMISSION_REFUSED``, binding
refusals the managed-connection family, a non-loopback listen address is
``MCP_TRANSPORT_UNSUPPORTED``.

Threading: one accept thread plus one reader thread per accepted
connection (daemon threads, joined-best-effort on close). Frames are
newline-delimited JSON with a hard size cap. All sockets are plain TCP on
loopback; nothing in this module can dial out - it only ever accepts.
"""
from __future__ import annotations

import hmac
import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from ..errors import (
    CATALOG_CHANGED,
    MCP_DEFINITION_INVALID,
    MCP_NOT_CONNECTED,
    MCP_TOOL_NOT_APPROVED,
    MCP_TRANSPORT_UNSUPPORTED,
    MCP_VERIFICATION_MISMATCH,
    PERMISSION_REFUSED,
    McpError,
)
from .catalog import tool_schema_digest
from .lease import LeaseCaller
from .session_manager import ManagedSessionManager

#: Control-channel protocol version this peer speaks (extension sends
#: ``proto`` in its hello; a mismatch is a gate refusal).
BRIDGE_PROTOCOL = 1

#: The only address this peer may bind and accept on.
LOOPBACK_HOST = "127.0.0.1"

#: Hard cap for one control-channel frame (mirrors the extension source).
MAX_FRAME_BYTES = 1024 * 1024

#: Env contract with the managed extension (adapters/pi/ordessa-mcp-bridge.ts).
#: Values live in one table: a bare ``NAME = "UPPER_SNAKE"`` module constant
#: is a *code registration* shape for the closed-vocabulary guard (T014) and
#: env keys are not codes - keep them out of that grammar.
_ENV_KEYS = {
    "host": "ORDESSA_PI_BRIDGE_HOST",
    "port": "ORDESSA_PI_BRIDGE_PORT",
    "token": "ORDESSA_PI_BRIDGE_TOKEN",
}
ENV_HOST = _ENV_KEYS["host"]
ENV_PORT = _ENV_KEYS["port"]
ENV_TOKEN = _ENV_KEYS["token"]


@dataclass(frozen=True)
class BridgeToolBinding:
    """One Server-validated tool descriptor exposed over the bridge."""
    name: str
    label: str
    description: str
    input_schema: Mapping[str, Any]

    def descriptor(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "inputSchema": dict(self.input_schema),
        }


@dataclass
class BridgeState:
    """Observable counters for tests and audit: nothing leaves the process
    that is not counted here (gate refusals must show *zero forwarding*)."""
    hellos_accepted: int = 0
    hellos_refused: int = 0
    refusal_reasons: list = field(default_factory=list)
    calls_forwarded: int = 0
    calls_refused: int = 0
    #: a live bound channel right now (cleared when the peer vanishes)
    bound: bool = False
    #: sticky: the one-shot token was spent; a dead channel never re-arms it
    token_consumed: bool = False
    closed: bool = False

    def snapshot(self) -> dict:
        return {
            "hellosAccepted": self.hellos_accepted,
            "hellosRefused": self.hellos_refused,
            "refusalReasons": list(self.refusal_reasons),
            "callsForwarded": self.calls_forwarded,
            "callsRefused": self.calls_refused,
            "bound": self.bound,
            "tokenConsumed": self.token_consumed,
            "closed": self.closed,
        }


class PiToolBridge:
    """The frozen, validated tool binding a bridge channel may serve.

    Built once per (lease, approved subset) pair. Binds each exposed
    descriptor to the *live observation* at construction: the name must be
    in the lease's approved subset AND the provided inputSchema must digest
    to the same ``tool_schema_digest`` the catalog recorded - the Server
    never hands the extension a tool it did not observe, and never lets a
    drifted definition sneak in under an old name.
    """

    def __init__(
        self, *, bridge_id: str, manager: ManagedSessionManager,
        caller: LeaseCaller, owner_id: str, lease_id: str,
        tools: Sequence[BridgeToolBinding],
    ) -> None:
        if not isinstance(tools, Sequence) or isinstance(tools, (str, bytes)) or not tools:
            raise McpError(
                MCP_DEFINITION_INVALID,
                "a bridge registration needs the non-empty Server-validated tool list",
            )
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
            raise McpError(
                MCP_DEFINITION_INVALID,
                "bridge tool names must be unique non-empty strings",
            )
        try:
            lease = manager.leases.get_lease(lease_id, caller)
        except McpError:
            raise  # visibility/missing refusals propagate unchanged
        manager.leases.require_owner(lease, owner_id)
        if lease.state != "catalog-observed":
            raise McpError(
                MCP_NOT_CONNECTED,
                f"the bridge only binds to a catalog-observed lease (state {lease.state!r})",
            )
        current = manager.catalogs.latest(
            definition_id=lease.definition_id, revision=lease.revision)
        if current is None:
            raise McpError(
                MCP_CATALOG_MISSING,
                "no live tools/list observation backs this lease; a stored "
                "definition is never presented to the extension as a catalog",
            )
        if lease.approved_catalog_digest != current.catalog_digest:
            raise McpError(
                CATALOG_CHANGED,
                "the observed catalog drifted before the bridge bound; the "
                "frozen approval is stale and re-approval is required",
            )
        observed = dict(current.tool_names_and_schema_digests)
        for tool in tools:
            if tool.name not in set(lease.approved_tool_names):
                raise McpError(
                    MCP_TOOL_NOT_APPROVED,
                    f"tool {tool.name!r} is outside the lease's approved subset; "
                    "the bridge may only register approved tools",
                )
            if tool.name not in observed:
                raise McpError(
                    MCP_TOOL_NOT_APPROVED,
                    f"tool {tool.name!r} is not in the approved subset",
                )
            if tool_schema_digest({"name": tool.name,
                                   "inputSchema": tool.input_schema}) != observed[tool.name]:
                raise McpError(
                    MCP_VERIFICATION_MISMATCH,
                    f"tool {tool.name!r} does not match the live observation "
                    "(schema digest differs); the Server-validated descriptor wins",
                )
        self.bridge_id = bridge_id
        self._manager = manager
        self._caller = caller
        self._owner_id = owner_id
        self._lease_id = lease_id
        self._definition_id = lease.definition_id
        self._revision = lease.revision
        self._catalog_digest = current.catalog_digest
        self.tools: Mapping[str, BridgeToolBinding] = {tool.name: tool for tool in tools}

    # -- frames ------------------------------------------------------------------

    def ready_frame(self) -> dict:
        return {
            "type": "ready",
            "proto": BRIDGE_PROTOCOL,
            "bridgeId": self.bridge_id,
            "catalogDigest": self._catalog_digest,
            "tools": [tool.descriptor() for tool in self._tools_ordered()],
        }

    def _tools_ordered(self):
        return [self.tools[name] for name in sorted(self.tools)]

    def handle_call(self, tool_name: Any, arguments: Any) -> dict:
        """One validated tools/call. Gate order is load-bearing: every
        refusal here happens *before* ``manager.call_tool`` is entered, so
        a refused frame can be proven to have forwarded zero work; the
        double gate (catalog subset + PermissionAuthority) then runs
        inside :meth:`ManagedSessionManager.call_tool`, unchanged.
        """
        if not isinstance(tool_name, str) or tool_name not in self.tools:
            raise McpError(
                MCP_TOOL_NOT_APPROVED,
                f"tool {tool_name!r} was never registered on this bridge; "
                "the extension may only call the Server-validated subset",
            )
        if not isinstance(arguments, Mapping):
            raise McpError(
                MCP_DEFINITION_INVALID, "call params must be a JSON object",
            )
        current = self._manager.catalogs.latest(
            definition_id=self._definition_id, revision=self._revision)
        if current is None:
            raise McpError(
                MCP_CATALOG_MISSING, "the live catalog observation is gone; "
                "the bridge refuses to serve from memory",
            )
        if current.catalog_digest != self._catalog_digest:
            raise McpError(
                CATALOG_CHANGED,
                "the observed catalog drifted after binding; every call is "
                "refused until a fresh registration re-binds the bridge",
            )
        return self._manager.call_tool(
            caller=self._caller, lease_id=self._lease_id, owner_id=self._owner_id,
            tool_name=tool_name, arguments=dict(arguments),
        )


class PiBridgeServer:
    """Loopback control-channel server hosting exactly one bound extension.

    Lifecycle: :meth:`start` binds ``127.0.0.1:0`` (OS-assigned port) and
    mints the one-shot token; the launcher puts ``extension_env()`` into
    the Pi process environment; the extension's hello consumes the token
    on first successful bind - a second hello (same token or not, even
    after the peer vanished) is refused forever, so a leaked token can
    never re-bind. :meth:`close` is idempotent: stop listening, drop the
    live connection, and every later frame or call is refused.
    """

    def __init__(self, bridge: PiToolBridge, *, host: str = LOOPBACK_HOST,
                 audit_sink: Optional[Any] = None) -> None:
        if host != LOOPBACK_HOST:
            # defence in depth: this peer structurally refuses to serve on
            # anything but loopback (a Pi bridge must never be reachable
            # off-machine).
            raise McpError(
                MCP_TRANSPORT_UNSUPPORTED,
                f"the Pi bridge only serves on {LOOPBACK_HOST}; {host!r} is refused",
            )
        self.bridge = bridge
        self.state = BridgeState()
        self._audit_sink = audit_sink
        self._token = secrets.token_hex(16)
        self._listen: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._conn_lock = threading.Lock()
        self._conns: set[socket.socket] = set()
        self._host = host
        self._port = 0

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> int:
        if self._listen is not None:
            raise McpError(MCP_DEFINITION_INVALID, "the bridge server is already started")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # polled accept: a blocking accept would pin the listen fd open past
        # close() (CPython defers the real fd release while an op is in
        # flight), so the port would not actually be released on close.
        listener.settimeout(0.25)
        try:
            listener.bind((self._host, 0))
        except OSError as exc:
            listener.close()
            raise McpError(MCP_TRANSPORT_UNSUPPORTED,
                           f"the loopback bind failed: {exc}") from exc
        listener.listen(8)
        self._listen = listener
        self._port = listener.getsockname()[1]
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name=f"pi-bridge-accept-{self.bridge.bridge_id}",
            daemon=True)
        self._accept_thread.start()
        return self._port

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    def extension_env(self) -> dict:
        """The env the launcher gives the Pi process (server-compat bridge
        token precedent, independent implementation): host is the literal
        loopback constant, port is the bound one, token is one-shot."""
        return {
            ENV_HOST: self._host,
            ENV_PORT: str(self._port),
            ENV_TOKEN: self._token,
        }

    def close(self) -> dict:
        """Idempotent teardown: no accept, no calls, sockets dropped."""
        if self.state.closed:
            return {"replayed": True, **self.state.snapshot()}
        self.state.closed = True
        self.state.bound = False
        listener, self._listen = self._listen, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._conn_lock:
            conns, self._conns = self._conns, set()
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        thread, self._accept_thread = self._accept_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._audit({"kind": "pi-bridge-closed", "bridgeId": self.bridge.bridge_id})
        return {"replayed": False, **self.state.snapshot()}

    # -- accept / connection loops ------------------------------------------------

    def _accept_loop(self) -> None:
        listener = self._listen
        assert listener is not None
        while not self.state.closed:
            try:
                conn, _peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return  # listener closed (normal teardown)
            if self.state.closed:
                try:
                    conn.close()
                except OSError:
                    pass
                return
            reader = threading.Thread(
                target=self._serve_conn, args=(conn,),
                name=f"pi-bridge-conn-{self.bridge.bridge_id}", daemon=True)
            with self._conn_lock:
                self._conns.add(conn)
            reader.start()

    def _serve_conn(self, conn: socket.socket) -> None:
        try:
            self._connection_loop(conn)
        except OSError:
            pass
        finally:
            with self._conn_lock:
                self._conns.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _connection_loop(self, conn: socket.socket) -> None:
        reader = _FrameReader(conn)
        hello = reader.read_frame()
        if hello is None or hello.get("type") != "hello":
            self._refuse(conn, reader, PERMISSION_REFUSED,
                         "the first control-channel frame must be a hello")
            return
        self._handshake(conn, reader, hello)

    def _handshake(self, conn: socket.socket, reader: "_FrameReader",
                   hello: Mapping[str, Any]) -> None:
        refused = self._check_hello(hello)
        if refused is not None:
            self._refuse(conn, reader, *refused)
            return
        with self._conn_lock:
            was_bound = self.state.bound
        if was_bound:  # race backstop; the one-shot check above already covers it
            self._refuse(conn, reader, PERMISSION_REFUSED,
                         "another live channel already holds this bridge")
            return
        self.state.hellos_accepted += 1
        self.state.bound = True
        self.state.token_consumed = True
        self._audit({"kind": "pi-bridge-bound", "bridgeId": self.bridge.bridge_id,
                     "pid": hello.get("pid")})
        _send_frame(conn, self.bridge.ready_frame())
        while not self.state.closed:
            frame = reader.read_frame()
            if frame is None:
                # peer EOF / transport error: the CHANNEL is done (the token
                # stays spent - a vanished peer never re-arms the binding).
                self.state.bound = False
                self._audit({"kind": "pi-bridge-channel-closed",
                             "bridgeId": self.bridge.bridge_id})
                return
            if frame.get("type") == "__malformed__":
                # malformed JSON is a gate event, not a retryable frame:
                # refuse the reason and drop the channel (fail closed).
                self.state.hellos_refused += 1
                self.state.refusal_reasons.append("malformed control-channel frame")
                self.state.bound = False
                self._audit({"kind": "pi-bridge-frame-refused",
                             "code": PERMISSION_REFUSED})
                return
            self._dispatch(conn, frame)

    def _check_hello(self, hello: Mapping[str, Any]) -> Optional[tuple[str, str]]:
        if hello.get("proto") != BRIDGE_PROTOCOL:
            return (PERMISSION_REFUSED, "unsupported control-channel protocol version")
        if self.state.closed:
            return (PERMISSION_REFUSED, "the bridge is closed; no new channel is accepted")
        if self.state.bound:
            return (PERMISSION_REFUSED,
                    "another live channel already holds this bridge")
        token = hello.get("token")
        if self.state.token_consumed:
            # one-shot binding: once a hello has EVER succeeded, no further
            # hello binds - not the same token, not after a disconnect.
            return (PERMISSION_REFUSED,
                    "the bridge token is already consumed (one-shot binding)")
        if not isinstance(token, str) or not token:
            return (PERMISSION_REFUSED, "hello carries no bridge token")
        if not hmac.compare_digest(token, self._token):
            return (PERMISSION_REFUSED, "hello token does not match the bound registration")
        return None

    def _dispatch(self, conn: socket.socket, frame: Mapping[str, Any]) -> None:
        kind = frame.get("type")
        if kind == "bye":
            return
        if kind != "call":
            self.state.calls_refused += 1
            _send_frame(conn, {
                "type": "result", "id": frame.get("id"), "ok": False,
                "code": PERMISSION_REFUSED,
                "reason": f"unsupported control-channel frame type {kind!r}",
            })
            return
        call_id = frame.get("id")
        try:
            outcome = self.bridge.handle_call(frame.get("tool"), frame.get("params"))
        except McpError as exc:
            self.state.calls_refused += 1
            self._audit({"kind": "pi-bridge-call-refused", "code": exc.code,
                         "tool": frame.get("tool")})
            _send_frame(conn, {"type": "result", "id": call_id, "ok": False,
                               "code": exc.code, "reason": str(exc)})
            return
        except BaseException as exc:  # never forward a crash to the channel
            self.state.calls_refused += 1
            _send_frame(conn, {"type": "result", "id": call_id, "ok": False,
                               "code": PERMISSION_REFUSED,
                               "reason": f"internal bridge error: {type(exc).__name__}"})
            return
        self.state.calls_forwarded += 1
        _send_frame(conn, {"type": "result", "id": call_id, "ok": True,
                           "result": outcome})

    def _refuse(self, conn: socket.socket, reader: "_FrameReader",
                code: str, reason: str) -> None:
        self.state.hellos_refused += 1
        self.state.refusal_reasons.append(reason)
        self._audit({"kind": "pi-bridge-hello-refused", "code": code, "reason": reason})
        try:
            _send_frame(conn, {"type": "error", "code": code, "reason": reason})
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def _audit(self, event: Mapping[str, Any]) -> None:
        if self._audit_sink is not None:
            self._audit_sink.write(event)

    # -- test/probe helpers ---------------------------------------------------------

    def wait_for_bound(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state.bound or self.state.closed:
                break
            time.sleep(0.01)
        return self.state.bound


#: refusals raised at the channel gate (before any domain object is touched)
#: use PERMISSION_REFUSED from backend.errors (closed vocabulary).


class _FrameReader:
    """Newline-delimited JSON reader with a hard size cap (fail closed)."""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn
        self._buf = b""

    def read_frame(self) -> Optional[dict]:
        while True:
            newline = self._buf.find(b"\n")
            if newline >= 0:
                line, self._buf = self._buf[:newline], self._buf[newline + 1:]
                line = line.strip(b"\r")
                if not line:
                    continue
                return self._parse(line)
            try:
                chunk = self._conn.recv(65536)
            except OSError:
                return None
            if not chunk:
                return None
            self._buf += chunk
            if len(self._buf) > MAX_FRAME_BYTES:
                return None  # oversized frame: drop the channel, never parse it

    def _parse(self, line: bytes) -> Optional[dict]:
        try:
            frame = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"type": "__malformed__"}
        if not isinstance(frame, dict):
            return {"type": "__malformed__"}
        return frame


def _send_frame(conn: socket.socket, frame: Mapping[str, Any]) -> None:
    payload = json.dumps(dict(frame), separators=(",", ":"), ensure_ascii=False)
    conn.sendall(payload.encode("utf-8") + b"\n")


def bind_bridge(
    *, manager: ManagedSessionManager, caller: LeaseCaller, owner_id: str,
    lease_id: str, tools: Sequence[Mapping[str, Any]], bridge_id: Optional[str] = None,
    audit_sink: Optional[Any] = None, start: bool = True,
) -> PiBridgeServer:
    """Convenience: validate + freeze the tool descriptors into a
    :class:`PiToolBridge`, wrap it in a :class:`PiBridgeServer` and (by
    default) start it. ``tools`` entries are
    ``{"name", "label"?, "description"?, "inputSchema"?}`` - the caller
    (service wiring / probe) supplies the Server-side descriptors; every
    one is digest-checked against the live catalog observation before a
    single frame can flow.
    """
    bindings = []
    for tool in tools:
        if not isinstance(tool, Mapping) or not tool.get("name"):
            raise McpError(MCP_DEFINITION_INVALID, "bridge tools need names")
        bindings.append(BridgeToolBinding(
            name=str(tool["name"]),
            label=str(tool.get("label") or tool["name"]),
            description=str(tool.get("description") or ""),
            input_schema=dict(tool.get("inputSchema") or {"type": "object",
                                                          "properties": {}}),
        ))
    server = PiBridgeServer(
        PiToolBridge(
            bridge_id=bridge_id or f"pib-{secrets.token_hex(6)}",
            manager=manager, caller=caller, owner_id=owner_id,
            lease_id=lease_id, tools=bindings,
        ),
        audit_sink=audit_sink,
    )
    if start:
        server.start()
    return server
