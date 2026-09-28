"""wire/1 host dispatch — the contract's edge.

The one dispatch table is the plugin host's method registry: every method's
shape, handler, availability and owner travel as one atomic descriptor
(`server_plugin_api.ServerMethodDescriptor`), and `dispatch`/`hello` read
only from this registry — there is no second method table anywhere in the
Server. The host owns exactly one row's logic: the `server.hello` envelope
(`serverId`, `protocolVersion`, `capabilities`, `auth`) and the aggregation of
the discovery facets the composed domains publish through the
`wire.discovery-facets` point — since T014-S3 the host builds no facet entry
and validates no domain fact, it only decides where they go in the answer —
plus the dispatch wall (shape check, requestId check, error families). Every
business method arrives through a plugin — see
`ordessa_server_compat.core_wire` for the compatibility core's frozen list.

The param-shape helpers are the wire's shared vocabulary and they live in the
contract package (`server_plugin_api.wire_shape`): plugins import them from
there, and so does this module — one implementation, so a frozen refusal
string can never drift between the host's wall and a plugin's handler. The
domain-shape validators that only the compatibility core raises
(`assignments`/`models`/`overrides`/`positive`/`slug`) left the host in
T014-S2c for `ordessa_server_compat.wire_validators`.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_server.errors import ServerError
from ordessa_server.wire.discovery import ALWAYS_PRESENT_EMPTY_LIST
from ordessa_server.wire.envelope import CursorCodec
from ordessa_server.wire.errors import WireError
from server_plugin_api.wire_shape import (
    bounded as _bounded,
    request_id as _request_id,
    require as _require,
)

WIRE_VERSION = "wire/1"


HOST_OWNER_ID = "server.host"


class WireService:
    """Dispatches wire/1 methods through the plugin host's method registry."""

    def __init__(
        self, *, server_id_provider: Callable[[], str], cursor_secret: bytes,
        method_registry=None,
        stream_routes=None,
        token_required: bool = True,
        discovery_facets_resolver: (
            "Callable[[], Mapping[str, Callable[[], Any]]] | None") = None,
        error_family_resolver: "Callable[[str], str] | None" = None,
        acp_admission_gate=None,
    ) -> None:
        self._server_id_provider = server_id_provider
        #: The composition's `server.hello` discovery facets (T014-S3): a
        #: `facet name -> projector` mapping built by the composition root over
        #: the declaring plugin host's own aggregate, handed over once here —
        #: the same per-composition accessor shape as
        #: `_error_family_resolver`, never module state. Which harnesses this
        #: Server can run, and whose native identity it runs as, are facts the
        #: domain that owns them projects; this transport only aggregates.
        #: None = no domain speaks here at all, and hello answers the contract's
        #: empty defaults.
        self._discovery_facets_resolver = discovery_facets_resolver
        #: Workspace facts reach the remaining compatibility domains only
        #: through a resolver the composition binds after activation; it reads
        #: the plugin host live, so unloading the Workspace plugin unbinds the
        #: port too. None resolver = the domain can never be present.
        self._workspace_resolver = None
        #: The composition's wire/1 error-family resolver (S2a-R): a
        #: `code -> family` callable built by the composition root over the
        #: declaring plugin host's own aggregate, handed over once here.
        #: None = the transport answers from the static host table only.
        self._error_family_resolver = error_family_resolver
        self._registry = method_registry
        #: The host's stream-route registry (ACP today): resolution of owned
        #: endpoints only — origin/bearer checks and close semantics stay in
        #: the host transport, which is where the wire reads it from.
        self.stream_routes = stream_routes
        # Generic transport safety wall, shared with the selected ACP owner
        # through a declared host port. No verifier is composed by default.
        self.acp_admission_gate = acp_admission_gate
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
            result = descriptor.handler(params)
            if self.acp_admission_gate is not None and self.stream_routes is not None:
                self.acp_admission_gate.observe_wire_result(method, params, result, self.stream_routes)
            return result
        except WireError:
            # A typed refusal is the contract answering, not a crash: the wall
            # below must never re-project it onto `UNAVAILABLE`.
            raise
        except ServerError as exc:
            # The composition's resolver (bound at construction, never a
            # process-global table) answers contributed codes for THIS
            # transport's composition; without one the static host table
            # and the documented fall-through answer (T014-S2a-R).
            raise WireError.from_server_error(exc, self._error_family_resolver) from exc
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
        result: dict[str, Any] = {
            "serverId": self._server_id_provider(),
            "protocolVersion": WIRE_VERSION,
            "capabilities": capabilities,
            "auth": auth,
        }
        # The discovery facets are what the composed domains have to say about
        # this Server — which harnesses it can run, whose native identity it
        # runs as — and the host neither builds nor interprets a single entry
        # of them. Each facet arrives through the open `wire.discovery-facets`
        # point (published by the domain that can answer it, read live per
        # hello because the fact is live), and the host keeps only what a
        # protocol must keep: the envelope above, this aggregation, and its
        # deterministic order (publish order, so a client that cached the
        # answer sees the same bytes it cached).
        #
        # A projector that answers `None` published no fact, so the key is
        # absent rather than empty — `nativeExecution` on a non-native
        # deployment is typed absence, not a refusal and not a lie. The
        # always-present members are wire/1's contract, not domain vocabulary:
        # a composition with no harness plugin answers `harnesses: []` because
        # the member exists in the schema and has nothing in it.
        facets = (self._discovery_facets_resolver()
                  if self._discovery_facets_resolver is not None else {})
        for facet, project in facets.items():
            value = project()
            if value is not None:
                result[facet] = value
        for facet in ALWAYS_PRESENT_EMPTY_LIST:
            result.setdefault(facet, [])
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
