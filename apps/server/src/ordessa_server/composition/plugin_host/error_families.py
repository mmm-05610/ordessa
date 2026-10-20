"""The composition's half of the wire/1 family table.

The published contract vocabulary — the twelve-family `FAMILIES` set, the
`STATIC_ERROR_FAMILIES` rows the host or no component produces,
`converge_family`, `family_for` and the `WireError` object itself — lives in
`server_plugin_api.wire_errors` since T014-S2c, because plugins raise it and
must not import host internals. This module keeps what only a *composition*
can own: the aggregate of contributed rows and the point handler that
validates them.

T014-S2a split the table by owner; S2a-R made the contributed half per-host.
What stays here is composition state: business codes arrive as
`code -> family` mappings contributed through the open `wire.error-families`
point by the plugin that raises them, and the declaring `ServerPluginHost`
owns one `ErrorFamilyAggregate` per host (the first cut kept the aggregate in
module state, so two compositions in one process shared it and a bare host
answered another host's business rows). A consumer resolves a code through the
composition it was built for: the composition root hands
`host.wire_error_families.family_for` to the transport once, at construction —
the same shape as `harness_resolver` in bootstrap, and since S2c the same shape
for the one plugin (`server-compat`) that converts errors inside its own
handlers: it receives the resolver as an injected callable, never this object.

Aggregation semantics (the point is deliberately open / multi-owner; several
components produce the same code; each rule is checked per host):

- two owners publishing the same code with the **same** family coalesce in
  the host that composes them; the answer survives the retirement of either
  one, in that host and only there;
- two owners publishing the same code with **different** families, or a
  contributed family that contradicts a static row, refuse the batch at
  stage time — that host's registration-round machinery then undoes the
  whole round (validate-or-undo, FR-005). The host never picks a family by
  activation order;
- a published mapping retires with its owner in its own composition:
  deactivation rolls the owner's rows out of that host's aggregate
  immediately (C2's unregister path).
"""
from __future__ import annotations

from typing import Any, Mapping

from server_plugin_api import (
    WIRE_ERROR_FAMILIES_API_VERSION,
    WIRE_ERROR_FAMILIES_POINT_ID,
    Contribution,
    ServerContributionHandler,
)
from server_plugin_api.wire_errors import (  # re-exported: the host's own use
    FAMILIES,
    STATIC_ERROR_FAMILIES,
    WireError,
    converge_family,
    family_for,
)


class ErrorFamilyContributionRefused(ValueError):
    """A published error-family mapping is refused before anything is visible.

    Either the payload is not a `code -> family` mapping over the closed
    family set, or the code already has a different family in **this host's**
    aggregate (a static row or another owner's published/staged contribution in
    the same composition). Raising at `stage` is the loud half of
    validate-or-undo: the host's contribution round rolls the whole batch —
    and the plugin's activation — back, so two owners can never disagree
    about one code and the answer can never depend on which one activated
    first.
    """

    def __init__(self, message: str, *, code: str | None = None,
                 family: str | None = None, existing: str | None = None,
                 owner: str | None = None, other_owner: str | None = None) -> None:
        self.code = code
        self.family = family
        self.existing = existing
        self.owner = owner
        self.other_owner = other_owner
        super().__init__(message)


def _refuse_conflict(code: str, family: str, existing: str,
                     owner: str, other_owner: "str | None") -> "ErrorFamilyContributionRefused":
    source = f"owner {other_owner!r}" if other_owner else "the static wire/1 table"
    return ErrorFamilyContributionRefused(
        f"{WIRE_ERROR_FAMILIES_POINT_ID}: {owner!r} contributes {code} -> {family}, "
        f"which conflicts with {existing} from {source}",
        code=code, family=family, existing=existing, owner=owner,
        other_owner=other_owner)


def _validate_family(code: str, family: Any, owner: str) -> None:
    if not isinstance(family, str) or family not in FAMILIES:
        raise ErrorFamilyContributionRefused(
            f"{WIRE_ERROR_FAMILIES_POINT_ID}: {owner!r} contributes {code} -> {family!r}; "
            f"the wire/1 family set is closed (FAMILIES)",
            code=code, family=repr(family), existing="not a wire/1 family",
            owner=owner)


def _answer_for(code: str,
                entries: "list[tuple[Mapping[str, str], str]]") -> "tuple[str | None, str | None]":
    """(family, owner) of the first entry answering `code`, published order."""
    for mapping, owner in entries:
        if code in mapping:
            return mapping[code], owner
    return None, None


