"""Authenticated loopback HTTP API for the independent Server.

The host owns the transport walls and the generic surfaces: health, the
wire/1 dispatch route, the OpenAPI view, the two websocket channels and the
plugin route admission seam. Business REST routes are contributed by the
domain plugins through `HttpRouteDescriptor`s and admitted behind the same
walls below — never re-declared here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import secrets
from typing import Annotated
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ordessa_server.acp_admission import AcpAdmissionRefused
from ordessa_server.bootstrap import ServerRuntime
from ordessa_server.errors import ServerError
from ordessa_server.wire import WireError, decode_request, encode_error, encode_result
from ordessa_server.wire.handlers import WIRE_VERSION


def _loopback_authority(value: str) -> bool:
    host = value.rsplit(":", 1)[0].lower() if not value.startswith("[") else value.split("]", 1)[0] + "]"
    return host in {"127.0.0.1", "localhost", "[::1]"}


def create_app(runtime: ServerRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        # A restart activates plugins after this app was created: their HTTP
        # routes mount now (deduped against the creation-time mounts), and
        # the served route set freezes only once startup is complete — so a
        # later activation with unmounted routes refuses instead of leaking
        # a half-effective plugin. The mounting sits inside the cleanup: a
        # mount-stage refusal must still dispose the round and release the
        # data root, not leave a started runtime behind.
        try:
            _mount_plugin_routes()
            if getattr(runtime, "plugin_host", None) is not None:
                runtime.plugin_host.frozen_http_routes = frozenset(_mounted_routes)
            yield
        finally:
            runtime.stop()

    app = FastAPI(
        title="Ordessa Server", version="1", lifespan=lifespan,
        openapi_url=None, docs_url=None, redoc_url=None,
    )

    @app.middleware("http")
    async def loopback_policy(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
        request.state.request_id = request_id
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        if not _loopback_authority(host) or (origin and not _loopback_authority(origin.split("//", 1)[-1])):
            return _error("LOOPBACK_POLICY_REJECTED", "Host or Origin is not allowed", 403, False, request_id)
        response = await call_next(request)
        # Windows PowerShell 5 otherwise decodes non-ASCII JSON with the active
        # ANSI code page even though JSON itself is UTF-8 by specification.
        if response.headers.get("content-type") == "application/json":
            response.headers["content-type"] = "application/json; charset=utf-8"
        response.headers["X-Request-ID"] = request_id
        return response

    def _error_handler(request: Request, exc: ServerError):
        return _error(exc.code, exc.message, exc.status, exc.retryable, request.state.request_id)

    app.add_exception_handler(ServerError, _error_handler)

    @app.exception_handler(Exception)
    async def _unexpected_exception_handler(request: Request, exc: Exception):
        # The boundary's own last wall (order 123), registered on the app so it
        # covers everything no route catches: authentication, envelope decoding,
        # `encode_result`, the SSE generator, and any route added later. The
        # status stays 500 — the Server genuinely failed — but the plain-text
        # body that replaces the contract is what is no longer allowed. The
        # exception's text never leaves; only its type, as `internalCode`.
        return JSONResponse(status_code=500, content={
            "error": {
                "code": "UNAVAILABLE",
                "message": "this Server could not answer the request",
                "details": {"internalCode": type(exc).__name__, "retryable": True},
            },
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        return _error("REQUEST_INVALID", "Request did not match the API schema", 422, False, request.state.request_id)

    def authorize(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        # A direct call (the wire route) has no dependency injection, so fall
        # back to reading the header itself; the comparison is shared.
        provided = authorization if authorization is not None else request.headers.get("authorization")
        expected = "Bearer " + runtime.token
        if provided is None or not secrets.compare_digest(provided, expected):
            raise ServerError("AUTHENTICATION_REQUIRED", "A valid bearer token is required", status=401)

    protected = [Depends(authorize)]

    @app.get("/live")
    def live():
        return {"status": "alive"}

    @app.post("/wire/v1/{method}")
    async def wire(method: str, request: Request, response: Response):
        """wire/1 entry point: one method per request, JSON-RPC shaped.

        Authentication is required for every method, including `server.hello`:
        the host reads the per-instance token from the protected bootstrap file
        in the data root, so an unauthenticated local process cannot even
        enumerate this Server's capabilities.
        """
        try:
            authorize(request)
        except ServerError as exc:
            return JSONResponse(status_code=exc.status, content=encode_error(
                None, WireError.from_server_error(exc),
            ))
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001 - a malformed body is a client error
            return JSONResponse(status_code=400, content=encode_error(
                None, WireError("INVALID_REQUEST", f"Request body is not valid JSON: {exc}"),
            ))
        try:
            request_id, wire_method, params = decode_request(body)
        except WireError as exc:
            return JSONResponse(status_code=400, content=encode_error(None, exc))
        if wire_method != method:
            return JSONResponse(status_code=400, content=encode_error(
                request_id,
                WireError("INVALID_REQUEST", "method does not match the request path"),
            ))
        try:
            result = runtime.wire.dispatch(wire_method, params)
        except WireError as exc:
            return JSONResponse(status_code=200, content=encode_error(request_id, exc))
        except Exception as exc:  # noqa: BLE001 - order 123, the third wall
            # Anything escaping the wire layer still leaves as a JSON-RPC error
            # object. The bare status is what broke the contract: `QA-008`'s
            # users got `500 / text/plain / 21 bytes` where an envelope belongs.
            # `internalCode` carries the exception **type** only — its text can
            # name a host path or a credential locator (`R-0011`).
            return JSONResponse(status_code=200, content=encode_error(request_id, WireError(
                "UNAVAILABLE", "this Server could not answer the request",
                {"internalCode": type(exc).__name__, "retryable": True},
            )))
        response.headers["X-Wire-Version"] = WIRE_VERSION
        return encode_result(request_id, result)

    @app.get("/api/v1/openapi.json", dependencies=protected)
    def openapi():
        return app.openapi()

    @app.websocket("/wire/v1/event-stream")
    async def wire_event_stream(websocket: WebSocket):
        """Authenticated `wire.eventStream/1` channel carrying EventFrame JSON."""
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin")
        provided = websocket.headers.get("authorization")
        if (not _loopback_authority(host)
                or (origin and not _loopback_authority(origin.split("//", 1)[-1]))):
            await websocket.close(code=4403, reason="LOOPBACK_POLICY_REJECTED")
            return
        if provided is None or not secrets.compare_digest(provided, "Bearer " + runtime.token):
            await websocket.close(code=4401, reason="UNAUTHENTICATED")
            return
        session_id = websocket.query_params.get("sessionId", "")
        cursor = websocket.query_params.get("cursor")
        if not session_id or len(session_id) > 160:
            await websocket.close(code=4400, reason="INVALID_REQUEST")
            return
        # The push relay is host transport; the event source is the sessions
        # domain's declared port, resolved from the live activation round
        # (`FR-006`: the host runtime carries no business attribute). A round
        # without the plugin resolves to None = fail closed, the typed close
        # below.
        plugin_host = getattr(runtime, "plugin_host", None)
        stream_source = (plugin_host.provided_port("events.stream_source")
                         if plugin_host is not None else None)
        if stream_source is None:
            await websocket.close(code=4400, reason="UNKNOWN_ROUTE")
            return
        try:
            frames, cursor = stream_source(session_id, cursor)
        except (WireError, ServerError):
            await websocket.close(code=4400, reason="INVALID_CURSOR_OR_SESSION")
            return
        except Exception as exc:  # noqa: BLE001 - order 123: close, never escape
            # The reason is the exception type, never its text (`R-0011`).
            await websocket.close(code=4400, reason=type(exc).__name__[:120])
            return
        await websocket.accept()
        try:
            while True:
                if frames:
                    for frame in frames:
                        await websocket.send_json(frame)
                    frames = []
                    continue
                frames, cursor = stream_source(session_id, cursor)
                if frames:
                    continue
                import asyncio
                # Waiting only on an in-process Condition cannot observe a peer
                # close.  A bounded receive detects disconnects while the next
                # persisted batch remains the sole source of event truth.
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                    if message.get("type") == "websocket.disconnect":
                        return
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            return

    @app.websocket("/wire/v1/acp-channel/{connection_id}")
    async def wire_acp_channel(websocket: WebSocket, connection_id: str):
        """Bidirectional ACP frame relay with a host-owned effect admission wall.

        Only prompt and reverse-answer identities are inspected. A client
        disconnecting is not a release - the channel, its
        Agent and its run record stay exactly as they were (seam doc §2).
        """
        import asyncio

        # Admission pinned by the reviewed tests: non-loopback Origin -> 4403,
        # missing/wrong bearer -> 4401, unknown connectionId -> 4400, all
        # before accept.  Unlike /wire/v1/event-stream there is no Host clause:
        # the pinned client (ManagedChannel) attaches over the TestClient's
        # default host, and this route is bearer-gated regardless.
        origin = websocket.headers.get("origin")
        provided = websocket.headers.get("authorization")
        if origin and not _loopback_authority(origin.split("//", 1)[-1]):
            await websocket.close(code=4403, reason="LOOPBACK_POLICY_REJECTED")
            return
        if provided is None or not secrets.compare_digest(provided, "Bearer " + runtime.token):
            await websocket.close(code=4401, reason="UNAUTHENTICATED")
            return
        # Stream admission goes through the host's route registry: the route's
        # owner only resolves the connection; origin, bearer and close codes
        # above and below stay host-owned.
        connection = runtime.wire.stream_routes.resolve("acp-channel", connection_id)
        if connection is None:
            await websocket.close(code=4400, reason="UNKNOWN_CONNECTION")
            return
        gate = runtime.wire.acp_admission_gate
        if gate is None:
            await websocket.close(code=4403, reason="ACP_ADMISSION_UNAVAILABLE")
            return
        await websocket.accept()
        inbox: asyncio.Queue = asyncio.Queue()

        def _sink(item):
            if isinstance(item, str):
                gate.observe_agent_frame(connection_id, item)
            elif item is None:
                gate.forget_channel(connection_id)
            inbox.put_nowait(item)

        async def _pump():
            while True:
                item = await inbox.get()
                if item is None:
                    try:
                        await websocket.close(code=1001)
                    except Exception:  # noqa: BLE001 - the socket is already gone
                        pass
                    return
                await websocket.send_text(item)

        loop = asyncio.get_running_loop()
        connection.attach(loop, _sink)
        pump = asyncio.create_task(_pump())
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text = message.get("text")
                if text is None:
                    continue
                transport = connection.transport
                if transport is None:
                    break
                try:
                    gate.admit_client_frame(connection, text)
                    transport.send_line(text)
                except AcpAdmissionRefused:
                    await websocket.close(code=4403, reason="ACP_ADMISSION_REFUSED")
                    break
                except Exception:  # noqa: BLE001 - the Agent is gone; answer nothing for it
                    break
        except WebSocketDisconnect:
            pass
        finally:
            connection.detach(loop, _sink)
            pump.cancel()

    # -- plugin-contributed business routes (the plugin-host HTTP seam) -----
    # Admitted behind exactly the host's walls: the `protected` bearer
    # dependency, the loopback middleware above, and the app-level error
    # handlers. A plugin route that would shadow a host route (same path,
    # overlapping method) is a startup refusal, never a silent second
    # handler; plugin-vs-plugin duplicates are refused at activation.
    if getattr(runtime, "plugin_host", None) is not None:
        from fastapi.routing import APIRoute

        host_methods: dict[str, set[str]] = {}
        for route in app.routes:
            if isinstance(route, APIRoute):
                host_methods.setdefault(route.path, set()).update(route.methods)

        def _owner_guard(descriptor, endpoint):
            """The mounted route serves exactly while its owner is active,
            and serves the owner's CURRENT registration: both the ownership
            check and the endpoint resolution run at request time against
            the live registry, so an unload takes the capability away from
            the RUNNING app and a re-activated owner serves its new build —
            not just stale table rows."""
            import functools

            @functools.wraps(endpoint)
            def guarded(*args, **kwargs):
                if not runtime.plugin_host.is_active(descriptor.owner):
                    raise ServerError(
                        "PLUGIN_CAPABILITY_UNAVAILABLE",
                        f"the plugin owning {descriptor.path} is not active",
                        status=404,
                    )
                current = None
                for item in runtime.plugin_host.http_routes.descriptors():
                    if (item.path == descriptor.path
                            and item.methods == descriptor.methods
                            and item.owner == descriptor.owner):
                        current = item.endpoint
                        break
                if current is None:  # unregistered between the two checks
                    raise ServerError(
                        "PLUGIN_CAPABILITY_UNAVAILABLE",
                        f"the plugin owning {descriptor.path} is not active",
                        status=404,
                    )
                return current(*args, **kwargs)
            return guarded

        _mounted_routes: set[tuple[str, frozenset[str], str, bool, str]] = set()

        def _mount_plugin_routes() -> list:
            """Mount every registered plugin route this app does not serve
            yet. Idempotent: creation-time mounting and restart-time mounting
            share the same shape-keyed dedup. The mounted shape carries the
            auth flag and the endpoint's signature — the request machinery
            the app actually built. A declaration that OVERLAPS a mounted
            route (same path, intersecting methods) without matching its
            shape exactly refuses type-wise here — before the freeze exists
            too: no second same-path route is ever added, and no new owner
            takes over a mounted route through the pre-startup window."""
            import inspect

            from server_plugin_api import (
                DuplicateHttpRouteError, HttpRouteShapeChangedError,
            )

            newly = []
            for descriptor in runtime.plugin_host.http_routes.descriptors():
                shape = (descriptor.path, frozenset(descriptor.methods), descriptor.owner,
                         descriptor.authenticated,
                         str(inspect.signature(descriptor.endpoint)))
                if shape in _mounted_routes:
                    continue
                overlap = next((m for m in _mounted_routes
                                if m[0] == descriptor.path
                                and m[1] & frozenset(descriptor.methods)), None)
                if overlap is not None:
                    label = (f"{descriptor.path} ({', '.join(sorted(descriptor.methods))})")
                    if overlap[2] != descriptor.owner:
                        raise DuplicateHttpRouteError(
                            descriptor.path, tuple(descriptor.methods),
                            overlap[2], descriptor.owner)
                    changed = []
                    if overlap[3] != descriptor.authenticated:
                        changed.append(
                            f"{label}: auth {overlap[3]} -> {descriptor.authenticated}")
                    if overlap[4] != shape[4]:
                        changed.append(f"{label}: endpoint signature changed")
                    raise HttpRouteShapeChangedError(descriptor.owner, tuple(changed))
                clash = host_methods.get(descriptor.path)
                if clash and (clash & set(descriptor.methods)):
                    raise RuntimeError(
                        "PLUGIN_HTTP_ROUTE_CONFLICT: "
                        f"{descriptor.path} ({', '.join(sorted(descriptor.methods))}) "
                        f"declared by {descriptor.owner} collides with a host route"
                    )
                app.add_api_route(
                    descriptor.path, _owner_guard(descriptor, descriptor.endpoint),
                    methods=sorted(descriptor.methods),
                    dependencies=protected if descriptor.authenticated else None,
                    name=f"plugin:{descriptor.owner}:{descriptor.path}",
                )
                _mounted_routes.add(shape)
                newly.append(descriptor)
            return newly

        for descriptor in runtime.plugin_host.http_routes.descriptors():
            _mount_plugin_routes()

    return app


def _error(code: str, message: str, status: int, retryable: bool, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable, "request_id": request_id}},
    )
