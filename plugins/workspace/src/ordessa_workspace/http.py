"""The Workspace domain's REST surface, admitted through the host transport.

Moved verbatim from the host's `transport/http/app.py` (core-cleanup stage 3):
same paths, same request models, same status codes, same idempotency
discipline. The host owns the wall (bearer auth, loopback policy, error
sanitisation — `transport.http.admission`); these endpoints own the domain
facts, answering from the plugin's own `WorkspaceRecords`/`WorkspaceService`
—the same instance the product facade composes, so there is no second
workspace authority.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from server_plugin_api import ServerError
from ordessa_server.transport.http.admission import idempotency_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BrowseRequest(StrictModel):
    probe_id: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=4096)


class WorkspaceRequest(BrowseRequest):
    pass


class ProbeRequest(StrictModel):
    kind: str
    distribution: str = Field(min_length=1, max_length=128)
    user: str | None = Field(default=None, min_length=1, max_length=128)


def workspace_http_routes(
    records: Any, service: Any,
) -> "tuple[Any, ...]":
    """The plugin's HTTP route descriptors, closed over its own objects."""
    from server_plugin_api import HttpRouteDescriptor

    PLUGIN_ID = "ordessa.workspace"

    def create_workspace(body: WorkspaceRequest, response: Response,
                         key: str = Depends(idempotency_key)):
        status, result = service.create(key, body.model_dump())
        response.status_code = status
        return result

    def list_workspaces():
        return {"items": records.list()}

    def probe(body: ProbeRequest, response: Response,
              key: str = Depends(idempotency_key)):
        if body.kind != "wsl":
            raise ServerError("CONNECTION_KIND_UNSUPPORTED",
                              "Only WSL connections are supported", status=422)
        status, result = service.probe(key, body.distribution, body.user)
        response.status_code = status
        return result

    def browse(body: BrowseRequest, response: Response,
               key: str = Depends(idempotency_key)):
        status, result = service.browse(key, body.probe_id, body.path)
        response.status_code = status
        return result

    def distributions():
        return {"items": service.distributions()}

    return (
        HttpRouteDescriptor(
            path="/api/v1/workspaces", methods=frozenset({"POST"}),
            endpoint=create_workspace, owner=PLUGIN_ID,
        ),
        HttpRouteDescriptor(
            path="/api/v1/workspaces", methods=frozenset({"GET"}),
            endpoint=list_workspaces, owner=PLUGIN_ID,
        ),
        HttpRouteDescriptor(
            path="/api/v1/connections/probe", methods=frozenset({"POST"}),
            endpoint=probe, owner=PLUGIN_ID,
        ),
        HttpRouteDescriptor(
            path="/api/v1/connections/browse", methods=frozenset({"POST"}),
            endpoint=browse, owner=PLUGIN_ID,
        ),
        HttpRouteDescriptor(
            path="/api/v1/wsl/distributions", methods=frozenset({"GET"}),
            endpoint=distributions, owner=PLUGIN_ID,
        ),
    )
