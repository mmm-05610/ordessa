"""The Server's internal error type — a re-export of the published contract.

T014-S2c moved the definition to `server_plugin_api.internal_errors` because
every plugin raises `ServerError` and importing it from here was a host-internals
reach (AGENTS rule 3). The host keeps its own neutral use cases, so it imports
the published implementation and re-exports it: one class object, one
implementation, and `isinstance` keeps working across host and plugin code
without either side importing the other.

Nothing may be defined in this module again; new shared vocabulary goes to the
contract package.
"""
from __future__ import annotations

from server_plugin_api.internal_errors import ServerError, unavailable

__all__ = ["ServerError", "unavailable"]
