"""Q4 T011 managed lane (**L2**, limited substitute): Streamable-HTTP client.

Sibling of :mod:`backend.managed.client_stdio` on the same route ruling
(integration-request item 10): the pinned TS SDK 1.29.0 is not in the root
lock closure, so this module is the explicit **limited substitute** - the
smallest Streamable-HTTP JSON-RPC subset (``initialize`` negotiation,
``tools/list``, ``tools/call``, close/cancel) over stdlib ``http.client``,
and nothing else. No resources, sampling, elicitation, completions, tasks,
no server-initiated SSE GET streams; growing this into a full protocol
stack stays C0's ruling.

Semantics deliberately mirror the stdio client (single taxonomy):

* one client instance == one local HTTP session, created fresh per lease by
  :func:`make_http_client_factory` - there is **no pooling path** (data-model
  「首版默认不池化」, verification.md counterexample 3: two sessions on one
  URL are two independent worlds, verified server-side);
* a server-issued session id (``Mcp-Session-Id``) is stored on THIS instance
  only, echoed on this instance's later requests, and dropped on close;
* failure taxonomy against the lease state machine: local precondition and
  security-policy refusals raise a typed ``McpError`` **before a single
  request body is written** (the manager books ``refused`` and nothing ever
  lived); anything that fails **after** the frame was written raises
  :class:`~backend.managed.client_stdio.ClientRequestUnconfirmed` (not an
  ``McpError``) so ``ManagedSessionManager`` maps it to ``UNKNOWN_OUTCOME``
  + ``call-outcome-unknown`` and reconcile is required before any retry
  (FR-10);
* ``close()`` tears down ONLY the local connection/session and is
  idempotent; the remote Streamable-HTTP service is not this plugin's
  process to stop (harness-adapters.md「Managed lane」"远端服务不归本插件
  停机"), which the client states honestly in its close fact as
  ``remoteServiceLifecycle: "not-owned"``.

Security policy (explicit, default strictest, :class:`HttpClientPolicy`):

* https required; plain http accepted ONLY to the **exact** host
  ``127.0.0.1`` (the storage rule matches a prefix, so a host like
  ``127.0.0.1.evil.test`` would slip past it - this client repeats the
  probe's exact-host check before touching the network, probe.py:249);
* TLS peer verification is ALWAYS on (default context or the configured
  ``ca_bundle`` file as its trust anchor; there is no opt-out);
* redirects are NEVER followed: any 3xx is a typed refusal (302 from a
  hostile/compromised endpoint must not move the session or the auth
  header);
* an origin-consistency guard re-asserts on every request that the
  connection target still equals the configured URL's authority;
* response bytes are bounded and every socket op runs under a wall-clock
  deadline;
* the ``protocolVersion`` the server ACTUALLY negotiated is recorded;
  anything outside the supported list is ``PROTOCOL_MISMATCH``.

Authorization (FR-05/FR-08, verification.md counterexample 8): declared
``SecretRef`` headers are resolved through the T07 port
(:func:`backend.secret.resolve_for_launch` over a frozen :class:`LaunchPlan`
+ :class:`CredentialPort`) at the instant a request is built - the plaintext
exists only in the local header dict handed to ``http.client`` and is never
stored on the instance, never returned, never logged; a refused
resolution (missing plan, missing slot binding, revoked/rotated/stale
credential) aborts BEFORE anything is written. A declared secret slot with
no resolver wired is ``SECRET_UNRESOLVED`` fail-closed, exactly the stdio
rule. ``close()`` drops the plan/port references so a closed client can
never resolve material again.

What this file is NOT: it has never talked to a real product MCP server
(every L2 claim here runs against the controlled loopback fake in
``tests/managed_http``); the Pi格 still waits for the harness-api batch (G4)
and nothing here may be cited as Pi L3 evidence.
"""
from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from ..definition import Literal, McpRevision, RemoteTransport, SecretRef
from ..errors import (
    AUTH_REQUIRED,
    CONNECTION_FAILED,
    MCP_HTTP_HOST_ORIGIN_MISMATCH,
    MCP_HTTP_REDIRECT_REFUSED,
    MCP_HTTP_REQUEST_REFUSED,
    MCP_HTTP_TRANSPORT_DOWN,
    MCP_HTTP_URL_NOT_ALLOWED,
    MCP_TRANSPORT_UNSUPPORTED,
    PROTOCOL_MISMATCH,
    SECRET_UNRESOLVED,
    McpError,
)
from ..secret import CredentialPort, LaunchPlan, resolve_for_launch
from .client_stdio import (
    ClientRequestUnconfirmed,
    MCP_CLIENT_CLOSED,
    MCP_CLIENT_NOT_CONNECTED,
    MCP_CLIENT_NOT_STARTED,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from .lease import McpConnectionLease

# T014 converge: the HTTP-client family is registered in backend/errors.py;
# this module keeps re-exporting the names (reported in t011-http-client.md).

#: harness-adapters.md「Managed lane」: the remote service is not ours to stop.
REMOTE_SERVICE_LIFECYCLE = "not-owned"


@dataclass(frozen=True)
class HttpClientPolicy:
    """Bounds for one managed Streamable-HTTP client (default = strictest).

    ``ca_bundle`` is a path handed to ``ssl.create_default_context(cafile=)``
    as the trust anchor for a private deployment (tests inject a throwaway
    loopback CA this way); with ``None`` the system trust store verifies.
    There is no field that turns verification, the redirect refusal, the
    byte bound or the deadline off.
    """

    request_timeout: float = 5.0
    initialize_timeout: float = 5.0
    connect_timeout: float = 5.0
    max_response_bytes: int = 64 * 1024
    allow_loopback_http: bool = True
    ca_bundle: Optional[str] = None
    supported_protocol_versions: Tuple[str, ...] = SUPPORTED_PROTOCOL_VERSIONS
    client_name: str = "ordessa-mcp-managed-client"
    client_version: str = "t011-limited-substitute"

    def __post_init__(self) -> None:
        for name in ("request_timeout", "initialize_timeout", "connect_timeout"):
            if not isinstance(getattr(self, name), (int, float)) or getattr(self, name) <= 0:
                raise ValueError(f"client policy {name} must be positive")
        if not isinstance(self.max_response_bytes, int) or self.max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be an int >= 1024")
        if (not isinstance(self.supported_protocol_versions, tuple)
                or not self.supported_protocol_versions
                or any(not isinstance(v, str) or not v
                       for v in self.supported_protocol_versions)):
            raise ValueError("client policy needs a non-empty version tuple")
        if self.ca_bundle is not None and not isinstance(self.ca_bundle, str):
            raise ValueError("ca_bundle must be a path string or None")


DEFAULT_HTTP_CLIENT_POLICY = HttpClientPolicy()


def evaluate_remote_url(
    url: str, policy: HttpClientPolicy = DEFAULT_HTTP_CLIENT_POLICY,
) -> Tuple[str, str, int, str]:
    """(scheme, host, port, path) of an allowed endpoint, or a typed refusal.

    The fail-closed core of the security policy: https only, or plain http
    to the EXACT host ``127.0.0.1`` - never the storage-side prefix match,
    so ``http://127.0.0.1.evil.test`` (which passes ``startswith`` there)
    is refused here before any socket exists (probe.py's exact-host ruling).
    """
    if not isinstance(url, str) or not url or "\x00" in url:
        raise McpError(MCP_HTTP_URL_NOT_ALLOWED, "a remote client needs a plain url")
    target = urlsplit(url)
    if target.hostname is None:
        raise McpError(MCP_HTTP_URL_NOT_ALLOWED, "the remote url names no host")
    scheme = target.scheme.lower()
    if scheme == "https":
        port = target.port or 443
    elif (scheme == "http" and policy.allow_loopback_http
            and target.hostname == "127.0.0.1"):
        port = target.port or 80
    else:
        raise McpError(
            MCP_HTTP_URL_NOT_ALLOWED,
            "the managed http client is https-only (plain http is allowed "
            "only to the exact loopback host 127.0.0.1)")
    path = target.path or "/"
    if target.query:
        path = f"{path}?{target.query}"
    return scheme, target.hostname, port, path


class HttpManagedClient:
    """One local Streamable-HTTP session speaking the MCP JSON-RPC subset.

    Lifecycle mirrors ``ManagedClientPort``: ``start`` opens (and TLS-
    verifies) the owned connection without sending anything, ``connect``
    runs the initialize negotiation over it and records the ACTUAL
    negotiated protocolVersion plus the server-issued session id (instance
    only), ``list_tools``/``call_tool`` ride the same connection, ``close``
    is idempotent, drops all credential-material references and stops
    nothing beyond the local side. Instances share no state and no
    connection: two clients for one URL are two worlds (no pooling).
    """

    def __init__(
        self, *, url: str, headers: Optional[Mapping[str, Any]] = None,
        launch_plan: Optional[LaunchPlan] = None,
        credential_port: Optional[CredentialPort] = None,
        binding_scope: Optional[Tuple[str, int]] = None,
        policy: Optional[HttpClientPolicy] = None,
    ) -> None:
        self._policy = policy or DEFAULT_HTTP_CLIENT_POLICY
        self._scheme, self._host, self._port, self._path = evaluate_remote_url(
            url, self._policy)
        self._url = url
        # header SPECS only (Literal values / SecretRef ids); plaintext is
        # never a field of this object, in any state, ever.
        self._headers: Mapping[str, Any] = dict(headers or {})
        secret_slots = [name for name, value in self._headers.items()
                        if isinstance(value, SecretRef)]
        if secret_slots and (launch_plan is None or credential_port is None):
            # fail closed at construction, before any state exists:
            # the G7 convention - a declared SecretRef without the T07
            # credential port wired is a refusal, never an ambient read.
            raise McpError(
                SECRET_UNRESOLVED,
                "the managed http client declares credential header(s) "
                f"{sorted(secret_slots)} as SecretRef but no LaunchPlan/"
                "CredentialPort pair is wired; refusing to start")
        self._launch_plan = launch_plan
        self._credential_port = credential_port
        self._binding_scope = binding_scope
        self._connection: Optional[HTTPConnection] = None
        self._state_lock = threading.Lock()
        self._started = False
        self._connected = False
        self._closed = False
        self._transport_down = False
        self.negotiated_protocol_version: Optional[str] = None
        self.server_info: Optional[Mapping[str, Any]] = None
        #: server-issued session id: THIS instance only, dropped on close.
        self.session_id: Optional[str] = None
        self._next_id = 0
        self.close_fact: Optional[Mapping[str, Any]] = None

    # -- port properties -----------------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def remote_service_lifecycle(self) -> str:
        """Always ``not-owned``: this client never stops the remote service."""
        return REMOTE_SERVICE_LIFECYCLE

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        """Open the owned local connection (TLS-verified, nothing sent).

        A connect or handshake failure is a confirmed refusal (typed
        ``McpError``): no MCP frame ever left, so the manager books
        ``refused``, never ``unknown``.
        """
        if self._started:
            raise McpError(CONNECTION_FAILED, "the client transport was already started")
        if self._closed:
            raise McpError(MCP_CLIENT_CLOSED, "a closed client cannot be restarted")
        connection = self._build_connection()
        try:
            connection.connect()  # TCP + TLS handshake; zero application bytes
        except (OSError, ssl.SSLError) as exc:
            connection.close()
            raise McpError(
                CONNECTION_FAILED,
                f"the endpoint could not be reached: {type(exc).__name__}: {exc}") from exc
        self._connection = connection
        self._started = True

    def connect(self) -> Mapping[str, Any]:
        """``initialize`` negotiation; records the ACTUAL protocolVersion.

        A JSON-RPC error answer or an unsupported negotiated version is a
        typed ``PROTOCOL_MISMATCH`` after the local session has been closed
        - nothing stays half-live. Both happen only AFTER a full server
        answer, so the outcome is confirmed; any transport break instead
        surfaces as ``ClientRequestUnconfirmed`` and parks the lease in
        ``unknown`` via the manager.
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
            self.close()  # a frame was written; tear the local session down
            raise
        except McpError:
            # a confirmed security/status refusal during the handshake also
            # ends the local session: nothing half-open stays behind
            self.close()
            raise
        if "error" in answer:
            self.close()
            error = answer["error"]
            message = error.get("message") if isinstance(error, Mapping) else error
            raise McpError(
                PROTOCOL_MISMATCH,
                f"the server refused the initialize offer: {message} - the "
                "local session is closed (the remote service, if any, is not "
                "ours to stop)")
        result = answer.get("result")
        if not isinstance(result, Mapping):
            self.close()
            raise McpError(
                MCP_HTTP_REQUEST_REFUSED, "the initialize answer carries no result object")
        negotiated = result.get("protocolVersion")
        if (not isinstance(negotiated, str)
                or negotiated not in self._policy.supported_protocol_versions):
            self.close()
            raise McpError(
                PROTOCOL_MISMATCH,
                f"the server negotiated {negotiated!r}, outside the client's "
                "supported list - the local session is closed (the remote "
                "service, if any, is not ours to stop)")
        info = result.get("serverInfo")
        self.negotiated_protocol_version = negotiated
        self.server_info = info if isinstance(info, Mapping) else {}
        # the server-issued session id lives on THIS instance only
        self.session_id = answer.get("_session_id") or None
        self._connected = True
        try:
            self._notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except ClientRequestUnconfirmed:
            self.close()
            raise
        return {"protocolVersion": negotiated, "serverInfo": dict(self.server_info)}

    # -- requests ---------------------------------------------------------------------

    def list_tools(self) -> Mapping[str, Any]:
        """``tools/list`` over the negotiated connection (refused locally
        unless connected; drift detection stays in the manager)."""
        self._require_live("tools/list")
        answer = self._request(
            {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/list",
             "params": {}}, timeout=self._policy.request_timeout)
        if "error" in answer:
            raise ClientRequestUnconfirmed("the tools/list answer carried an error")
        result = answer.get("result")
        if not isinstance(result, Mapping) or not isinstance(result.get("tools"), list):
            raise ClientRequestUnconfirmed(
                "the tools/list answer carries no tools array")
        return {"tools": list(result["tools"])}

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """``tools/call`` - the only path with server-side effects.

        Every gate (lease state, catalog/approval subset, Permission
        authority) runs in ``ManagedSessionManager`` BEFORE this method is
        entered; this client adds no gate and is never a side door. A
        JSON-RPC error answer may still have executed the tool ->
        unconfirmed, exactly the stdio ruling; 401/403 are confirmed
        refusals (the server rejected the call before running it).
        """
        self._require_live("tools/call")
        answer = self._request(
            {"jsonrpc": "2.0", "id": self._new_id(), "method": "tools/call",
             "params": {"name": name, "arguments": dict(arguments)}},
            timeout=self._policy.request_timeout)
        if "error" in answer:
            error = answer["error"]
            message = error.get("message") if isinstance(error, Mapping) else error
            raise ClientRequestUnconfirmed(
                f"the server answered tools/call with an error: {message}")
        result = answer.get("result")
        return dict(result) if isinstance(result, Mapping) else {"value": result}

    # -- close --------------------------------------------------------------------------

    def close(self) -> None:
        """Idempotent LOCAL teardown: connection closed, session id and
        every credential reference dropped.

        This never claims the remote service stopped, and cannot: the
        recorded close fact states ``remoteServiceLifecycle: "not-owned"``
        (harness-adapters.md「Managed lane」). After close the client holds
        no plan, no port and no resolved value, and cannot resolve again.
        """
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._connected = False
            self._transport_down = True
            connection = self._connection
            self._connection = None
            had_session = self.session_id is not None
            self.session_id = None
            self._launch_plan = None
            self._credential_port = None
        self.close_fact = {"localSessionClosed": True,
                           "sessionIdDropped": had_session,
                           "remoteServiceLifecycle": REMOTE_SERVICE_LIFECYCLE}
        if connection is not None:
            self._hang_up(connection)

    @staticmethod
    def _hang_up(connection: HTTPConnection) -> None:
        """Close the local socket, first SHUT_RDWR-ing it so a reader
        blocked in ``getresponse`` wakes with an immediate error: the HTTP
        answer to "cancel" is a local hang-up whose in-flight outcome is
        unconfirmed (FR-10), never a pretend-confirmed abort."""
        try:
            sock = getattr(connection, "sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass

    # -- credential material (transient by construction) --------------------------------

    def _request_headers(self) -> dict:
        """Build this request's header map; plaintext lives ONLY in the
        local dict handed to ``http.client`` and is never a field of self.

        Resolution order mirrors the manager's gates: closed client -> typed
        refusal; declared SecretRef without a (still-held) plan/port pair ->
        ``SECRET_UNRESOLVED``; a declared slot with no binding in the plan
        -> ``SECRET_UNRESOLVED``; rotated/revoked/expired credential ->
        whatever :func:`resolve_for_launch` refuses with (PLAN_STALE /
        SECRET_UNRESOLVED) - always BEFORE a single byte is written.
        """
        headers: dict = {}
        secret_slots = []
        for name, value in self._headers.items():
            if isinstance(value, Literal):
                headers[str(name)] = value.value
            elif isinstance(value, SecretRef):
                secret_slots.append(str(name))
            else:  # pragma: no cover - the revision model has exactly two values
                raise McpError(MCP_TRANSPORT_UNSUPPORTED, "the header value shape is unknown")
        if not secret_slots:
            return headers
        plan, port = self._launch_plan, self._credential_port
        if plan is None or port is None:  # closed between checks: fail closed
            raise McpError(
                SECRET_UNRESOLVED,
                "credential header slot(s) requested but no launch-plan/port "
                "pair is live; refusing to send unresolved")
        keyed = {binding.slot: binding for binding in plan.bindings
                 if binding.kind == "header"
                 and (self._binding_scope is None
                      or (binding.definition_id, binding.revision) == self._binding_scope)}
        for slot in secret_slots:
            if slot not in keyed:
                raise McpError(
                    SECRET_UNRESOLVED,
                    f"the definition declares credential header slot {slot!r} "
                    "with no binding in the launch plan; refusing to send half-authenticated")
        resolved = resolve_for_launch(plan, port, time.time())  # batch fail-closed
        out = dict(headers)
        for slot in secret_slots:
            value = resolved.headers.get(keyed[slot].key)
            if value is None:  # pragma: no cover - resolve_for_launch fills all bindings
                raise McpError(
                    SECRET_UNRESOLVED,
                    f"credential header slot {slot!r} resolved to nothing; "
                    "refusing to send unresolved")
            out[slot] = value
        return out

    # -- plumbing -------------------------------------------------------------------------

    def _build_connection(self) -> HTTPConnection:
        if self._scheme == "https":
            # TLS verification is never optional: either the system trust
            # store (ca_bundle=None) or the configured anchor file; hostname
            # checking stays on in both cases.
            context = ssl.create_default_context(
                cafile=self._policy.ca_bundle if self._policy.ca_bundle else None)
            return HTTPSConnection(
                self._host, self._port, context=context,
                timeout=self._policy.connect_timeout)
        return HTTPConnection(
            self._host, self._port, timeout=self._policy.connect_timeout)

    def _assert_origin(self) -> None:
        """Host/origin consistency: the connection in use must still be the
        configured URL's authority (scheme, exact host, port). Guards
        against any later re-pointing of the instance fields sending the
        session (and its auth headers) somewhere else."""
        current = (self._scheme, self._host, self._port)
        expected = urlsplit(self._url)
        expected_port = expected.port or (443 if expected.scheme == "https" else 80)
        if (expected.scheme.lower(), (expected.hostname or "").lower(), expected_port) != current:
            self._transport_down = True
            raise McpError(
                MCP_HTTP_HOST_ORIGIN_MISMATCH,
                "the client's connection target no longer matches its "
                "configured origin; refusing to send")

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

    def _request(self, frame: Mapping[str, Any], *, timeout: float) -> dict:
        request_id = frame.get("id")
        status, headers, raw = self._post(frame, timeout=timeout)
        if not raw.strip():
            self._kill_local_session()
            raise ClientRequestUnconfirmed(
                f"the server answered {frame.get('method')!r} with an empty body")
        answer = self._json_answer(raw)
        if answer.get("id") != request_id:
            self._kill_local_session()
            raise ClientRequestUnconfirmed(
                f"the answer carries id {answer.get('id')!r}, not this request's id")
        session_id = (headers.get("Mcp-Session-Id") if headers else None) or None
        if session_id is not None and frame.get("method") == "initialize":
            answer["_session_id"] = session_id  # recorded by connect() only
        return answer

    def _notify(self, frame: Mapping[str, Any]) -> None:
        self._post(frame, timeout=self._policy.request_timeout)

    def _json_answer(self, raw: bytes) -> dict:
        try:
            answer = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            self._kill_local_session()
            raise ClientRequestUnconfirmed(
                "the server answered with a non-JSON body") from exc
        if not isinstance(answer, Mapping):
            self._kill_local_session()
            raise ClientRequestUnconfirmed("the server answered with a non-object frame")
        return dict(answer)

    def _kill_local_session(self) -> None:
        """Mid-request transport break: drop the local connection so no
        later request can interleave on a half-read stream; the caller
        raises - the lease lands in unknown via the manager."""
        with self._state_lock:
            self._transport_down = True
            self._connected = False
            connection = self._connection
            self._connection = None
        if connection is not None:
            self._hang_up(connection)

    def _post(self, frame: Mapping[str, Any], *, timeout: float) -> Tuple[int, Any, bytes]:
        """Write one JSON-RPC frame as a POST and return (status, headers,
        body-bytes). Everything before ``request()`` is confirmed-refusal
        territory (typed McpError, zero bytes written); from ``request()``
        on, a transport break is ``ClientRequestUnconfirmed``."""
        if self._closed:
            raise McpError(MCP_CLIENT_CLOSED, "the client is closed")
        self._assert_origin()
        if self._connection is None or self._transport_down:
            raise McpError(MCP_HTTP_TRANSPORT_DOWN, "the local session is down")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   **self._request_headers()}
        if self.negotiated_protocol_version:
            headers["MCP-Protocol-Version"] = self.negotiated_protocol_version
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        body = json.dumps(frame, sort_keys=True).encode("utf-8")
        connection = self._connection
        written = False
        try:
            if connection.sock is not None:
                connection.sock.settimeout(timeout)
            connection.timeout = timeout
            # from here on bytes may already be on the wire (a partial
            # write is still a write): every break is UNCONFIRMED.
            written = True
            connection.request("POST", self._path, body=body, headers=headers)
            response = connection.getresponse()
            payload = self._read_bounded(response, timeout)
        except ClientRequestUnconfirmed:
            # bound/deadline breaks from the reader: the stream is
            # half-consumed, drop the local connection before propagating.
            self._kill_local_session()
            raise
        except McpError:
            raise
        except (OSError, HTTPException) as exc:
            raise self._after(written, f"the transport broke: {type(exc).__name__}") from exc
        status = response.status
        if 300 <= status < 400:
            # redirects are never followed: a 3xx must not move this
            # session (or its auth header) to another authority.
            self._kill_local_session()
            raise McpError(
                MCP_HTTP_REDIRECT_REFUSED,
                f"the endpoint redirected ({status}); the managed http "
                "client never follows redirects")
        if status in (401, 403):
            self._kill_local_session()
            raise McpError(
                AUTH_REQUIRED,
                f"the endpoint refused authorization ({status}); the "
                "request was rejected before any tool effect")
        if 400 <= status < 500:
            self._kill_local_session()
            raise McpError(
                MCP_HTTP_REQUEST_REFUSED, f"the endpoint refused the request ({status})")
        if status >= 500:
            self._kill_local_session()
            raise ClientRequestUnconfirmed(
                f"the endpoint failed with status {status} after receiving "
                "the frame; the server-side outcome is unconfirmed")
        return status, response.headers, payload

    def _after(self, written: bool, reason: str) -> BaseException:
        """A break before any byte left is confirmed; after, unconfirmed."""
        self._kill_local_session()
        if not written:
            return McpError(
                CONNECTION_FAILED, f"the request never left: {reason}")
        return ClientRequestUnconfirmed(
            f"no usable answer ({reason}); the server-side outcome is unconfirmed")

    def _read_bounded(self, response: Any, timeout: float) -> bytes:
        """Read the response body under the byte bound and wall-clock
        deadline; SSE (text/event-stream) answers have their first JSON-RPC
        data-line extracted, the same framing discipline as the probe."""
        declared = response.getheader("Content-Length")
        if (declared is not None and declared.strip().isdigit()
                and int(declared) > self._policy.max_response_bytes):
            raise ClientRequestUnconfirmed(
                "the answer declares a body over the read bound")
        deadline = time.monotonic() + timeout
        collected = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise ClientRequestUnconfirmed(
                    "the answer did not finish within the deadline")
            want = max(1, min(4096, self._policy.max_response_bytes + 1 - len(collected)))
            chunk = response.read1(want) if hasattr(response, "read1") else response.read(want)
            if not chunk:
                break
            collected.extend(chunk)
            if len(collected) > self._policy.max_response_bytes:
                raise ClientRequestUnconfirmed("the answer exceeds the read bound")
            remaining = getattr(response, "length_remaining", None)
            if remaining == 0:
                break
            if remaining is None and b"\n" in collected:
                break
        content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type == "text/event-stream":
            for raw_line in bytes(collected).split(b"\n"):
                line = raw_line.strip()
                if line.startswith(b"data:"):
                    return line[len(b"data:"):].strip()
            raise ClientRequestUnconfirmed("the SSE answer carries no data line")
        return bytes(collected)


# -- the lease -> client factory (one fresh instance per lease, no pooling) --------

def make_http_client_factory(
    definitions: Any, *, policy: Optional[HttpClientPolicy] = None,
    launch_plan: Optional[LaunchPlan] = None,
    credential_port: Optional[CredentialPort] = None,
) -> Callable[["McpConnectionLease"], HttpManagedClient]:
    """A ``ClientFactory`` producing one fresh :class:`HttpManagedClient`
    per lease, driven entirely by the stored revision.

    The factory is asked exactly once per lease by the manager and always
    constructs a NEW instance - there is no cache, no pool, no shared
    connection: two leases on one URL are two HTTP sessions (server-side
    provable, verification.md counterexample 3). Stdio transports are a
    typed refusal here: they belong to
    :func:`backend.managed.client_stdio.make_stdio_client_factory`.

    ``launch_plan``/``credential_port`` are the T07 pair handed to every
    produced client; a revision with ``SecretRef`` headers and no pair is a
    ``SECRET_UNRESOLVED`` refusal at production time (fail closed, before
    any socket use).
    """
    def factory(lease: McpConnectionLease) -> HttpManagedClient:
        model: McpRevision = definitions.read_revision(
            server_scope=lease.server_scope,
            definition_id=lease.definition_id, revision=lease.revision)
        transport = model.transport
        if not isinstance(transport, RemoteTransport):
            raise McpError(
                MCP_TRANSPORT_UNSUPPORTED,
                "the managed http client covers remote (Streamable-HTTP) "
                "transports only; a stdio lease belongs to the stdio client")
        return HttpManagedClient(
            url=transport.url, headers=transport.headers,
            launch_plan=launch_plan, credential_port=credential_port,
            binding_scope=(model.definition_id, model.revision),
            policy=policy)
    return factory
