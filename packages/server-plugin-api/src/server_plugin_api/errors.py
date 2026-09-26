"""Typed plugin failures. A host rejects startup with these, never with prose."""
from __future__ import annotations


class ServerPluginError(RuntimeError):
    """Base class for every plugin-boundary refusal."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class InvalidDeclarationError(ServerPluginError):
    """A descriptor violates the contract's shape rules."""

    def __init__(self, message: str) -> None:
        super().__init__("PLUGIN_DECLARATION_INVALID", message)


class DuplicateMethodError(ServerPluginError):
    """Two plugins, or two registrations, claim the same wire method id."""

    def __init__(self, method_id: str, first_owner: str, second_owner: str) -> None:
        super().__init__(
            "PLUGIN_METHOD_DUPLICATE",
            f"method {method_id} is already owned by {first_owner!r}"
            f" (refused re-registration by {second_owner!r})",
        )
        self.method_id = method_id


class DuplicatePluginError(ServerPluginError):
    def __init__(self, plugin_id: str) -> None:
        super().__init__("PLUGIN_ID_DUPLICATE", f"plugin {plugin_id!r} is already active")
        self.plugin_id = plugin_id


class DuplicateStreamRouteError(ServerPluginError):
    def __init__(self, route_id: str, first_owner: str, second_owner: str) -> None:
        super().__init__(
            "PLUGIN_STREAM_ROUTE_DUPLICATE",
            f"stream route {route_id} is already owned by {first_owner!r}"
            f" (refused re-registration by {second_owner!r})",
        )
        self.route_id = route_id


class DependencyError(ServerPluginError):
    """A declared `requires` names no activatable plugin."""

    def __init__(self, plugin_id: str, missing: tuple[str, ...]) -> None:
        super().__init__(
            "PLUGIN_DEPENDENCY_MISSING",
            f"plugin {plugin_id!r} requires {', '.join(sorted(missing))}"
            " which no active or requested plugin provides",
        )
        self.plugin_id = plugin_id


class CyclicDependencyError(ServerPluginError):
    def __init__(self, cycle: tuple[str, ...]) -> None:
        super().__init__(
            "PLUGIN_DEPENDENCY_CYCLE",
            "plugin requires form a cycle: " + " -> ".join(cycle),
        )
        self.cycle = cycle
