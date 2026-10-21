"""wire/1 envelope encoding and opaque cursor codec.

Envelope shape is fixed by the contract candidate: JSON-RPC 2.0 shaped
requests with `method` matched against the registered method table, and
responses that carry exactly one of `result` or `error`.

Cursors are opaque to the client. Encoding is versioned so a cursor minted by a
different server generation can be recognised and answered with
`resync_required` rather than silently misread.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from ordessa_server_plugin_api.wire_errors import WireError


METHOD_PATTERN = re.compile(r"^[a-z][a-zA-Z0-9_]*(\.[a-z][a-zA-Z0-9_]*)+$")


class WireRequestError(WireError):
    pass


def decode_request(body: Any) -> tuple[Any, str, Mapping[str, Any]]:
    """Validate one wire request; returns (id, method, params)."""
    if not isinstance(body, Mapping):
        raise WireRequestError("INVALID_REQUEST", "Request must be a JSON object")
    if body.get("jsonrpc") != "2.0":
        raise WireRequestError("INVALID_REQUEST", "jsonrpc must be exactly '2.0'")
    if "id" not in body or not isinstance(body["id"], (str, int, float)) or isinstance(body["id"], bool):
        raise WireRequestError("INVALID_REQUEST", "id must be a string or number")
    method = body.get("method")
    if not isinstance(method, str) or not METHOD_PATTERN.match(method):
        raise WireRequestError("INVALID_REQUEST", "method is not a wire/1 method name")
    params = body.get("params", {})
    if not isinstance(params, Mapping):
        raise WireRequestError("INVALID_REQUEST", "params must be an object")
    if set(body) - {"jsonrpc", "id", "method", "params"}:
        raise WireRequestError("INVALID_REQUEST", "Request carries unknown members")
    return body["id"], method, params


def encode_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def encode_error(request_id: Any, error: WireError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_body()}




def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
