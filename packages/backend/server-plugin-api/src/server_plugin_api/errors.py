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


class DuplicateHttpRouteError(ServerPluginError):
    """Two plugins claim the same HTTP path with overlapping methods; the host
    refuses instead of letting registration order pick a silent winner."""

    def __init__(self, path: str, methods: "tuple[str, ...]",
                 first_owner: str, second_owner: str) -> None:
        super().__init__(
            "PLUGIN_HTTP_ROUTE_DUPLICATE",
            f"http route {path} for {', '.join(sorted(methods))} is already "
            f"owned by {first_owner!r} (refused re-registration by {second_owner!r})",
        )
        self.path = path
        self.methods = tuple(methods)


class HttpRouteUnmountedError(ServerPluginError):
    """A plugin activated while a live transport holds a frozen route set
    declares HTTP routes that set never mounted. The transport is a snapshot
    at creation; a route that was not mounted cannot silently never serve.
    The activation refuses and rolls back — wire methods and HTTP routes
    succeed or refuse together."""

    def __init__(self, plugin_id: str, unmounted: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_HTTP_ROUTE_UNMOUNTED",
            f"plugin {plugin_id!r} declares HTTP routes the live transport "
            f"never mounted: {', '.join(sorted(unmounted))} — activate before "
            "the transport is created, or restart the transport",
        )
        self.plugin_id = plugin_id
        self.unmounted = tuple(unmounted)


class HttpRouteShapeChangedError(ServerPluginError):
    """A re-activated plugin's route matches a mounted route by path, methods
    and owner, but its mounted shape differs — the authentication flag or the
    endpoint's FastAPI-visible signature changed. The live transport would
    keep serving the new registration behind the wall and call shape that the
    first mount installed; the activation refuses instead."""

    def __init__(self, plugin_id: str, changed: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_HTTP_ROUTE_SHAPE_CHANGED",
            f"plugin {plugin_id!r} re-declares mounted routes with a changed "
            f"shape (auth flag or endpoint signature): {'; '.join(sorted(changed))}",
        )
        self.plugin_id = plugin_id
        self.changed = tuple(changed)


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


class DependentActiveError(ServerPluginError):
    """Unloading a plugin whose declared dependents are still active would
    orphan them; the host refuses and names them."""

    def __init__(self, plugin_id: str, dependents: tuple[str, ...]) -> None:
        super().__init__(
            "PLUGIN_DEPENDENT_ACTIVE",
            f"plugin {plugin_id!r} cannot be unloaded while its declared "
            f"dependent(s) are active: {', '.join(sorted(dependents))}",
        )
        self.plugin_id = plugin_id
        self.dependents = tuple(dependents)


class PortConflictError(ServerPluginError):
    """A provided port would silently override an existing binding in a
    consumer's activation context (a host facade or another dependency's
    port of the same name); the host refuses instead of shadowing."""

    def __init__(self, consumer_id: str, provider_id: str, port_name: str) -> None:
        super().__init__(
            "PLUGIN_PORT_CONFLICT",
            f"port {port_name!r} provided by {provider_id!r} collides with an "
            f"existing binding in {consumer_id!r}'s activation context",
        )
        self.consumer_id = consumer_id
        self.provider_id = provider_id
        self.port_name = port_name


class PluginCleanupError(ServerPluginError):
    """One plugin's disposal raised while the host was cleaning up.

    The original exception the disposal raised travels unmodified in `error`;
    the plugin's registrations were already revoked before `error` was
    captured, so this is a hygiene fact, not a registry leak."""

    def __init__(self, plugin_id: str, error: BaseException) -> None:
        super().__init__(
            "PLUGIN_DISPOSAL_RAISED",
            f"plugin {plugin_id!r}'s disposal raised "
            f"{type(error).__name__} during host cleanup",
        )
        self.plugin_id = plugin_id
        self.error = error


