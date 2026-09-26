"""Authenticated loopback HTTP API for the independent Server."""
from __future__ import annotations

from contextlib import asynccontextmanager
import json
import secrets
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ordessa_server.bootstrap import ServerRuntime
from ordessa_server.errors import ServerError
from ordessa_server.wire import WireError, decode_request, encode_error, encode_result
from ordessa_server.wire.handlers import WIRE_VERSION


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProbeRequest(StrictModel):
    kind: str
    distribution: str = Field(min_length=1, max_length=128)
    user: str | None = Field(default=None, min_length=1, max_length=128)


class CredentialImportRequest(StrictModel):
    kind: str = Field(min_length=1, max_length=32)
    source_path: str = Field(min_length=1, max_length=4096)
    confirm_source_path: str = Field(min_length=1, max_length=4096)


class BrowseRequest(StrictModel):
    probe_id: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=4096)


class WorkspaceRequest(BrowseRequest):
    pass


class ProfileRequest(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    harness_type: str = Field(min_length=1, max_length=64)
    configuration: dict[str, Any]
    credential_id: str | None = Field(default=None, min_length=1, max_length=160)


class SessionRequest(StrictModel):
    workspace_id: str = Field(min_length=1, max_length=160)
    profile_id: str = Field(min_length=1, max_length=160)


class TurnRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4096)
    expected_profile_revision: int = Field(ge=1)
    overrides: dict[str, Any] | None = None


def _loopback_authority(value: str) -> bool:
    host = value.rsplit(":", 1)[0].lower() if not value.startswith("[") else value.split("]", 1)[0] + "]"
    return host in {"127.0.0.1", "localhost", "[::1]"}


