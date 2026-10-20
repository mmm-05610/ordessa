"""The Extensions domain's published wire-refusal seam.

Same discipline as the Skills family table: domain codes → the closed
families of `server_plugin_api.FAMILIES`, contributed through the open
`wire.error-families` point so a client sees a truthful family with the
domain code as `internalCode`, never the generic exception-class
fall-through.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any

from server_plugin_api import ServerError

#: The code -> family mapping contributed to
#: ``server_plugin_api.WIRE_ERROR_FAMILIES_POINT_ID``.
EXTENSIONS_ERROR_FAMILIES = MappingProxyType({
    # -- request shape/value refusals ------------------------------------
    "INVALID_REQUEST": "INVALID_REQUEST",
    "HOOK_ID_INVALID": "INVALID_REQUEST",
    "EVENT_UNEVIDENCED": "INVALID_REQUEST",
    "ACTION_KIND_INVALID": "INVALID_REQUEST",
    "ACTION_AMBIGUOUS": "INVALID_REQUEST",
    "COMMAND_REQUIRED": "INVALID_REQUEST",
    "COMMAND_ARG_INVALID": "INVALID_REQUEST",
    "COMMAND_TOO_LONG": "INVALID_REQUEST",
    "COMMAND_ARG_TOO_LONG": "INVALID_REQUEST",
    "HANDLER_REF_INVALID": "INVALID_REQUEST",
    "MATCHER_INVALID": "INVALID_REQUEST",
    "TIMEOUT_OUT_OF_BOUNDS": "INVALID_REQUEST",
    "RUN_ASYNC_INVALID": "INVALID_REQUEST",
    "PIN_INVALID": "INVALID_REQUEST",
    "CONTENT_HASH_INVALID": "INVALID_REQUEST",
    "SHELL_INJECTION_SURFACE": "INVALID_REQUEST",
    "APPROVER_REQUIRED": "INVALID_REQUEST",
    "SCOPE_INVALID": "INVALID_REQUEST",
    "SNAPSHOT_INVALID": "INVALID_REQUEST",
    "REVIVE_MISPLACED": "INVALID_REQUEST",
    "HOOK_ID_MISMATCH": "INVALID_REQUEST",
    "BLOCKING_CLAIM_REFUSED": "INVALID_REQUEST",
    # -- unknown ids in this data domain ---------------------------------
    "HOOK_UNKNOWN": "NOT_FOUND",
    # the modelled-but-unbuilt handler registry seam: retryable once the
    # registry lands (UNAVAILABLE, not a client error)
    "HANDLER_ROUTE_UNAVAILABLE": "UNAVAILABLE",
    # -- deterministic state conflicts ------------------------------------
    "NOT_APPROVED": "CONFLICT_REQUEST",
    "HOOK_REVOKED": "CONFLICT_REQUEST",
})

_STATUS_BY_FAMILY = {
    "INVALID_REQUEST": 400,
    "NOT_FOUND": 404,
    "CONFLICT_REQUEST": 409,
}


def to_server_error(exc: Any) -> ServerError:
    """Project one domain refusal (a `.code`-carrying ValueError) onto the
    published internal-error type. Unknown codes answer the UNAVAILABLE
    family (the host fall-through family) — an unmapped code must never
    masquerade as a client's request-shaped 400. A refusal with no code
    at all is a domain invariant break: UNAVAILABLE/503 with the
    family's own code, never a borrowed INVALID_REQUEST."""
    code = getattr(exc, "code", "")
    family = EXTENSIONS_ERROR_FAMILIES.get(code, "UNAVAILABLE")
    if family == "UNAVAILABLE":
        return ServerError(code or "UNAVAILABLE", str(exc), status=503,
                           retryable=True)
    return ServerError(code, str(exc),
                       status=_STATUS_BY_FAMILY.get(family, 400),
                       retryable=False)


__all__ = ["EXTENSIONS_ERROR_FAMILIES", "to_server_error"]