class CleanupError(ServerPluginError):
    """The host finished releasing every plugin, but at least one disposal
    raised; the per-plugin failures travel in `errors`, reverse activation
    order. Nothing was skipped — this is what "all cleaned, some failed"
    looks like."""

    def __init__(self, errors: "tuple[PluginCleanupError, ...]") -> None:
        super().__init__(
            "PLUGIN_CLEANUP_FAILED",
            f"{len(errors)} plugin disposal(s) raised during host cleanup: "
            + ", ".join(f"{e.plugin_id}({type(e.error).__name__})" for e in errors),
        )
        self.errors = tuple(errors)


class ContributionDeclarationError(ServerPluginError):
    """A contribution declaration violates the C2 shape rules: a missing or
    malformed point id, a bad api_version spelling, a non-boolean required
    flag, or a batch entry that is not a contribution."""

    def __init__(self, message: str) -> None:
        super().__init__("PLUGIN_CONTRIBUTION_DECLARATION_INVALID", message)


class DuplicateContributionError(ServerPluginError):
    """One batch declares the same point twice while the point is exclusive;
    the batch refuses instead of letting declaration order pick a silent
    winner. Multi-entry points must be declared open by the batch."""

    def __init__(self, point_id: str) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_DUPLICATE",
            f"contribution point {point_id} is declared more than once in one "
            "batch but the point is exclusive",
        )
        self.point_id = point_id


class RequiredContributionMissingError(ServerPluginError):
    """A contribution the batch itself marked `required` carries no payload,
    or a host-named required point is not observably carried. The batch is
    refused as a whole; optional absences never raise this — they resolve
    to an observable `AbsentContribution`."""

    def __init__(self, missing: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_REQUIRED_MISSING",
            "required contribution(s) missing from the batch: "
            + ", ".join(missing),
        )
        self.missing = tuple(missing)


class ContributionStateError(ServerPluginError):
    """A contribution transaction transitioned illegally: committing twice,
    or committing a batch that was already rolled back."""

    def __init__(self, message: str) -> None:
        super().__init__("PLUGIN_CONTRIBUTION_STATE_INVALID", message)


class ContributionCleanupError(ServerPluginError):
    """One staged contribution entry raised while its batch was being rolled
    back. A carried hygiene fact, never a primary: the stage failure that
    triggered the rollback stays the exception the caller sees, exactly as
    `PluginCleanupError` rides beside a disposal-triggered failure."""

    def __init__(self, plugin_owner: str, point_id: str, cause: BaseException) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_ROLLBACK_RAISED",
            f"rollback of contribution {point_id} for {plugin_owner!r} raised "
            f"{type(cause).__name__} during batch rollback",
        )
        self.plugin_owner = plugin_owner
        self.point_id = point_id
        self.cause = cause


class ContributionBatchCleanupError(ServerPluginError):
    """A batch rollback attempted every staged entry, but at least one entry's
    rollback raised; the per-entry failures travel in `errors`, reverse batch
    order. Nothing was skipped — this is what "everything undone as far as it
    goes, some cleanups failed" looks like when no other exception is in
    flight to carry it."""

    def __init__(self, errors: "tuple[ContributionCleanupError, ...]") -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_CLEANUP_FAILED",
            f"{len(errors)} contribution rollback(s) raised during batch "
            "rollback: "
            + ", ".join(f"{e.point_id}({type(e.cause).__name__})" for e in errors),
        )
        self.errors = tuple(errors)


class ContributionRollbackRefusedError(ServerPluginError):
    """Rollback was requested for a contribution batch that is already
    committed. This contract chooses refusal over a silent no-op: a
    published batch is retired through the host's unregister path, never
    un-published underneath its consumers."""

    def __init__(self, committed_points: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_ROLLBACK_REFUSED",
            "contribution batch is committed; rollback refuses and names the "
            "published point(s) for host retirement instead: "
            + ", ".join(committed_points),
        )
        self.committed_points = tuple(committed_points)


class ContributionPointUnboundError(ServerPluginError):
    """A batch declares a point the host has not registered, or one it
    registered without a handler (the seam is named but nothing binds it
    yet). Admission refuses type-wise: the contribution can be neither
    validated nor published, and silently dropping it would turn a missing
    binding into an observable absence no consumer asked for."""

    def __init__(self, point_id: str, claimer: str) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_POINT_UNBOUND",
            f"contribution point {point_id} carries no host-bound handler; "
            f"the batch by {claimer!r} is refused (register the point and "
            "bind its handler, or do not declare it)",
        )
        self.point_id = point_id
        self.claimer = claimer


