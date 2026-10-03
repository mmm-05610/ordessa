"""Q4 T05 managed client (**L2**, limited substitute): a minimal stdio MCP client.

**Route ruling (registered with C0, integration-request item 10).** The
first-choice route was the in-tree pinned TypeScript SDK
``@modelcontextprotocol/sdk`` 1.29.0, but the probe shows it is **not in the
root package-lock closure**: ``grep -c -i modelcontextprotocol package-lock.json``
is ``0``, ``require.resolve`` from the worktree root fails with
``MODULE_NOT_FOUND`` and there is no root ``node_modules``. The only pin is
``plugins/harness/packaging/pi/package-lock.json`` - a harness artefact whose
lock face belongs to C0 (AGENTS.md: no new dependency versions here). Per
``docs/design/mcp/research-and-reuse.md`` ("若与 ACP/Python 进程边界不符…
记录限定替代，禁止临时写全协议") this module is therefore the **explicit
limited substitute**: the smallest stdio JSON-RPC client subset -
``initialize`` negotiation, ``tools/list``, ``tools/call``, close/cancel -
and **nothing else**. It deliberately does not implement resources,
sampling, elicitation, completions or tasks, and must not grow into a full
protocol stack; that growth is C0's ruling to make (official Python ``mcp``
SDK vs reusing the harness-pinned TS SDK over a subprocess seam).

Scope honesty (evidence ladder): what is proven here is a brand-neutral SDK
client layer driving a **controlled fake MCP server** (loopback stdio, L2).
The Pi格 (Pi extension loading through the harness API) is NOT proven by
this file and still waits for the harness-api batch (G4); nothing in this
module may be cited as Pi L3 evidence.

Design notes:

* one client instance per managed lease, created fresh by the injected
  ``ClientFactory`` - there is no pooling path (data-model「首版默认不池化」);
* the client implements ``ManagedClientPort``
  (:mod:`backend.managed.session_manager`) and adds nothing to the gates:
  lease-state, catalog/approval and the Permission authority stay in the
  manager, which alone owns the side-effect door;
* framing is line-delimited JSON-RPC over the child's stdin/stdout, the
  same discipline as the T03 probe (``start_new_session`` + killpg
  SIGTERM->grace->SIGKILL whole-group reaping, bounded timeouts, credential
  never ambient: the child env is the fixed allowlist plus explicitly
  resolved values);
* failure taxonomy is load-bearing against the lease state machine:
  local precondition refusals (not started / not connected / closed) raise
  a typed ``McpError`` **before any frame is written** - the manager keeps
  the lease and books nothing unknown; anything that fails **after** a
  frame was written raises :class:`ClientRequestUnconfirmed` (a plain
  ``RuntimeError``, deliberately NOT an ``McpError``) so
  ``ManagedSessionManager`` maps it to ``UNKNOWN_OUTCOME`` + a
  ``call-outcome-unknown`` fact instead of pretending the outcome is known;
* ``close()`` is idempotent, joins the reader thread and reaps the process
  group; a process that survives SIGKILL+wait raises - the manager books
  that as ``cleanup-error`` and parks the lease in ``unknown``.

Secrets: values of a definition's stdio ``env`` reach the child through
``secret_resolver`` only (``SecretRef -> str`` at spawn time, the T07
credential port). With no resolver injected a declared ``secretRef`` is a
typed ``SECRET_UNRESOLVED`` refusal - fail closed, never an ambient read,
never a logged value.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from ..definition import Literal, McpRevision, SecretRef, StdioTransport
from ..errors import (
    CONNECTION_FAILED,
    MCP_CLIENT_CLEANUP_FAILED,
    MCP_CLIENT_CLOSED,
    MCP_CLIENT_NOT_CONNECTED,
    MCP_CLIENT_NOT_STARTED,
    MCP_CLIENT_RESPONSE_INVALID,
    MCP_CLIENT_SPAWN_FAILED,
    MCP_DEFINITION_INVALID,
    MCP_TRANSPORT_UNSUPPORTED,
    PROTOCOL_MISMATCH,
    SECRET_UNRESOLVED,
    McpError,
)
from ..probe_policy import BASE_ENVIRONMENT
from .lease import McpConnectionLease

# T014 converge: the stdio-client family is registered in backend/errors.py;
# this module keeps re-exporting the names (reported in t05-client.md).

#: The client capability list, newest first (negotiation baseline 2025-11-25,
#: same as docs/design/mcp/research-and-reuse.md; nothing auto-upgrades).
SUPPORTED_PROTOCOL_VERSIONS: Tuple[str, ...] = ("2025-11-25", "2024-11-05")


class ClientRequestUnconfirmed(RuntimeError):
    """A failure that happened AFTER a frame was written to the server.

    Not an ``McpError`` on purpose: the manager's call path must map it to
    ``UNKNOWN_OUTCOME`` (FR-10) - the server may or may not have executed
    the request, and no automatic retry may bet either way.
    """


@dataclass(frozen=True)
class StdioClientPolicy:
    """Bounds for one managed stdio client (probe policy in spirit, wider
    because a managed connection serves repeated requests, not one probe)."""

    request_timeout: float = 5.0
    initialize_timeout: float = 5.0
    kill_grace: float = 1.0
    exit_grace: float = 1.0
    max_line_bytes: int = 256 * 1024
    supported_protocol_versions: Tuple[str, ...] = SUPPORTED_PROTOCOL_VERSIONS
    client_name: str = "ordessa-mcp-managed-client"
    client_version: str = "t05-limited-substitute"

    def __post_init__(self) -> None:
        if self.request_timeout <= 0 or self.initialize_timeout <= 0:
            raise ValueError("client policy timeouts must be positive")
        if (not isinstance(self.supported_protocol_versions, tuple)
                or not self.supported_protocol_versions
                or any(not isinstance(v, str) or not v
                       for v in self.supported_protocol_versions)):
            raise ValueError("client policy needs a non-empty version tuple")


DEFAULT_STDIO_CLIENT_POLICY = StdioClientPolicy()


class StdioManagedClient:
    """One owned stdio MCP child process + line-framed JSON-RPC (limited subset).

    Lifecycle mirrors ``ManagedClientPort``: ``start`` spawns the owned
    process, ``connect`` runs the initialize negotiation (the ACTUAL
    negotiated ``protocolVersion`` is recorded, never assumed), ``list_tools``
    and ``call_tool`` run the two read/write requests, ``close`` is
    idempotent and reaps the whole process group. Instances share no state;
    two clients for one URL are two worlds (no pooling).
    """

    def __init__(
        self, *, argv: Sequence[str], env: Mapping[str, str],
        policy: Optional[StdioClientPolicy] = None,
    ) -> None:
        if (not argv or not isinstance(argv[0], str) or not argv[0].startswith("/")):
            raise McpError(
                MCP_DEFINITION_INVALID, "the stdio command must be an absolute path")
        if any(not isinstance(item, str) or "\x00" in item for item in argv):
            raise McpError(MCP_DEFINITION_INVALID, "argv entries must be plain strings")
        self._argv = [str(item) for item in argv]
        self._env = {str(k): str(v) for k, v in env.items()}
        self._policy = policy or DEFAULT_STDIO_CLIENT_POLICY
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict = {}
        self._started = False
        self._connected = False
        self._closed = False
        self._transport_down = threading.Event()
        self.negotiated_protocol_version: Optional[str] = None
        self.server_info: Optional[Mapping[str, Any]] = None
        self._next_id = 0

    # -- port properties -----------------------------------------------------------

    @property
    def child_pid(self) -> Optional[int]:
        process = self._process
        return process.pid if process is not None else None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def closed(self) -> bool:
        return self._closed

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the owned server process in its own session (process group).

        A spawn failure is a confirmed refusal (typed ``McpError``): nothing
        is running, so the manager books ``refused``, never ``unknown``.
        """
        if self._started:
            raise McpError(CONNECTION_FAILED, "the client transport was already started")
        if self._closed:
            raise McpError(MCP_CLIENT_CLOSED, "a closed client cannot be restarted")
        try:
            process = subprocess.Popen(  # noqa: S603 - the command is the stored revision
                self._argv,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env, start_new_session=True,
            )
        except OSError as exc:
            raise McpError(
                MCP_CLIENT_SPAWN_FAILED, f"the server process did not start: {exc}") from exc
        self._process = process
        self._started = True
        self._reader = threading.Thread(
            target=self._read_loop, name=f"mcp-client-reader-{process.pid}", daemon=True)
        self._reader.start()

    def connect(self) -> Mapping[str, Any]:
        """``initialize`` negotiation; records the ACTUAL protocolVersion.

        The negotiated version is read off the server's own answer and must
        be in the client's supported list - ``2024-11-05`` from a
        downgrading server is recorded as ``2024-11-05``, and an
        unanswerable version (``1999-01-01``) is a typed
        ``PROTOCOL_MISMATCH`` after the owned process has been reaped, so a
        failed connect can never leave a live child behind.
        """
        self._require_started()
        if self._closed:
            raise McpError(MCP_CLIENT_CLOSED, "the client is closed")
        request = {
            "jsonrpc": "2.0",
            "id": self._new_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": self._policy.supported_protocol_versions[0],
                "capabilities": {},
                "clientInfo": {"name": self._policy.client_name,
                               "version": self._policy.client_version},
            },
        }
        try:
            answer = self._request(request, timeout=self._policy.initialize_timeout)
        except ClientRequestUnconfirmed:
            # the handshake frame was written; the child exists. Reap it
            # first so the (manager-parked) unknown lease has no live leak.
            self.close()
            raise
        if "error" in answer:
            # the server refused the offered protocol version outright (the
            # controlled fake does exactly this for an un-negotiated offer).
            self.close()
            error = answer["error"]
            message = error.get("message") if isinstance(error, Mapping) else error
            raise McpError(
                PROTOCOL_MISMATCH,
                f"the server refused the initialize offer: {message} - the "
                "connection is torn down, nothing stays live")
        result = answer.get("result")
        if not isinstance(result, Mapping):
            self.close()
            raise McpError(
                MCP_CLIENT_RESPONSE_INVALID, "the initialize answer carries no result object")
        negotiated = result.get("protocolVersion")
        if (not isinstance(negotiated, str)
                or negotiated not in self._policy.supported_protocol_versions):
            self.close()
            raise McpError(
                PROTOCOL_MISMATCH,
                f"the server negotiated {negotiated!r}, outside the client's "
                "supported list - the connection is torn down, nothing stays live")
        info = result.get("serverInfo")
        self.negotiated_protocol_version = negotiated
        self.server_info = info if isinstance(info, Mapping) else {}
        self._connected = True
        # the initialized notification completes the handshake; a failure
        # here is still unconfirmed-but-owned: tear the client down.
        try:
            self._notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except ClientRequestUnconfirmed:
            self.close()
            raise
        return {"protocolVersion": negotiated, "serverInfo": dict(self.server_info)}

    # -- requests ---------------------------------------------------------------------

    def list_tools(self) -> Mapping[str, Any]:
        """``tools/list`` over the negotiated connection.

        Refused locally (typed McpError, zero frames written) unless the
        handshake completed - an un-negotiated version never reaches the
        wire. A server that answers with a JSON-RPC error (the controlled
        fake refuses un-negotiated use) surfaces as
        ``ClientRequestUnconfirmed`` -> the manager books ``unknown``.
        """
        self._require_live("tools/list")
        answer = self._request(
            {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/list",
             "params": {}}, timeout=self._policy.request_timeout)
        result = answer.get("result")
        if not isinstance(result, Mapping) or not isinstance(result.get("tools"), list):
            raise ClientRequestUnconfirmed(
                "the tools/list answer carries no tools array")
        return {"tools": list(result["tools"])}

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """``tools/call`` - the only path with server-side effects.

        Every gate (lease state, catalog/approval subset, Permission
        authority) runs in the manager BEFORE this method is entered; this
        client adds no gate of its own and is never a side door.
        """
        self._require_live("tools/call")
        answer = self._request(
            {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/call",
             "params": {"name": name, "arguments": dict(arguments)}},
            timeout=self._policy.request_timeout)
        if "error" in answer:
            # a tool-level error may still have executed - unconfirmed, and
            # the manager books call-outcome-unknown.
            error = answer["error"]
            message = error.get("message") if isinstance(error, Mapping) else error
            raise ClientRequestUnconfirmed(
                f"the server answered tools/call with an error: {message}")
        result = answer.get("result")
        return dict(result) if isinstance(result, Mapping) else {"value": result}

    # -- close --------------------------------------------------------------------------

    def close(self) -> None:
        """Idempotent teardown: stop accepting, shut stdin, reap the group.

        ``start_new_session=True`` put grandchildren in the same process
        group, so one ``killpg`` reaches the whole tree; SIGTERM, bounded
        grace, SIGKILL, and the leader is always waited for (no zombie).
        A process that survives all of that raises - the manager books a
        ``cleanup-error`` and parks the lease in ``unknown``.
        """
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._connected = False
            process = self._process
        if process is None:
            return
        try:
            try:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
            except OSError:
                pass
            # cooperative exit first (the fake server ends on stdin EOF),
            # then the bounded SIGTERM -> SIGKILL escalation.
            try:
                process.wait(timeout=self._policy.exit_grace)
            except subprocess.TimeoutExpired:
                pass
            # the session leader may exit cooperatively while grandchildren
            # stay in the group: the escalation therefore runs regardless
            # of the leader's state (start_new_session made the leader its
            # own group, so pgid == pid even after it has been reaped).
            pgid = process.pid
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(pgid, sig)
                except ProcessLookupError:
                    break  # the whole group is already gone
                try:
                    process.wait(timeout=self._policy.kill_grace)
                except subprocess.TimeoutExpired:
                    continue
                try:
                    os.killpg(pgid, 0)  # group existence probe
                except ProcessLookupError:
                    break
        except OSError as exc:
            raise McpError(
                MCP_CLIENT_CLEANUP_FAILED,
                f"the owned process group did not reap cleanly: {exc}") from exc
        finally:
            self._transport_down.set()
            self._wake_pending(ClientRequestUnconfirmed(
                "the client closed while requests were in flight"))
            for stream in (process.stdout, ):
                try:
                    if stream is not None and not stream.closed:
                        stream.close()
                except OSError:
                    pass
        if process.poll() is None:  # reaped escalation failed silently
            raise McpError(
                MCP_CLIENT_CLEANUP_FAILED, "the owned process is still alive after SIGKILL")
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=2.0)

    # -- plumbing -------------------------------------------------------------------------

    def _require_started(self) -> None:
        if not self._started:
            raise McpError(
                MCP_CLIENT_NOT_STARTED, "start() must bring the transport up first")

    def _require_live(self, operation: str) -> None:
        self._require_started()
        if self._closed:
            raise McpError(MCP_CLIENT_CLOSED, f"{operation} on a closed client")
        if not self._connected:
            raise McpError(
                MCP_CLIENT_NOT_CONNECTED,
                f"{operation} requires a completed initialize negotiation")

    def _new_id(self) -> int:
        with self._state_lock:
            self._next_id += 1
            return self._next_id

    def _request(self, frame: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        request_id = frame.get("id")
        slot = threading.Event()
        holder: list = []
        with self._state_lock:
            if self._transport_down.is_set():
                raise ClientRequestUnconfirmed("the server transport is down")
            self._pending[request_id] = (slot, holder)
        try:
            self._write(frame)
        except BaseException:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        if not slot.wait(timeout):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise ClientRequestUnconfirmed(
                f"no answer to {frame.get('method')!r} within {timeout}s; "
                "the server-side outcome is unconfirmed")
        with self._state_lock:
            self._pending.pop(request_id, None)
        if not holder:
            raise ClientRequestUnconfirmed(
                f"the transport closed while {frame.get('method')!r} was in flight")
        answer = holder[0]
        if isinstance(answer, BaseException):
            raise answer
        if not isinstance(answer, Mapping):
            raise ClientRequestUnconfirmed("the server answered with a non-object frame")
        return answer

    def _notify(self, frame: Mapping[str, Any]) -> None:
        self._write(frame)

    def _write(self, frame: Mapping[str, Any]) -> None:
        process = self._process
        assert process is not None and process.stdin is not None
        payload = (json.dumps(frame, sort_keys=True) + "\n").encode("utf-8")
        with self._write_lock:
            if self._transport_down.is_set() or process.poll() is not None:
                raise ClientRequestUnconfirmed("the server process is not accepting frames")
            try:
                process.stdin.write(payload)
                process.stdin.flush()
            except (BrokenPipeError, ValueError, OSError) as exc:
                raise ClientRequestUnconfirmed(
                    f"the frame could not be written: {exc}") from exc

    def _read_loop(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        stream = process.stdout
        try:
            while True:
                line = stream.readline(self._policy.max_line_bytes + 1)
                if not line:
                    break  # EOF: server exited or closed stdout
                if len(line) > self._policy.max_line_bytes:
                    self._fail_line(
                        "the server answered with an over-bound line")
                    return
                try:
                    frame = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._fail_line("the server answered with a non-JSON line")
                    return
                if not isinstance(frame, Mapping):
                    continue
                request_id = frame.get("id")
                if request_id is None:
                    continue  # server-to-client notification: not answered here
                with self._state_lock:
                    waiter = self._pending.get(request_id)
                if waiter is not None:
                    slot, holder = waiter
                    holder.append(frame)
                    slot.set()
        except (OSError, ValueError):
            pass
        finally:
            self._transport_down.set()
            self._wake_pending(None)

    def _fail_line(self, reason: str) -> None:
        self._transport_down.set()
        self._wake_pending(ClientRequestUnconfirmed(reason))

    def _wake_pending(self, payload: Any) -> None:
        with self._state_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for slot, holder in waiters:
            if payload is not None:
                holder.append(payload)
            slot.set()


# -- the lease -> client factory (one fresh instance per lease, no pooling) --------

SecretResolver = Callable[[str], str]


def stdio_environment(
    transport: StdioTransport, *, secret_resolver: Optional[SecretResolver] = None,
) -> dict:
    """Child env for one stdio revision: allowlist + literals + resolved refs.

    Fail closed: a ``SecretRef`` without an injected resolver is
    ``SECRET_UNRESOLVED`` (the G7 convention - the manager lane may run
    with credentials, but only through the T07 credential port, never from
    the ambient environment, and no value is ever returned in an error).
    """
    environment = dict(BASE_ENVIRONMENT)
    for key, value in transport.env.items():
        if isinstance(value, Literal):
            environment[str(key)] = value.value
        elif isinstance(value, SecretRef):
            if secret_resolver is None:
                raise McpError(
                    SECRET_UNRESOLVED,
                    f"the managed stdio launch declares credential "
                    f"{key!r} as a SecretRef but no credential resolver is "
                    "wired; refusing to start unresolvable or ambient")
            environment[str(key)] = secret_resolver(value.credential_id)
        else:  # pragma: no cover - the revision model has exactly two values
            raise McpError(MCP_TRANSPORT_UNSUPPORTED, "the env value shape is unknown")
    return environment


def make_stdio_client_factory(
    definitions: Any, *, policy: Optional[StdioClientPolicy] = None,
    secret_resolver: Optional[SecretResolver] = None,
) -> Callable[[McpConnectionLease], StdioManagedClient]:
    """A ``ClientFactory`` producing one fresh :class:`StdioManagedClient`
    per lease, driven entirely by the stored revision.

    The factory is asked exactly once per lease by the manager (no pooling,
    no sharing between sessions - two leases on the same command spawn two
    processes). Remote transports are a typed refusal here: this limited
    substitute is the stdio subset only; the Streamable-HTTP managed client
    is open work registered in t05-client.md.
    """
    def factory(lease: McpConnectionLease) -> StdioManagedClient:
        model: McpRevision = definitions.read_revision(
            server_scope=lease.server_scope,
            definition_id=lease.definition_id, revision=lease.revision)
        transport = model.transport
        if not isinstance(transport, StdioTransport):
            raise McpError(
                MCP_TRANSPORT_UNSUPPORTED,
                "the managed client limited substitute covers stdio only; a "
                "remote transport lease needs the C0-ruled SDK route")
        env = stdio_environment(transport, secret_resolver=secret_resolver)
        return StdioManagedClient(
            argv=[transport.executable_ref, *transport.argv], env=env, policy=policy)
    return factory