class ErrorFamilyAggregate:
    """The contributed half of the wire/1 family table, for ONE composition.

    Owned by the `ServerPluginHost` that declares the point (T014-S2a-R):
    the published/staged lists are per-host instance state, never module
    state. Two live compositions in one process therefore answer each other
    nothing — a host that composes no producer resolves that producer's
    codes through the documented `UNAVAILABLE` fall-through even while a
    neighbouring host published the rows. The C2 registry holds the
    transactional truth; this index exists because family lookup is a pure
    read reached from every request path. It is written ONLY through the
    handler below (one handler instance per host, bound to this object):
    activate publishes an owner's mapping, commit makes it visible, rollback
    and retire remove exactly it.
    """

    def __init__(self) -> None:
        #: Published contributed rows: list of `(mapping, owner)` in
        #: publish order.
        self._contributed: "list[tuple[Mapping[str, str], str]]" = []
        #: Staged-but-unpublished mappings (same entry shape). Conflict
        #: checks see these so two plugins in the SAME activation round
        #: collide at stage time, not silently at commit; the consumer
        #: lookup never does — half a round is not a value (host.py
        #: publication rule).
        self._staged: "list[tuple[Mapping[str, str], str]]" = []

    # -- transaction (driven only by this host's point handler) ----------

    def stage(self, payload: Mapping[str, str], owner: str) -> None:
        if not isinstance(payload, Mapping) or not payload:
            raise ErrorFamilyContributionRefused(
                f"{WIRE_ERROR_FAMILIES_POINT_ID}: {owner!r} payload must be a non-empty "
                f"mapping of internal code to wire family, got {payload!r}",
                owner=owner)
        for code, family in payload.items():
            if not isinstance(code, str) or not code:
                raise ErrorFamilyContributionRefused(
                    f"{WIRE_ERROR_FAMILIES_POINT_ID}: {owner!r} contributes a code that is "
                    f"not a non-empty string: {code!r}",
                    code=repr(code), owner=owner)
            _validate_family(code, family, owner)
            host_family = STATIC_ERROR_FAMILIES.get(code)
            if host_family is not None and host_family != family:
                raise _refuse_conflict(code, family, host_family, owner, None)
            for entries in (self._contributed, self._staged):
                existing, other = _answer_for(code, entries)
                if existing is not None and existing != family:
                    raise _refuse_conflict(code, family, existing, owner, other)
        self._staged.append((payload, owner))

    def commit(self, prepared: Any, owner: str) -> None:
        # Same activation round staged it; move it from the staged view to
        # the published one. A re-entrant commit cannot happen:
        # `StagedBatch` publishes each entry exactly once.
        self._contributed.append((prepared, owner))
        for index, (mapping, entry_owner) in enumerate(self._staged):
            if mapping is prepared and entry_owner == owner:
                del self._staged[index]
                break

    def rollback(self, prepared: Any, owner: str) -> None:
        # The unregister path and the round-undo path, alike: remove THIS
        # entry (identity, not owner string) from both views. Idempotent:
        # an entry already gone is not a failure. The payload mapping object
        # itself is the identity token: owner strings alone are not unique
        # across compositions.
        for entries in (self._staged, self._contributed):
            for index, (mapping, entry_owner) in enumerate(entries):
                if mapping is prepared and entry_owner == owner:
                    del entries[index]
                    return

    # -- consumer resolution ----------------------------------------------

    def family_for(self, code: str) -> str:
        """The composition's full answer: static rows, then this host's
        published contributions, then family names, then the fall-through.
        This is what the transport (and, since S2c, the one plugin that
        converts errors inside its own handlers) is handed at construction; it
        reads only THIS host's aggregate."""
        if code in STATIC_ERROR_FAMILIES:
            return STATIC_ERROR_FAMILIES[code]
        contributed, _owner = _answer_for(code, self._contributed)
        if contributed is not None:
            return contributed
        if code in FAMILIES:
            return code
        return "UNAVAILABLE"

    def contributed_families(self) -> "dict[str, tuple[str, ...]]":
        """Observation seam for the gates: code -> owners published in THIS
        composition. Read-only; nothing in the request path uses it."""
        view: "dict[str, set[str]]" = {}
        for mapping, owner in self._contributed:
            for code in mapping:
                view.setdefault(code, set()).add(owner)
        return {code: tuple(sorted(owners)) for code, owners in view.items()}


class _ErrorFamiliesContribution(ServerContributionHandler):
    """The host-side handler of the open `wire.error-families` point.

    One instance per declaring host, bound to that host's aggregate:
    `stage` validates shape and conflicts against the static rows plus every
    mapping published or staged in THIS composition, then records the
    mapping as staged; `commit` makes exactly that recorded mapping visible
    (identity-based, so a republish and a retire can never remove the wrong
    entry); `rollback` removes the entry from both views and tolerates being
    called twice.
    """

    def __init__(self, aggregate: ErrorFamilyAggregate) -> None:
        self._aggregate = aggregate

    def stage(self, contribution: Contribution, owner: str) -> Mapping[str, str]:
        self._aggregate.stage(contribution.payload, owner)
        return contribution.payload

    def commit(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        self._aggregate.commit(prepared, owner)

    def rollback(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        self._aggregate.rollback(prepared, owner)


def declare_wire_error_families_point(host: Any) -> None:
    """Declare the host's own `wire.error-families` seam on one plugin host.

    The point belongs to the host's wire/1 contract, so the host declares it
    open (multi-owner — several components produce the same code) when the
    plugin host comes into being, before any registration is staged. The
    aggregate and its handler are built HERE, for THIS host: the contributed
    table is composition state owned by the declaring `ServerPluginHost`
    (S2a-R), never process state. The handler carries no business rows:
    every mapping is published by the plugin that raises the codes.
    Imported lazily from `plugin_host`: the error vocabulary needs no host-side
    wiring of its own.
    """
    aggregate = ErrorFamilyAggregate()
    host.wire_error_families = aggregate
    host.register_contribution_point(
        WIRE_ERROR_FAMILIES_POINT_ID, WIRE_ERROR_FAMILIES_API_VERSION,
        handler=_ErrorFamiliesContribution(aggregate), exclusive=False)
