"""wire/1 host dispatch — the contract's edge.

The one dispatch table is the plugin host's method registry: every method's
shape, handler, availability and owner travel as one atomic descriptor
(`ordessa_server_plugin_api.ServerMethodDescriptor`), and `dispatch`/`hello` read
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
contract package (`ordessa_server_plugin_api.wire_shape`): plugins import them from
there, and so does this module — one implementation, so a frozen refusal
string can never drift between the host's wall and a plugin's handler. The
domain-shape validators that only the compatibility core raises
(`assignments`/`models`/`overrides`/`positive`/`slug`) left the host in
T014-S2c for `ordessa_server_compat.wire_validators`.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping
from collections.abc import Coroutine
from contextlib import nullcontext
from inspect import CORO_CLOSED, CORO_CREATED, getcoroutinestate, isawaitable, iscoroutine
from threading import Lock
from asyncio import CancelledError

from ordessa_interfaces.system_access.access_control.authentication import AccessError

from ordessa_server_plugin_api.internal_errors import ServerError
from .discovery import ALWAYS_PRESENT_EMPTY_LIST
from ordessa_interfaces.system_access.subscriptions.cursors import CursorCodec
from ordessa_interfaces.system_access.contracts.transport import WIRE_VERSION
from ordessa_server_plugin_api.wire_errors import WireError
from ordessa_server_plugin_api.wire_shape import (
    bounded as _bounded,
    request_id as _request_id,
    require as _require,
)



HOST_OWNER_ID = "server.host"


class _TrackedAwaitable(Coroutine):
    """A coroutine that keeps one wire dispatch in flight until it is closed.

    `dispatch()` is also a public synchronous entry point and may return an
    awaitable from a contextual owner. A plain async `finally` does not run
    when that coroutine is closed before its first send, so this small wrapper
    owns the release for completion, cancellation, and explicit close.
    `dispatch_async()` may defer release until its post-await wire wall ends.
    """

    def __init__(self, awaitable, release: Callable[[], None]) -> None:
        self._awaitable = awaitable

        async def await_result():
            return await awaitable

        self._coroutine = await_result()
        self._release = release
        self._released = False
        self._deferred = False
        self._release_guard = Lock()
        self._started = False
        self._protocol_completed = False
        self._abandoned = False
        self._done_callback_registered = False

    def defer_release(self) -> None:
        with self._release_guard:
            self._deferred = True

    def _owner_is_done(self) -> bool:
        if iscoroutine(self._awaitable):
            return self._awaitable.cr_frame is None
        done = getattr(self._awaitable, "done", None)
        if callable(done):
            try:
                return bool(done())
            except Exception:
                return False
        return self._protocol_completed

    def _release_if_finished(self) -> None:
        if not (self._protocol_completed or self._abandoned) or not self._owner_is_done():
            return
        if not self._started:
            self._coroutine.close()
        with self._release_guard:
            if self._released or self._deferred:
                return
            self._released = True
        self._release()

    def _owner_done_callback(self, _future=None) -> None:
        self._release_if_finished()

    def _watch_owner_completion(self) -> None:
        if self._done_callback_registered or self._owner_is_done():
            self._release_if_finished()
            return
        add_done_callback = getattr(self._awaitable, "add_done_callback", None)
        if callable(add_done_callback):
            self._done_callback_registered = True
            add_done_callback(self._owner_done_callback)

    def release_after_dispatch(self) -> None:
        """End the dispatcher hold only after owner work is demonstrably done."""
        with self._release_guard:
            self._deferred = False
        self._release_if_finished()
        if not self._released:
            self._watch_owner_completion()

    def refresh_completion(self) -> None:
        """Recheck owner state when the composition polls shutdown readiness."""
        self._release_if_finished()

    def __await__(self):
        return self

    def __iter__(self):
        return self

    def __next__(self):
        return self.send(None)

    def _discard_unstarted(self) -> None:
        """Dispose a never-driven wrapper without touching external Tasks."""
        self._abandoned = True
        if self._started:
            return
        if iscoroutine(self._awaitable):
            state = getcoroutinestate(self._awaitable)
            if state not in {CORO_CREATED, CORO_CLOSED}:
                self._coroutine.close()
                raise WireError(
                    "CAPABILITY_UNSUPPORTED",
                    "cannot discard an owner coroutine that has already started",
                    {"internalCode": "OWNER_COROUTINE_ALREADY_STARTED", "retryable": True},
                )
        self._coroutine.close()
        if iscoroutine(self._awaitable):
            if getcoroutinestate(self._awaitable) == CORO_CREATED:
                self._awaitable.close()
        else:
            self._watch_owner_completion()
        self._release_if_finished()

    def send(self, value):
        self._started = True
        try:
            return self._coroutine.send(value)
        except StopIteration:
            self._protocol_completed = True
            self._release_if_finished()
            raise
        except BaseException:
            if self._owner_is_done():
                self._protocol_completed = True
            self._release_if_finished()
            raise

    def throw(self, typ, val=None, tb=None):
        cancel_type = typ if isinstance(typ, type) else type(typ)
        if (not self._started and isinstance(cancel_type, type)
                and issubclass(cancel_type, CancelledError)):
            self._discard_unstarted()
            error = typ if isinstance(typ, BaseException) else (val or typ())
            if tb is not None:
                raise error.with_traceback(tb)
            raise error
        self._started = True
        try:
            if val is None:
                return self._coroutine.throw(typ)
            if tb is None:
                return self._coroutine.throw(typ, val)
            return self._coroutine.throw(typ, val, tb)
        except StopIteration:
            self._protocol_completed = True
            self._release_if_finished()
            raise
        except BaseException:
            if self._owner_is_done():
                self._protocol_completed = True
            self._release_if_finished()
            raise

    def close(self):
        if self._released:
            return
        self._abandoned = True
        if self._owner_is_done():
            if not self._started:
                self._coroutine.close()
            self._release_if_finished()
            return
        if self._started:
            # Synchronous close cannot settle an async finally block. Keep the
            # original awaitable driveable and leave shutdown pending.
            raise RuntimeError("cannot synchronously close an active wire dispatch")
        self._discard_unstarted()


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
        identity_authority=None,
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
        #: 026 T006-02: the composed round's started state — a zero-arg
        #: callable the composition root binds once the runtime exists
        #: (`lambda: runtime.started`, read live per dispatch so stop() closes
        #: the gate again). None = no round is composed here (a `WireService`
        #: built standalone), and the dispatch wall applies no round gate — it
        #: cannot invent a lifecycle the composition does not have.
        self._round_state_resolver = None
        #: The composition's wire/1 error-family resolver (S2a-R): a
        #: `code -> family` callable built by the composition root over the
        #: declaring plugin host's own aggregate, handed over once here.
        #: None = the transport answers from the static host table only.
        self._error_family_resolver = error_family_resolver
        self._registry = method_registry
        # Admission and drain state belongs to this transport instance. The
        # lock makes close-vs-dispatch atomic across sync threads and async
        # callers without blocking the event loop while work is in flight.
        self._dispatch_state_lock = Lock()
        self._dispatch_admission_open = True
        self._active_dispatches = 0
        self._tracked_dispatches: set[_TrackedAwaitable] = set()
        self.identity_authority = identity_authority
        #: The host's stream-route registry (ACP today): resolution of owned
        #: endpoints only — origin/bearer checks and close semantics stay in
        #: the host transport, which is where the wire reads it from.
        self.stream_routes = stream_routes
        # Generic transport safety wall, shared with the selected ACP owner
        # through a declared host port. No verifier is composed by default.
        self.acp_admission_gate = acp_admission_gate
        # The host-owned discovery method; every other row arrives through a
        # plugin's registration (order preserved by the product composition).
        from ordessa_server_plugin_api import ServerMethodDescriptor

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
        from ordessa_server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        owner = self._require_plugin_owner(method_id)
        self._registry.unregister(method_id, owner=owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=descriptor.required_params,
            optional_params=descriptor.optional_params, handler=handler,
            owner=owner, availability=descriptor.availability,
            contextual=descriptor.contextual,
        ))

    def amend_shape(self, method_id: str, *, required: "frozenset[str] | set[str]",
                    optional: "frozenset[str] | set[str]") -> None:
        """Re-declare one plugin-owned param shape on the live registry."""
        from ordessa_server_plugin_api import ServerMethodDescriptor

        descriptor = self._registry.lookup(method_id)
        owner = self._require_plugin_owner(method_id)
        self._registry.unregister(method_id, owner=owner)
        self._registry.register(ServerMethodDescriptor(
            method_id=method_id, required_params=frozenset(required),
            optional_params=frozenset(optional), handler=descriptor.handler,
            owner=owner, availability=descriptor.availability,
            contextual=descriptor.contextual,
        ))

    def bind_workspace_resolution(self, resolver: "Callable[[], Any] | None") -> None:
        """Bind how workspace facts are resolved (a zero-arg callable reading
        the plugin host live, or None to declare the domain absent)."""
        self._workspace_resolver = resolver

    def bind_round_state(self, resolver: "Callable[[], bool] | None") -> None:
        """Bind how the dispatch wall reads the round's started state (a
        zero-arg callable over the composed runtime's live `started` flag, or
        None to declare no round composed here)."""
        self._round_state_resolver = resolver

    def begin_shutdown(self) -> bool:
        """Close business dispatch admission and report whether it is idle.

        The method never waits. A false result means accepted dispatches are
        still active and the caller must keep shutdown pending.
        """
        with self._dispatch_state_lock:
            self._dispatch_admission_open = False
            tracked = tuple(self._tracked_dispatches)
        for dispatch in tracked:
            dispatch.refresh_completion()
        with self._dispatch_state_lock:
            return self._active_dispatches == 0

    def reopen_admission(self) -> bool:
        """Reopen business dispatch only when the previous round is idle."""
        with self._dispatch_state_lock:
            tracked = tuple(self._tracked_dispatches)
        for dispatch in tracked:
            dispatch.refresh_completion()
        with self._dispatch_state_lock:
            if self._active_dispatches:
                return False
            self._dispatch_admission_open = True
            return True

    def _admit_dispatch(self) -> None:
        with self._dispatch_state_lock:
            if not self._dispatch_admission_open:
                raise WireError(
                    "INVALID_REQUEST",
                    "this Server is closing and is not accepting business dispatches",
                    {"internalCode": "DISPATCH_ADMISSION_CLOSED", "retryable": True},
                )
            self._active_dispatches += 1

    def _release_dispatch(self) -> None:
        with self._dispatch_state_lock:
            if self._active_dispatches <= 0:
                raise RuntimeError("wire dispatch activity counter underflow")
            self._active_dispatches -= 1

    def _track_awaitable(self, awaitable) -> _TrackedAwaitable:
        tracked_ref: dict[str, _TrackedAwaitable] = {}

        def release() -> None:
            self._release_dispatch()
            with self._dispatch_state_lock:
                self._tracked_dispatches.discard(tracked_ref["value"])

        tracked = _TrackedAwaitable(awaitable, release)
        tracked_ref["value"] = tracked
        with self._dispatch_state_lock:
            self._tracked_dispatches.add(tracked)
        return tracked

    def _round_open(self) -> bool:
        """Whether the composed round is accepting dispatches.

        An unbound resolver means this transport has no round concept (no
        composition attached), so the gate is inert; a bound one is read LIVE
        per dispatch — start() opens the gate and stop() closes it again."""
        if self._round_state_resolver is None:
            return True
        return bool(self._round_state_resolver())

    @property
    def workspaces(self):
        """The Workspace plugin's live resolution port, or None when absent."""
        if self._workspace_resolver is None:
            return None
        return self._workspace_resolver()

    def dispatch(self, method: str, params: Mapping[str, Any], *, caller=None) -> Any:
        descriptor = self._registry.lookup(method)
        if descriptor is None:
            raise WireError("INVALID_REQUEST", f"{method} is not a wire/1 method")
        # 026 T006-02: the round gate. Activation populates this registry at
        # composition time, so a built-but-never-started runtime carries every
        # business row and would otherwise answer fabricated empty reads from
        # domains that have no live round behind them. A round that is not
        # started (never started, or stopped) therefore refuses every method
        # except the host's discovery face — `server.hello` is how a client
        # learns this Server exists at all — with an existing wire family and
        # the internal code in details, never a new top-level error face. The
        # gate sits AFTER the existence refusal on purpose: what is NOT
        # registered keeps its unknown-method answer (the stopped round's rows
        # are unregistered by shutdown, so a stopped round refuses exactly as
        # the pinned T006-05 tests expect), and what IS registered but has no
        # live round gets the round refusal below.
        if method != "server.hello" and not self._round_open():
            raise WireError(
                "INVALID_REQUEST",
                "this Server's round is not started; wire/1 methods answer only a started round",
                {"internalCode": "ROUND_NOT_STARTED", "retryable": True},
            )
        missing = descriptor.required_params - set(params)
        extra = set(params) - descriptor.required_params - descriptor.optional_params
        if missing or extra:
            reason = "missing " + ", ".join(sorted(missing)) if missing else (
                "unexpected " + ", ".join(sorted(extra))
            )
            raise WireError("INVALID_REQUEST", f"params shape is invalid: {reason}")
        if "requestId" in params:
            _request_id(params["requestId"])
        tracked = method != "server.hello"
        if tracked:
            self._admit_dispatch()
        try:
            if descriptor.contextual and (caller is None or self.identity_authority is None):
                raise WireError("AUTHENTICATION_REQUIRED", "An authenticated caller is required")
            # Legacy providers retain their original local principal and ACL.
            # New contextual owners receive the verified caller explicitly and
            # acquire their exact scope/capability guard before application IO.
            guard = (self.identity_authority.guard_legacy(caller)
                     if self.identity_authority is not None and not descriptor.contextual
                     else nullcontext())
            with guard:
                if descriptor.contextual:
                    self.identity_authority.verify(caller)
                    result = descriptor.handler(params, caller)
                else:
                    result = descriptor.handler(params)
                if isawaitable(result) and tracked:
                    result = self._track_awaitable(result)
                    tracked = False
                if isawaitable(result) and not descriptor.contextual:
                    # A legacy guard ends with this synchronous call. Never
                    # execute deferred legacy IO after its admission expired.
                    close = getattr(result, "close", None)
                    if close is not None:
                        close()
                    raise WireError("CAPABILITY_UNSUPPORTED", "Async methods require contextual admission")
                if not isawaitable(result) and self.acp_admission_gate is not None and self.stream_routes is not None:
                    self.acp_admission_gate.observe_wire_result(method, params, result, self.stream_routes)
                return result
        except WireError:
            # A typed refusal is the contract answering, not a crash: the wall
            # below must never re-project it onto `UNAVAILABLE`.
            raise
        except AccessError as exc:
            family = ("FORBIDDEN" if exc.code in {"ACCESS_DENIED", "LEGACY_IDENTITY_UNAVAILABLE", "INVALID_CAPABILITY"}
                      else "UNAUTHENTICATED")
            raise WireError(family, "Caller binding is not admitted",
                            {"internalCode": exc.code, "retryable": False}) from None
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
        finally:
            if tracked:
                self._release_dispatch()

    async def dispatch_async(self, method, params, *, caller=None):
        """Await contextual application calls; their owners hold scoped admission.

        Legacy synchronous dispatch remains the same registry/authority path.
        Exceptions after an await use the same no-leak transport error wall.
        """
        result = self.dispatch(method, params, caller=caller)
        if not isawaitable(result):
            return result
        tracked_result = result if isinstance(result, _TrackedAwaitable) else None
        if tracked_result is not None:
            tracked_result.defer_release()
        try:
            result = await result
            if self.acp_admission_gate is not None and self.stream_routes is not None:
                self.acp_admission_gate.observe_wire_result(method, params, result, self.stream_routes)
            return result
        except WireError:
            raise
        except AccessError as exc:
            family = "FORBIDDEN" if exc.code in {"ACCESS_DENIED", "LEGACY_IDENTITY_UNAVAILABLE", "INVALID_CAPABILITY"} else "UNAUTHENTICATED"
            raise WireError(family, "Caller binding is not admitted",
                {"internalCode": exc.code, "retryable": False}) from None
        except ServerError as exc:
            raise WireError.from_server_error(exc, self._error_family_resolver) from exc
        except Exception as exc:
            raise WireError("UNAVAILABLE", "this Server could not answer the request",
                {"internalCode": type(exc).__name__, "retryable": True}) from exc
        finally:
            if tracked_result is not None:
                tracked_result.release_after_dispatch()

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
