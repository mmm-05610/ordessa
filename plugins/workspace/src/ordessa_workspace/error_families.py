"""The wire/1 error families owned by the workspace domain (T014-S2a-R).

`ordessa.workspace` raises these internal ServerError codes from its own code
— the environment shape (`service.py::_validate_environment`, lines 101/103/
106/111/118/184), the connector-absence refusals (`service.py` 51/56/73/84/
116/182/201/211/214, raised when the composed connector is None), the local
path surface (`local_environment.py::_refuse`, lines 115-236) and the local
sandbox blocker (`local_environment.py` 104, 157) — so their `code -> family`
rows live here, next to the code that produces them, and reach the host's
wire/1 error surface as a `wire.error-families` contribution published by
this plugin (`plugin.py`). They are not copied into the host's `_BY_CODE`
table any more: a composition without this plugin answers these codes with
the documented fall-through (`UNAVAILABLE`), which is the honest typed
absence.

Ownership was decided by the RAISE site, not by who mentions the code.
T014-S2b moved the connector CONSTRUCTION out of the host
(`bootstrap/runtime.py::_builtin_connector` / `_builtin_ssh_connector` →
this plugin's `connectors.py`), and the two rows whose producer the
workspace now composes moved with it:

- `SSH_TARGET_INVALID` / `SSH_IDENTITY_INVALID` are raised by the SSH
  connector implementation (`apps/server/src/ordessa_server/connectors.py`
  351/358 and 238/241) that THIS plugin builds and binds (S2b). The
  pre-S2b note kept them host rows because the host itself composed the
  connector; with the composition here, the rows live here — and a
  composition without this plugin answers them through the documented
  fall-through, which is the honest statement of "no producer composed".
- `SSH_WORKER_*` / `SSH_UNREACHABLE` remain static rows: they name the
  remote WORKER's own failure vocabulary carried by the connector
  implementation the host still ships, not a workspace decision.

`WSL_CONNECTOR_UNAVAILABLE` / `SSH_CONNECTOR_UNAVAILABLE` are the reverse
shape: no host code raises them — the consumers of the connector ports do,
this plugin (service.py) primarily and the compatibility core's placement
(`server-compat/.../placement.py` 55/61) secondarily. Placement runs only
in compositions that contain this plugin (compat declares `requires=("
ordessa.workspace",)`), so the row published here answers every raise site
that exists today; if a future composition drops workspace while keeping
those compat paths, the fall-through is the honest answer, and co-publishing
from compat's own table would be the explicit fix.
"""
from __future__ import annotations

from types import MappingProxyType

#: The plugin's published mapping. The host's per-composition handler
#: stages/commits/rolls back this exact object: its identity is the
#: transaction token, so it must be a module-level singleton, never a fresh
#: copy per build (same shape as `error_families.py` in server-compat).
WORKSPACE_ERROR_FAMILIES = MappingProxyType({
    "ENVIRONMENT_INVALID": "INVALID_REQUEST",
    "LOCAL_PATH_INVALID": "INVALID_REQUEST",
    "LOCAL_PATH_NOT_DIRECTORY": "INVALID_REQUEST",
    "LOCAL_PATH_MISSING": "NOT_FOUND",
    "LOCAL_PATH_NOT_READABLE": "FORBIDDEN",
    "LOCAL_PATH_FORBIDDEN": "FORBIDDEN",
    "LOCAL_PATH_UNAVAILABLE": "UNAVAILABLE",
    "LOCAL_SANDBOX_UNAVAILABLE": "UNAVAILABLE",
    "WSL_CONNECTOR_UNAVAILABLE": "UNAVAILABLE",
    "SSH_CONNECTOR_UNAVAILABLE": "UNAVAILABLE",
    # T014-S2b: raised by the SSH connector this plugin now composes.
    "SSH_TARGET_INVALID": "INVALID_REQUEST",
    "SSH_IDENTITY_INVALID": "INVALID_REQUEST",
})
