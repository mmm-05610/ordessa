"""The wire/1 param-shape primitives that host and plugins share.

These are the validators several components need and none of them owns:
`_require`/`_bounded`/`_request_id` are used by the host's own dispatch wall and
`server.hello`, while `_bounded`/`_require`/`_version` are also used by three
plugins. Before T014-S2c they lived as private functions of
`ordessa_server.wire.handlers`, so every plugin importing them reached into host
internals (rule 3). Moving them into one *sibling plugin* would have been
worse — it would have made workspace and harness import `ordessa_server_compat`
— so they live here, in the contract package, and the host imports them too.

The refusal bytes are the contract: the frozen strings below (`"params is
missing …"`, `"… must be a bounded string"`, `"requestId must contain at least
8 characters"`, `"… must be a non-negative safe integer"`) and the
`INVALID_REQUEST` family are what clients branch on, which is why exactly one
implementation exists and
`packages/server-plugin-api/tests/test_wire_shape.py` pins each string.

Domain-shape validators (`assignments`, `models`, `overrides`, `positive`,
`slug`) are NOT here: the measured table in the lane report shows zero host use
and a single owning plugin, so they live in `ordessa_server_compat`, which is
the domain that raises them.
"""
from __future__ import annotations

from typing import Any, Mapping

from .wire_errors import WireError


def require(params: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in params]
    if missing:
        raise WireError("INVALID_REQUEST", f"params is missing {', '.join(missing)}")


def bounded(value: Any, name: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not (0 < len(value) <= limit):
        raise WireError("INVALID_REQUEST", f"{name} must be a bounded string")
    return value


def request_id(value: Any) -> str:
    result = bounded(value, "requestId")
    if len(result) < 8:
        raise WireError("INVALID_REQUEST", "requestId must contain at least 8 characters")
    return result


def version(value: Any, name: str = "expectedVersion") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 2**53 - 1):
        raise WireError("INVALID_REQUEST", f"{name} must be a non-negative safe integer")
    return value