class ContributionVersionRefusedError(ServerPluginError):
    """The contribution declares an api_version the point does not accept.
    The host never guesses across versions: the refusal names both the
    declared and the accepted spelling."""

    def __init__(self, point_id: str, claimer: str, declared: str, accepted: str) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_VERSION_REFUSED",
            f"contribution to point {point_id} by {claimer!r} declares "
            f"api_version {declared}; the point accepts {accepted}",
        )
        self.point_id = point_id
        self.claimer = claimer
        self.declared = declared
        self.accepted = accepted


class ContributionPointHeldError(ServerPluginError):
    """An exclusive point already has an owner — committed earlier or
    claimed earlier in the same round. The host refuses instead of picking
    a registration-order winner; even the same owner must retire before it
    republishes, so a takeover is always an explicit two-step."""

    def __init__(self, point_id: str, holder: str, claimer: str) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_POINT_HELD",
            f"contribution point {point_id} is exclusively held by "
            f"{holder!r} (refused re-registration by {claimer!r}; retire "
            "first)",
        )
        self.point_id = point_id
        self.holder = holder
        self.claimer = claimer


class HostAdmissionClosedError(ServerPluginError):
    """The host is mid-activation-round (`draining`): staged work of this
    round is not yet committed and a second registration/publish would
    either interleave with it or make a half batch observable. The refusal
    names the state; it is never a queue-and-run-later."""

    def __init__(self, action: str, state: str) -> None:
        super().__init__(
            "PLUGIN_HOST_ADMISSION_CLOSED",
            f"{action} refused while the host is {state!r}: activation "
            "admission is closed until the in-flight round commits or "
            "rolls back",
        )
        self.action = action
        self.state = state


class ContributionOwnerBusyError(ServerPluginError):
    """An owner whose contribution is currently resolved-in-flight cannot
    be deactivated: that would steal a live reference from a consumer
    mid-call. The refusal names the owner and the points in flight; unload
    the consumer (or wait for the hold to release) first."""

    def __init__(self, owner: str, points: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_OWNER_BUSY",
            f"owner {owner!r} cannot be unloaded while its contribution is "
            "in flight on point(s): " + ", ".join(points),
        )
        self.owner = owner
        self.points = tuple(points)


class ContributionAccessError(ServerPluginError):
    """A consumer asked the host to resolve a contribution its plugin never
    declared `requires` on the owner for. `requires` is the access grant
    for ports and it is the access grant for contributions too: the refusal
    names consumer, owner and point rather than returning a value the
    grant never authorized."""

    def __init__(self, consumer: str, owner: str, point_id: str) -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_ACCESS",
            f"consumer {consumer!r} may not resolve {point_id}: it does not "
            f"declare requires on the owner {owner!r}",
        )
        self.consumer = consumer
        self.owner = owner
        self.point_id = point_id


class ContributionAmbiguousError(ServerPluginError):
    """A consumer asked the host to resolve one view of a point that carries
    several published owners it is ALL granted on. The host refuses rather
    than picking: registration order is not a selection rule, and a
    silently-chosen owner would turn a composition fact into a guess. The
    refusal names the consumer, the point and every owner in publish order —
    `contributions(point_id)` on the host is the multi-view answer.

    Kept separate from `ContributionAccessError` on purpose: there the
    consumer has no grant and must not see the value at all; here it has
    every grant and must not be handed one of several values.
    """

    def __init__(self, consumer: str, point_id: str, owners: "tuple[str, ...]") -> None:
        super().__init__(
            "PLUGIN_CONTRIBUTION_AMBIGUOUS",
            f"consumer {consumer!r} cannot resolve a single view of {point_id}: "
            f"the point carries {len(owners)} published owners "
            f"({', '.join(owners)}) and the host does not pick one — resolve "
            f"every view through contributions({point_id})",
        )
        self.consumer = consumer
        self.point_id = point_id
        self.owners = tuple(owners)
