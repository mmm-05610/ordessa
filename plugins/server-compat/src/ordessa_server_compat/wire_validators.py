"""The compatibility core's own wire/1 param-shape validators.

T014-S2c moved these five out of `ordessa_server.wire.handlers`. The measured
symbol table (`specs/010-platform-core/reports/B.md`, §S2c) is the reason:
`assignments`, `models`, `overrides`, `positive` and `slug` had **zero** call
sites inside the host and every one of their callers sat in this plugin. Host
code that exists only so a plugin can import it is the exact shape FR-006 asks
the host to stop carrying.

The truly shared primitives (`require`, `bounded`, `request_id`, `version`) did
NOT come here — three plugins use them, so they live in the published contract
package (`server_plugin_api.wire_shape`), which the host imports too. That is
the difference between moving business vocabulary to the domain that owns it
and swapping one rule-3 breach for a worse one (plugins importing a sibling
plugin's internals).

Frozen refusal bytes: `"models must be a list"`, `"each model has an invalid
shape"`, `"model availability is invalid"`, `"unavailableReason must be a string
or null"`, `"overrides must be a list of control assignments"`, `"each override
needs controlId and value"`, `"… must be a positive integer"`, `"… must be a
lowercase slug"`, `"… must be a list of control assignments"`, `"each … item
needs controlId and value"` — all `INVALID_REQUEST`, all unchanged by the move
and pinned by `apps/server/tests/test_asset_surface_refusals_147.py` and the
117/129/135-era gates that drive them over the real wire.
"""
from __future__ import annotations

import re as _re
from typing import Any, Mapping

from server_plugin_api import reject_sensitive_keys
from server_plugin_api.wire_errors import WireError
from server_plugin_api.wire_shape import bounded as _bounded


def slug(value: Any, name: str) -> str:
    """A lowercase slug: the asset id every store and binding shares."""
    if not isinstance(value, str) or _re.match(r"[a-z0-9][a-z0-9._-]{0,63}\Z", value) is None:
        raise WireError("INVALID_REQUEST", f"{name} must be a lowercase slug")
    return value


def positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WireError("INVALID_REQUEST", f"{name} must be a positive integer")
    return value


def overrides(params: Mapping[str, Any]) -> "list[dict[str, Any]] | None":
    value = params.get("overrides")
    if value is None:
        return None
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", "overrides must be a list of control assignments")
    for item in value:
        if (not isinstance(item, Mapping) or set(item) != {"controlId", "value"}
                or not isinstance(item["controlId"], str)):
            raise WireError("INVALID_REQUEST", "each override needs controlId and value")
    reject_sensitive_keys(value)
    reject_sensitive_keys({item["controlId"]: item["value"] for item in value})
    return [dict(item) for item in value]


def assignments(value: Any, name: str) -> "list[dict[str, Any]]":
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", f"{name} must be a list of control assignments")
    result = []
    for item in value:
        if (not isinstance(item, Mapping) or set(item) != {"controlId", "value"}
                or not isinstance(item["controlId"], str) or not item["controlId"]):
            raise WireError("INVALID_REQUEST", f"each {name} item needs controlId and value")
        result.append(dict(item))
    reject_sensitive_keys(result)
    reject_sensitive_keys({item["controlId"]: item["value"] for item in result})
    return result


def models(value: Any) -> "list[dict[str, Any]]":
    if not isinstance(value, list):
        raise WireError("INVALID_REQUEST", "models must be a list")
    result = []
    allowed = {"modelId", "displayName", "availability", "unavailableReason"}
    for item in value:
        if not isinstance(item, Mapping) or set(item) != allowed:
            raise WireError("INVALID_REQUEST", "each model has an invalid shape")
        availability = item["availability"]
        reason = item["unavailableReason"]
        if availability not in {"unknown", "available", "unavailable"}:
            raise WireError("INVALID_REQUEST", "model availability is invalid")
        if reason is not None and not isinstance(reason, str):
            raise WireError("INVALID_REQUEST", "unavailableReason must be a string or null")
        result.append({
            "modelId": _bounded(item["modelId"], "modelId", 256),
            "displayName": _bounded(item["displayName"], "displayName", 256),
            "availability": availability, "unavailableReason": reason,
        })
    return result
