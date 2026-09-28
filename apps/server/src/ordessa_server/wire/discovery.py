"""The composition's `server.hello` discovery facets (T014-S3).

`server.hello` is the one wire method the host owns end to end, and it is also
the one place where the composed domains have to speak: which harnesses this
Server can run, and (for a native deployment) whose identity it runs as. Before
this slice the host *built* those entries itself — it walked the live harness
directory port in `wire/handlers.py` and validated the native identity facts
inline — so the host knew the business it is only meant to carry.

Now a domain contributes a facet: a `facet name -> projector` mapping published
through the open `wire.discovery-facets` point, where the projector is a
zero-argument callable the host calls per `hello`. A projector, not a value,
because the fact is live: `test_stage4_audit.py` registers a harness into the
directory *after* activation and requires the next hello to advertise it, so an
activation-time snapshot would be a different protocol.

What stays host-owned and un-overridable:

- the envelope — `serverId`, `protocolVersion`, `capabilities`, `auth`. A facet
  claiming one of those names is refused at stage time (`_RESERVED_ENVELOPE`),
  which is what makes "the host keeps its fields" a checked property instead of
  a coding habit;
- the aggregation and the empty defaults: wire/1's hello result always carries
  the `harnesses` member (a composition with no harness plugin answers the
  empty list, pinned by `test_bare_host_exposes_exactly_the_host_capabilities`)
  and never invents a key a projector declined to fill (`None` = no key);
- the conflict rule: one facet, one owner. Two owners for one name refuse the
  batch and the round undoes (FR-005), so a discovery answer never depends on
  activation order.

Like the family table, this is per-composition state: the aggregate is owned by
the declaring `ServerPluginHost`, never by module state, so two live
compositions in one process publish nothing to each other's hello.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from server_plugin_api import (
    WIRE_DISCOVERY_FACETS_API_VERSION,
    WIRE_DISCOVERY_FACETS_POINT_ID,
    Contribution,
    ServerContributionHandler,
)

#: The hello envelope the host builds and no contribution may claim. Naming
#: them here is the point: these are wire/1's contract members, not domain
#: vocabulary.
RESERVED_ENVELOPE = frozenset({
    "serverId", "protocolVersion", "capabilities", "auth",
})

#: wire/1 members that are always present, even when no facet claims them.
#: `harnesses` is one of the two discovery arrays the contract froze, so its
#: absence would be a protocol change; a facet that IS composed fills it.
ALWAYS_PRESENT_EMPTY_LIST = frozenset({"harnesses"})

#: A facet name is a JSON member name of the hello result.
_FACET_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")


class DiscoveryFacetContributionRefused(ValueError):
    """A published facet mapping is refused before anything is observable.

    Raised at `stage` for a payload that is not a `name -> callable` mapping, a
    name that is not a hello member name, a name already claimed in this
    composition (by another owner or by the same owner republishing without
    retiring), or a name belonging to the host's envelope. The host's
    registration round then undoes the whole batch — the half facet is never a
    value a client can read.
    """

    def __init__(self, message: str, *, facet: str | None = None,
                 owner: str | None = None, other_owner: str | None = None) -> None:
        self.facet = facet
        self.owner = owner
        self.other_owner = other_owner
        super().__init__(message)


class DiscoveryFacetAggregate:
    """The facet projectors published to ONE composition, in publish order."""

    def __init__(self) -> None:
        self._published: "list[tuple[Mapping[str, Callable[[], Any]], str]]" = []
        self._staged: "list[tuple[Mapping[str, Callable[[], Any]], str]]" = []

    # -- transaction (driven only by this host's point handler) ----------

    def stage(self, payload: Mapping[str, Callable[[], Any]], owner: str) -> None:
        if not isinstance(payload, Mapping) or not payload:
            raise DiscoveryFacetContributionRefused(
                f"{WIRE_DISCOVERY_FACETS_POINT_ID}: {owner!r} payload must be a non-empty "
                f"mapping of facet name to projector, got {payload!r}",
                owner=owner)
        for facet, projector in payload.items():
            if not isinstance(facet, str) or not _FACET_NAME.match(facet):
                raise DiscoveryFacetContributionRefused(
                    f"{WIRE_DISCOVERY_FACETS_POINT_ID}: {owner!r} contributes a facet name "
                    f"that is not a hello member name: {facet!r}",
                    facet=repr(facet), owner=owner)
            if facet in RESERVED_ENVELOPE:
                raise DiscoveryFacetContributionRefused(
                    f"{WIRE_DISCOVERY_FACETS_POINT_ID}: {owner!r} may not contribute the "
                    f"envelope member {facet!r}; serverId/protocolVersion/capabilities/auth "
                    "are the host's and never overridable",
                    facet=facet, owner=owner)
            if not callable(projector):
                raise DiscoveryFacetContributionRefused(
                    f"{WIRE_DISCOVERY_FACETS_POINT_ID}: {owner!r} contributes {facet!r} as "
                    f"a {type(projector).__name__}; a facet carries a zero-argument projector",
                    facet=facet, owner=owner)
            existing = self._owner_of(facet, (self._published, self._staged))
            if existing is not None:
                raise DiscoveryFacetContributionRefused(
                    f"{WIRE_DISCOVERY_FACETS_POINT_ID}: {owner!r} contributes {facet!r}, "
                    f"already published by {existing!r} in this composition",
                    facet=facet, owner=owner, other_owner=existing)
        self._staged.append((payload, owner))

    @staticmethod
    def _owner_of(facet: str, entries: "tuple[list, ...]") -> "str | None":
        for mappings in entries:
            for mapping, mapping_owner in mappings:
                if facet in mapping:
                    return mapping_owner
        return None

    def commit(self, prepared: Any, owner: str) -> None:
        self._published.append((prepared, owner))
        for index, (mapping, entry_owner) in enumerate(self._staged):
            if mapping is prepared and entry_owner == owner:
                del self._staged[index]
                break

    def rollback(self, prepared: Any, owner: str) -> None:
        # Identity-based, like the family aggregate: the published mapping
        # object is the token, so a retire removes exactly the entry that
        # owner published and never a neighbour's.
        for entries in (self._staged, self._published):
            for index, (mapping, entry_owner) in enumerate(entries):
                if mapping is prepared and entry_owner == owner:
                    del entries[index]
                    return

    # -- consumer resolution (the host transport only) --------------------

    def facets(self) -> "dict[str, Callable[[], Any]]":
        """Every published projector, in publish order.

        A facet with no owner is not in here at all: `hello` then answers the
        contract's empty default for `harnesses` and omits any other member —
        a typed absence, never a refusal.
        """
        view: "dict[str, Callable[[], Any]]" = {}
        for mapping, _owner in self._published:
            for facet, projector in mapping.items():
                view[facet] = projector
        return view

    def contributed_facets(self) -> "dict[str, str]":
        """Observation seam for the gates: facet -> owning plugin."""
        view: "dict[str, str]" = {}
        for mapping, owner in self._published:
            for facet in mapping:
                view[facet] = owner
        return view


class _DiscoveryFacetsContribution(ServerContributionHandler):
    """The host-side handler of the open `wire.discovery-facets` point.

    One instance per declaring host, bound to that host's aggregate: `stage`
    validates and records, `commit` publishes exactly the recorded mapping,
    `rollback` removes it (twice is fine, a gone entry is not a failure).
    """

    def __init__(self, aggregate: DiscoveryFacetAggregate) -> None:
        self._aggregate = aggregate

    def stage(self, contribution: Contribution, owner: str) -> Mapping[str, Any]:
        self._aggregate.stage(contribution.payload, owner)
        return contribution.payload

    def commit(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        self._aggregate.commit(prepared, owner)

    def rollback(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        self._aggregate.rollback(prepared, owner)


def declare_wire_discovery_facets_point(host: Any) -> None:
    """Declare the host's own `wire.discovery-facets` seam on one plugin host.

    Same shape as the family point: the host owns the seam, declares it open
    (one facet per owning domain, several domains per composition), and binds
    a per-host handler over a per-host aggregate. The handler carries no facet
    of its own — every projector is published by the domain that can answer it.
    """
    aggregate = DiscoveryFacetAggregate()
    host.wire_discovery_facets = aggregate
    host.register_contribution_point(
        WIRE_DISCOVERY_FACETS_POINT_ID, WIRE_DISCOVERY_FACETS_API_VERSION,
        handler=_DiscoveryFacetsContribution(aggregate), exclusive=False)
