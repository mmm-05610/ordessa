"""wire/1 host dispatch — the contract's edge.

The one dispatch table is the plugin host's method registry: every method's
shape, handler, availability and owner travel as one atomic descriptor
(`server_plugin_api.ServerMethodDescriptor`), and `dispatch`/`hello` read
only from this registry — there is no second method table anywhere in the
Server. The host owns exactly one row's logic: the `server.hello` discovery
surface, plus the dispatch wall (shape check, requestId check, error
families). Every business method arrives through a plugin — see
`ordessa_server_compat.core_wire` for the compatibility core's frozen list.

The param-shape helpers below are the wire's shared vocabulary; plugins
import them rather than re-implementing them.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_server.errors import ServerError
from ordessa_server.records import reject_sensitive_keys
from ordessa_server.wire.envelope import CursorCodec
from ordessa_server.wire.errors import WireError

WIRE_VERSION = "wire/1"


def _require(params: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in params]
    if missing:
        raise WireError("INVALID_REQUEST", f"params is missing {', '.join(missing)}")


def _slug(value: Any, name: str) -> str:
    """A lowercase slug: the asset id every store and binding shares."""
    import re as _re

    if not isinstance(value, str) or _re.match(r"[a-z0-9][a-z0-9._-]{0,63}\Z", value) is None:
        raise WireError("INVALID_REQUEST", f"{name} must be a lowercase slug")
    return value


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WireError("INVALID_REQUEST", f"{name} must be a positive integer")
    return value


def _bounded(value: Any, name: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not (0 < len(value) <= limit):
        raise WireError("INVALID_REQUEST", f"{name} must be a bounded string")
    return value


def _request_id(value: Any) -> str:
    result = _bounded(value, "requestId")
    if len(result) < 8:
        raise WireError("INVALID_REQUEST", "requestId must contain at least 8 characters")
    return result


def _version(value: Any, name: str = "expectedVersion") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 2**53 - 1):
        raise WireError("INVALID_REQUEST", f"{name} must be a non-negative safe integer")
    return value


def _overrides(params: Mapping[str, Any]) -> list[dict[str, Any]] | None:
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


def _assignments(value: Any, name: str) -> list[dict[str, Any]]:
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


def _models(value: Any) -> list[dict[str, Any]]:
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


HOST_OWNER_ID = "server.host"


class WireService:
    """Dispatches wire/1 methods through the plugin host's method registry."""

    def __init__(
        self, *, server_id_provider: Callable[[], str], cursor_secret: bytes,
        method_registry=None,
        stream_routes=None,
        token_required: bool = True,
        harness_resolver: "Callable[[], Any | None] | None" = None,
    ) -> None:
        self._server_id_provider = server_id_provider
        #: The native identity facts a native composition publishes through
        #: `server.hello`; the closure itself stays composition-owned.
        self.native_execution_provider = None
        #: The live harness directory (a composition fact hello publishes),
        #: or None on a bare host — which answers an empty family list.
        self._harness_resolver = harness_resolver
        #: Workspace facts reach the remaining compatibility domains only
        #: through a resolver the composition binds after activation; it reads
        #: the plugin host live, so unloading the Workspace plugin unbinds the
        #: port too. None resolver = the domain can never be present.
        self._workspace_resolver = None
        self._registry = method_registry
        #: The host's stream-route registry (ACP today): resolution of owned
        #: endpoints only — origin/bearer checks and close semantics stay in
        #: the host transport, which is where the wire reads it from.
        self.stream_routes = stream_routes
        # The host-owned discovery method; every other row arrives through a
        # plugin's registration (order preserved by the product composition).
        from server_plugin_api import ServerMethodDescriptor

        self._registry.register(ServerMethodDescriptor(
            method_id="server.hello",
            required_params=frozenset({"clientVersions", "clientPresentationSupports"}),
            optional_params=frozenset(),
            handler=self.hello, owner=HOST_OWNER_ID,
        ))
        self.codec = CursorCodec(cursor_secret)
        self.token_required = token_required

    # -- the one dispatch table: registry views and lifecycle primitives ----

    @property
    def _handlers(self) -> "dict[str, Callable[[Mapping[str, Any]], Any]]":
        """The registry's `{method_id: handler}` view, in registry order.

        Reading is the only thing this offers: the live table is the registry,
        and mutating it goes through `retire`/`replace_handler`/`amend_shape`
        (or a plugin's own unload), never by editing a copy.
        """
        return self._registry.handler_view()

    def _require_plugin_owner(self, method_id: str) -> str:
        descriptor = self._registry.lookup(method_id)
        if descriptor is None or descriptor.owner == HOST_OWNER_ID:
            raise WireError("INVALID_REQUEST", f"{method_id} is not a plugin method")
        return descriptor.owner

    def retire(self, method_id: str) -> None:
        """Remove one plugin-owned method from the live table.

        This is the plugin-unload primitive applied to a single row; the
        order-097 counter-examples use it to prove the table is live.
        """
        owner = self._require_plugin_owner(method_id)
        self._registry.unregister(method_id, owner=owner)

    def replace_handler(self, method_id: str, handler: Callable) -> None:
        """Rebind one plugin-owned method on the live registry."""
        from server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        owner = self._require_plugin_owner(method_id)
        self._registry.unregister(method_id, owner=owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=descriptor.required_params,
            optional_params=descriptor.optional_params, handler=handler,
            owner=owner, availability=descriptor.availability,
        ))

    def amend_shape(self, method_id: str, *, required: "frozenset[str] | set[str]",
                    optional: "frozenset[str] | set[str]") -> None:
        """Re-declare one plugin-owned param shape on the live registry."""
        from server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        owner = self._require_plugin_owner(method_id)
        self._registry.unregister(method_id, owner=owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=frozenset(required),
            optional_params=frozenset(optional), handler=descriptor.handler,
            owner=owner, availability=descriptor.availability,
        ))

    def bind_workspace_resolution(self, resolver: "Callable[[], Any] | None") -> None:
        """Bind how workspace facts are resolved (a zero-arg callable reading
        the plugin host live, or None to declare the domain absent)."""
        self._workspace_resolver = resolver

    @property
    def workspaces(self):
        """The Workspace plugin's live resolution port, or None when absent."""
        if self._workspace_resolver is None:
            return None
        return self._workspace_resolver()

    def dispatch(self, method: str, params: Mapping[str, Any]) -> Any:
        descriptor = self._registry.lookup(method)
        if descriptor is None:
            raise WireError("INVALID_REQUEST", f"{method} is not a wire/1 method")
        missing = descriptor.required_params - set(params)
        extra = set(params) - descriptor.required_params - descriptor.optional_params
        if missing or extra:
            reason = "missing " + ", ".join(sorted(missing)) if missing else (
                "unexpected " + ", ".join(sorted(extra))
            )
            raise WireError("INVALID_REQUEST", f"params shape is invalid: {reason}")
        if "requestId" in params:
            _request_id(params["requestId"])
        try:
            return descriptor.handler(params)
        except WireError:
            # A typed refusal is the contract answering, not a crash: the wall
            # below must never re-project it onto `UNAVAILABLE`.
            raise
        except ServerError as exc:
            raise WireError.from_server_error(exc) from exc
        except Exception as exc:  # noqa: BLE001 - the wire contract, not the caller's convenience
            # The last wall of the error family (order 115): anything else that
            # escapes a handler still leaves this Server as a JSON-RPC error
            # object. The exception's *text* never goes out — it can name a host
            # path or a credential locator — only its type, as `internalCode`.
            raise WireError(
                "UNAVAILABLE", "this Server could not answer the request",
                {"internalCode": type(exc).__name__, "retryable": True},
            ) from exc

    # -- discovery ---------------------------------------------------------

    def hello(self, params: Mapping[str, Any]) -> dict[str, Any]:
        _require(params, "clientVersions", "clientPresentationSupports")
        versions = params["clientVersions"]
        presentations = params["clientPresentationSupports"]
        if (not isinstance(versions, list) or not versions
                or any(not isinstance(item, str) for item in versions)
                or not isinstance(presentations, list)
                or any(not isinstance(item, str) for item in presentations)):
            raise WireError("INVALID_REQUEST", "clientVersions must be a non-empty list")
        capabilities = []
        # The table is the plugin host's method registry: a method no plugin
        # registered does not exist here, and one that exists must never go
        # undeclared (a hand-maintained list had fallen 37 methods behind).
        # Iteration order is registration order — host, then each plugin in
        # activation order — so the list stays deterministic for a client that
        # caches it. `server.hello` declares itself - the discovery entry
        # point that said "I do not exist" would be the one lie here.
        for item in self._registry.descriptors():
            supported, reason = (
                item.availability() if item.availability is not None else (True, None))
            entry: dict[str, Any] = {"id": item.method_id, "supported": supported}
            if not supported:
                entry["reason"] = reason
            capabilities.append(entry)
        auth = {"required": True, "schemes": ["session_token"]} if self.token_required else {"required": False}
        harnesses = []
        # The family directory is a deployment fact - which harnesses this Server
        # can run - so it comes from the compatibility core's registry, never
        # from the records: a fresh deployment has no records, and deriving the
        # list from them was what left a client with nothing to choose. The
        # resolver reads the plugin host live; a bare host has no directory and
        # answers an empty list. `registered()` is already sorted by id, so this
        # is the registry's own order rather than a second sort that could later
        # disagree with it. Only what a family *declares* is published, and a
        # declaration that is absent stays absent.
        directory = self._harness_resolver() if self._harness_resolver else None
        for harness_id in (directory.registered() if directory is not None else ()):
            descriptor = directory.get(harness_id)
            entry: dict[str, Any] = {"id": harness_id}
            if descriptor.credential_kind is not None:
                entry["credentialKind"] = descriptor.credential_kind
            if descriptor.model_control_id is not None:
                entry["modelControlId"] = descriptor.model_control_id
            harnesses.append(entry)
        result = {
            "serverId": self._server_id_provider(),
            "protocolVersion": WIRE_VERSION,
            "capabilities": capabilities,
            "auth": auth,
            "harnesses": harnesses,
        }
        if self.native_execution_provider is not None:
            native = self.native_execution_provider()
            if (not isinstance(native, Mapping) or native.get("mode") != "native"
                    or directory is None
                    or native.get("harness") not in directory.registered()
                    or not isinstance(native.get("profileId"), str) or not native["profileId"]):
                raise WireError("SERVER_NATIVE_IDENTITY_INVALID", "native execution identity is unavailable")
            result["nativeExecution"] = dict(native)
        return result

    def _capability(self, capability_id: str) -> tuple[bool, str | None]:
        """Support state for one id, read from its registered descriptor.

        So this answers two questions and no third: does the method exist (the
        registry, the only thing that can say no to a call), and does its
        availability predicate hold. Whether a call would then *succeed* is a
        third question these rules do not ask - a family with no blocker rule
        says `true` even when its call path is broken, which is why an
        unwritten rule is a gap to file, not something to guess here. An id
        that is not registered at all is an existence refusal at dispatch,
        never a support claim.
        """
        item = self._registry.lookup(capability_id)
        if item is None:
            return False, "UNKNOWN_METHOD"
        if item.availability is not None:
            return item.availability()
        return True, None
