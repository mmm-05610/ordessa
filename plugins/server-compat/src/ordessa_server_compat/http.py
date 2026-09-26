"""The compatibility core's REST surface, admitted through the host transport.

Moved verbatim from the host's `transport/http/app.py` (core-cleanup stage 3):
same paths, same request models, same status codes, same idempotency
discipline. The host owns the wall (bearer auth, loopback policy, error
sanitisation — `transport.http.admission`); these endpoints own the business
facts, answering from the services this plugin composed.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ordessa_server.errors import ServerError
from ordessa_server.transport.http.admission import idempotency_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CredentialImportRequest(StrictModel):
    kind: str = Field(min_length=1, max_length=32)
    source_path: str = Field(min_length=1, max_length=4096)
    confirm_source_path: str = Field(min_length=1, max_length=4096)


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


def compat_http_routes(
    *, service: Any, repository: Any, notifier: Any,
    delegation_service: Any, delegation_tokens: dict,
) -> "tuple[Any, ...]":
    """The compatibility core's HTTP route descriptors."""
    from server_plugin_api import HttpRouteDescriptor

    PLUGIN_ID = "ordessa.server-compat"

    def readiness():
        return service.readiness()

    def credentials():
        """Which credentials this Server can resolve (ids and kinds only)."""
        return {"items": service.list_credentials()}

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
        status, result = service.import_credential(
            kind=body.kind, source=body.source_path, key=key,
        )
        response.status_code = status
        return result

    def create_profile(body: ProfileRequest, response: Response,
                       key: str = Depends(idempotency_key)):
        status, result = service.create_profile(key, body.model_dump())
        response.status_code = status
        return result

    def list_profiles():
        return {"items": service.profiles.list()}

    def create_session(body: SessionRequest, response: Response,
                       key: str = Depends(idempotency_key)):
        status, result = service.create_session(key, body.model_dump())
        response.status_code = status
        return result

    def get_session(session_id: str):
        return repository.get_session(session_id)

    def create_turn(
        session_id: str, body: TurnRequest, response: Response,
        key: str = Depends(idempotency_key),
    ):
        status, result = service.create_turn(session_id, key, body.model_dump())
        response.status_code = status
        return result

    def events(session_id: str, after: int = Query(default=0, ge=0)):
        generation = notifier.generation()
        history = repository.list_events(session_id, after)

        def stream():
            cursor = after
            for item in history:
                payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {item['seq']}\nevent: {item['kind']}\ndata: {payload}\n\n"
                cursor = item["seq"]
            current_generation = generation
            while True:
                batch = repository.list_events(session_id, cursor)
                if batch:
                    for item in batch:
                        payload = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                        yield f"id: {item['seq']}\nevent: {item['kind']}\ndata: {payload}\n\n"
                        cursor = item["seq"]
                    current_generation = notifier.generation()
                    continue
                next_generation = notifier.wait_after(current_generation)
                if next_generation == current_generation:
                    yield ": keepalive\n\n"
                current_generation = next_generation

        return StreamingResponse(stream(), media_type="text/event-stream")

    def cancel(turn_id: str, response: Response, key: str = Depends(idempotency_key)):
        status, result = service.cancel_turn(turn_id, key)
        response.status_code = status
        return result

    # The delegation bridge (order 65 C): the bridge inside the sandbox is not
    # a bearer of the user's token; it carries an attempt-scoped token minted
    # when the parent turn was assembled, and this surface resolves it to that
    # one turn. Reads only the two delegation operations, loops back to the
    # same policy as every other route (the host's loopback middleware), and
    # answers nothing else. `authenticated=False` is that token admission,
    # declared explicitly.
    async def delegation(token: str, request: Request) -> JSONResponse:
        body = await request.json()
        grant = (delegation_tokens or {}).get(token)
        if grant is None:
            return JSONResponse({"error": "DELEGATION_TOKEN_UNKNOWN"}, status_code=404)
        op = body.get("op")
        if delegation_service is None:
            return JSONResponse({"error": "DELEGATION_UNAVAILABLE"}, status_code=503)
        try:
            if op == "list":
                payload = delegation_service.list_for(parent_profile_id=grant["profileId"])
                return JSONResponse({"result": payload})
            if op == "run":
                payload = delegation_service.run(
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

    return (
        HttpRouteDescriptor(path="/api/v1/readiness", methods=frozenset({"GET"}),
                            endpoint=readiness, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/credentials", methods=frozenset({"GET"}),
                            endpoint=credentials, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/credentials", methods=frozenset({"POST"}),
                            endpoint=import_credential, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/profiles", methods=frozenset({"POST"}),
                            endpoint=create_profile, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/profiles", methods=frozenset({"GET"}),
                            endpoint=list_profiles, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/sessions", methods=frozenset({"POST"}),
                            endpoint=create_session, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/sessions/{session_id}", methods=frozenset({"GET"}),
                            endpoint=get_session, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/sessions/{session_id}/turns",
                            methods=frozenset({"POST"}),
                            endpoint=create_turn, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/sessions/{session_id}/events",
                            methods=frozenset({"GET"}),
                            endpoint=events, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/api/v1/turns/{turn_id}/cancel",
                            methods=frozenset({"POST"}),
                            endpoint=cancel, owner=PLUGIN_ID),
        HttpRouteDescriptor(path="/internal/delegation/{token}",
                            methods=frozenset({"POST"}),
                            endpoint=delegation, owner=PLUGIN_ID,
                            authenticated=False),
    )
