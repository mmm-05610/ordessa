"""The transitional core adapter — one plugin, visibly marked, temporarily big.

`ordessa.transition-core` registers every business wire method that has not
yet moved behind the plugin boundary. It is the bridge that keeps wire/1
stable while domains migrate one batch at a time; it is NOT a second plugin
host and owns no table of its own — every row here becomes one atomic
descriptor on the plugin host's method registry, exactly like any other
plugin's methods. The declaration lives in `wire.handlers`
(`_PARAM_SHAPES` + `_ADAPTER_METHODS`); the gates in
`test_hello_capability_sync_097.py` compare the declaration against the
registry so a row that never reached the registry stays visible.

Which domains still sit behind this adapter is recorded in
`docs/server-host-baseline.md` and restated in the batch report; each later
domain batch retires its slice from here.
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    ServerMethodDescriptor,
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from ordessa_server.wire.handlers import (
    _ADAPTER_METHODS,
    _EXECUTION_GATE_FAMILY,
    _PARAM_SHAPES,
    TRANSITIONAL_ADAPTER_ID,
)


class TransitionCorePlugin:
    """Registers the not-yet-migrated business methods of one WireService."""

    def __init__(self, wire: Any) -> None:
        self._wire = wire

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=TRANSITIONAL_ADAPTER_ID,
            display_name="Transitional core adapter (batch 1)",
            version="1",
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        wire = self._wire

        def execution_gate() -> "tuple[bool, str | None]":
            if wire.execution is None:
                return False, "EXECUTION_CAPABILITY_UNAVAILABLE"
            return True, None

        methods = []
        for method_id, attribute in _ADAPTER_METHODS.items():
            if method_id == "server.hello":
                # Host-owned discovery: registered by WireService itself at
                # construction, never re-registered by the adapter.
                continue
            required, optional = _PARAM_SHAPES[method_id]
            methods.append(ServerMethodDescriptor(
                method_id=method_id,
                required_params=frozenset(required),
                optional_params=frozenset(optional),
                handler=getattr(wire, attribute),
                owner=TRANSITIONAL_ADAPTER_ID,
                availability=execution_gate if method_id in _EXECUTION_GATE_FAMILY else None,
            ))
        return ServerPluginRegistration(
            methods=tuple(methods),
            disposal=lambda: None,
        )


def undeclared_adapter_methods() -> tuple[str, ...]:
    """Adapter rows whose shape has no declaration — a gate, not dead code.

    Both declaration tables must cover exactly the same method set; a row in
    one but not the other is exactly the "handler added, everything else
    forgotten" hole order 097 exists to catch.
    """
    shape_ids = frozenset(_PARAM_SHAPES) - {"server.hello"}
    adapter_ids = frozenset(_ADAPTER_METHODS) - {"server.hello"}
    return tuple(sorted(shape_ids ^ adapter_ids))