def create_app(runtime: ServerRuntime) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runtime.start()
        try:
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

    def idempotency_key(
        value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> str:
        if value is None or not (1 <= len(value) <= 160):
            raise ServerError("IDEMPOTENCY_KEY_REQUIRED", "A bounded Idempotency-Key is required", status=400)
        return value

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

    # -- delegation bridge (order 65 C) ------------------------------------
    #
    # The bridge inside the sandbox is not a bearer of the user's token: it
    # carries an attempt-scoped token minted when the parent turn was
    # assembled, and this surface resolves it to that one turn. Reads only the
    # two delegation operations, loops back to the same policy as every other
    # route (the loopback middleware above), and answers nothing else.
    @app.post("/internal/delegation/{token}")
    async def delegation(token: str, request: Request) -> JSONResponse:
        body = await request.json()
        registry = getattr(runtime, "delegation_tokens", None)
        grant = (registry or {}).get(token)
        if grant is None:
            return JSONResponse({"error": "DELEGATION_TOKEN_UNKNOWN"}, status_code=404)
        op = body.get("op")
        service = getattr(runtime, "delegation_service", None)
        if service is None:
            return JSONResponse({"error": "DELEGATION_UNAVAILABLE"}, status_code=503)
        try:
            if op == "list":
                payload = service.list_for(parent_profile_id=grant["profileId"])
                return JSONResponse({"result": payload})
            if op == "run":
                payload = service.run(
                    parent_turn_id=grant["turnId"], parent_profile_id=grant["profileId"],
                    arguments=dict(body.get("arguments") or {}),
                    calls_this_turn=int(body.get("callsThisTurn") or 0),
                )
                return JSONResponse({"result": payload})
        except Exception as refusal:  # noqa: BLE001 - typed by the service
            return JSONResponse({
                "error": getattr(refusal, "code", type(refusal).__name__),
                "message": getattr(refusal, "message", str(refusal)),
                "available": list(getattr(refusal, "available", ()) or ()),
            }, status_code=409)
        return JSONResponse({"error": "DELEGATION_OP_UNKNOWN"}, status_code=400)

    @app.get("/api/v1/readiness", dependencies=protected)
    def readiness():
        return runtime.service.readiness()

    @app.get("/api/v1/openapi.json", dependencies=protected)
    def openapi():
        return app.openapi()

    @app.get("/api/v1/wsl/distributions", dependencies=protected)
    def distributions():
        return {"items": runtime.service.distributions()}

    @app.get("/api/v1/credentials", dependencies=protected)
    def credentials():
        """Which credentials this Server can resolve (ids and kinds only)."""
        return {"items": runtime.service.list_credentials()}

    @app.post("/api/v1/credentials", dependencies=protected)
    def import_credential(
        body: CredentialImportRequest, response: Response,
        key: str = Depends(idempotency_key),
    ):
        """Import one credential from a *path*, never from a payload.

        The body names where the secret is; this Server's own secret store reads
        it (with the store's symlink, type and size rules), so credential
        material never travels in a request. The caller must repeat the source
        path, the same discipline the one-shot CLI applies, because a mistyped
        path would silently import the wrong file. The answer carries the opaque
        id the product will reference and nothing else.
        """
        if body.source_path != body.confirm_source_path:
            raise ServerError(
                "CREDENTIAL_SOURCE_UNCONFIRMED",
                "confirm_source_path must repeat source_path exactly",
                status=422,
            )
        status, result = runtime.service.import_credential(
            kind=body.kind, source=body.source_path, key=key,
        )
        response.status_code = status
        return result

    @app.post("/api/v1/connections/probe", dependencies=protected)
    def probe(body: ProbeRequest, response: Response, key: str = Depends(idempotency_key)):
        if body.kind != "wsl":
            raise ServerError("CONNECTION_KIND_UNSUPPORTED", "Only WSL connections are supported", status=422)
        status, result = runtime.service.probe(key, body.distribution, body.user)
        response.status_code = status
        return result

    @app.post("/api/v1/connections/browse", dependencies=protected)
    def browse(body: BrowseRequest, response: Response, key: str = Depends(idempotency_key)):
        status, result = runtime.service.browse(key, body.probe_id, body.path)
        response.status_code = status
        return result

    @app.post("/api/v1/workspaces", dependencies=protected)
    def create_workspace(body: WorkspaceRequest, response: Response, key: str = Depends(idempotency_key)):
        status, result = runtime.service.create_workspace(key, body.model_dump())
        response.status_code = status
        return result

    @app.get("/api/v1/workspaces", dependencies=protected)
    def list_workspaces():
        return {"items": runtime.repository.list_workspaces()}

    @app.post("/api/v1/profiles", dependencies=protected)
    def create_profile(body: ProfileRequest, response: Response, key: str = Depends(idempotency_key)):
        status, result = runtime.service.create_profile(key, body.model_dump())
        response.status_code = status
        return result

    @app.get("/api/v1/profiles", dependencies=protected)
    def list_profiles():
        return {"items": runtime.service.profiles.list()}

    @app.post("/api/v1/sessions", dependencies=protected)
    def create_session(body: SessionRequest, response: Response, key: str = Depends(idempotency_key)):
        status, result = runtime.service.create_session(key, body.model_dump())
        response.status_code = status
        return result

    @app.get("/api/v1/sessions/{session_id}", dependencies=protected)
    def get_session(session_id: str):
        return runtime.repository.get_session(session_id)

    @app.post("/api/v1/sessions/{session_id}/turns", dependencies=protected)
    def create_turn(
        session_id: str, body: TurnRequest, response: Response,
        key: str = Depends(idempotency_key),
    ):
        status, result = runtime.service.create_turn(session_id, key, body.model_dump())
        response.status_code = status
        return result

    @app.get("/api/v1/sessions/{session_id}/events", dependencies=protected)
    def events(session_id: str, after: int = Query(default=0, ge=0)):
        generation = runtime.notifier.generation()
        history = runtime.repository.list_events(session_id, after)

        def stream():
            cursor = after
            for item in history:
                payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {item['seq']}\nevent: {item['kind']}\ndata: {payload}\n\n"
                cursor = item["seq"]
            current_generation = generation
            while True:
                batch = runtime.repository.list_events(session_id, cursor)
                if batch:
                    for item in batch:
                        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                        yield f"id: {item['seq']}\nevent: {item['kind']}\ndata: {payload}\n\n"
                        cursor = item["seq"]
                    current_generation = runtime.notifier.generation()
                    continue
                next_generation = runtime.notifier.wait_after(current_generation)
                if next_generation == current_generation:
                    yield ": keepalive\n\n"
                current_generation = next_generation

        return StreamingResponse(stream(), media_type="text/event-stream")

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
        try:
            frames, cursor = runtime.wire.event_stream_batch(session_id, cursor)
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
                frames, cursor = runtime.wire.event_stream_batch(session_id, cursor)
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
        """Verbatim bidirectional ACP frame relay for one owned channel.

        The Server never parses a frame on this route: attach, relay bytes,
        detach. A client disconnecting is not a release - the channel, its
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
        await websocket.accept()
        inbox: asyncio.Queue = asyncio.Queue()

        def _sink(item):
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
                    transport.send_line(text)
                except Exception:  # noqa: BLE001 - the Agent is gone; answer nothing for it
                    break
        except WebSocketDisconnect:
            pass
        finally:
            connection.detach(loop, _sink)
            pump.cancel()

    @app.post("/api/v1/turns/{turn_id}/cancel", dependencies=protected)
    def cancel(turn_id: str, response: Response, key: str = Depends(idempotency_key)):
        status, result = runtime.service.cancel_turn(turn_id, key)
        response.status_code = status
        return result

    return app


def _error(code: str, message: str, status: int, retryable: bool, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable, "request_id": request_id}},
    )
