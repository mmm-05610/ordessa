"""Host-owned contribution point registry (T013).

The composition declares points; authors only declare contributions.
One `ContributionPoint` binds a point id to the api_version it accepts,
an optional `ServerContributionHandler` (the seam may be declared before
anything binds it — the real core handler arrives with the T015 binding),
and whether the point is exclusive.

Visibility rule: exactly one structure is ever read by consumers — the
registry's published records. Staging and committing a round never touch
it entry-by-entry: the host collects a round's committed entries and
`publish()`es them as one swap after every batch of the round committed.
A consumer resolving mid-round therefore sees the previous committed
view, never a half batch. Retirement (`retire_owner`) is the unregister
path a published batch leaves through, and it removes exactly one owner's
records: an observable absence the moment it returns.

In-flight accounting (`acquire`/`release`/`busy`) is a counter per owner,
held through the host's `use_contribution` context: an owner with a live
reference cannot be unloaded (the host raises `ContributionOwnerBusyError`
— C1's `owner_busy`/unregister semantics).

Payloads are opaque here: nothing in this module or in `host.py` imports
`pacthold` or interprets a payload; the handler does, and until one is
bound the point refuses admission type-wise instead of dropping entries.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from server_plugin_api import (
    AbsentContribution,
    Contribution,
    InvalidDeclarationError,
    ServerContributionHandler,
)

__all__ = [
    "ContributionPoint", "PublishedRecord", "ResolvedContribution",
    "ContributionPointRegistry",
]


@dataclass(frozen=True)
class ContributionPoint:
    """One host-declared extension point."""

    point_id: str
    api_version: str
    handler: ServerContributionHandler | None = None
    exclusive: bool = True


@dataclass(frozen=True)
class PublishedRecord:
    """A committed contribution's registry entry: who owns it, what was
    declared, what the handler prepared, and which handler to call on
    retirement (the unregister path)."""

    owner: str
    contribution: Contribution
    prepared: Any
    handler: ServerContributionHandler
    publication_token: str = ""


@dataclass(frozen=True)
class ResolvedContribution:
    """The consumer view of one publication, including its opaque identity.

    A token changes when the same owner and payload are retired and published
    again. It never identifies a staged or rolled-back contribution.
    """

    point_id: str
    api_version: str
    payload: Any
    owner: str
    publication_token: str = ""


class ContributionPointRegistry:
    """Points, published records and in-flight holds. No transactions:
    the host drives staging/committing/retiring through this store; this
    class never decides visibility ordering on its own beyond the atomic
    publish swap below."""

    def __init__(self) -> None:
        self._points: dict[str, ContributionPoint] = {}
        #: publish order across all points — retirement walks it in reverse
        self._published: list[PublishedRecord] = []
        self._holds: dict[str, int] = {}

    # -- point declaration -----------------------------------------------------

    def register(self, point_id: str, api_version: str, *,
                 handler: ServerContributionHandler | None = None,
                 exclusive: bool = True) -> None:
        """Declare a point, or bind a handler to one already declared.
        Re-registering is only legal when it keeps the earlier facts
        (same version, same exclusivity) and does not unbind a handler."""
        existing = self._points.get(point_id)
        declared = ContributionPoint(point_id=point_id, api_version=api_version,
                                     handler=handler, exclusive=exclusive)
        if existing is not None:
            if (existing.api_version != api_version or existing.exclusive != exclusive
                    or (existing.handler is not None and handler is not existing.handler)):
                raise InvalidDeclarationError(
                    f"contribution point {point_id} is already declared as "
                    f"{existing.api_version!r}, exclusive={existing.exclusive}, "
                    f"handler {'bound' if existing.handler is not None else 'unbound'}")
            if existing.handler is None and handler is None:
                return
        self._points[point_id] = declared

    def point(self, point_id: str) -> ContributionPoint | None:
        return self._points.get(point_id)

    # -- published view (the ONLY consumer-readable structure) ------------------

    def published(self, point_id: str) -> tuple[PublishedRecord, ...]:
        return tuple(record for record in self._published
                     if record.contribution.point_id == point_id)

    def holder(self, point_id: str) -> str | None:
        """The current owner of a published contribution on the point, if
        any. Exclusive or not: a second claim of an exclusively-held point
        must be nameable, and so must a same-owner republish."""
        records = self.published(point_id)
        return records[0].owner if records else None

    def publish(self, records: "tuple[PublishedRecord, ...] | list[PublishedRecord]") -> None:
        """The round's atomic swap: called only after every batch of the
        round committed, in one call, with the whole round's records."""
        tokenized = tuple(replace(record, publication_token=uuid4().hex)
                          for record in records)
        self._published.extend(tokenized)

    def retire_owner(self, owner: str) -> tuple[PublishedRecord, ...]:
        """The unregister path: remove exactly this owner's published
        records and return them in reverse publish order (the host drives
        the handler rollback attempts). The published view is already
        clean when this returns — retirement is observable immediately."""
        removed = [record for record in self._published if record.owner == owner]
        self._published = [record for record in self._published if record.owner != owner]
        return tuple(reversed(removed))

    def resolve(self, point_id: str) -> "ResolvedContribution | AbsentContribution":
        """The single view for one point: published records only. An open
        point with several owners has no single view — that is a fact,
        stated as an absence reason, and `views()` answers it."""
        records = self.published(point_id)
        if not records:
            return AbsentContribution(point_id, "no committed contribution is published")
        if len(records) > 1:
            owners = ", ".join(sorted({record.owner for record in records}))
            return AbsentContribution(
                point_id,
                f"point carries {len(records)} owners ({owners}); "
                "resolve through views()")
        return self.record_view(records[0])

    def views(self, point_id: str) -> tuple[ResolvedContribution, ...]:
        return tuple(self.record_view(record) for record in self.published(point_id))

    @staticmethod
    def record_view(record: PublishedRecord) -> ResolvedContribution:
        return ResolvedContribution(
            point_id=record.contribution.point_id,
            api_version=record.contribution.api_version,
            payload=record.contribution.payload,
            owner=record.owner,
            publication_token=record.publication_token,
        )

    # -- in-flight holds (busy/unload protection) --------------------------------

    def acquire(self, owner: str) -> None:
        self._holds[owner] = self._holds.get(owner, 0) + 1

    def release(self, owner: str) -> None:
        count = self._holds.get(owner, 0) - 1
        if count <= 0:
            self._holds.pop(owner, None)
        else:
            self._holds[owner] = count

    def busy(self, owner: str) -> bool:
        return self._holds.get(owner, 0) > 0

    def busy_points(self, owner: str) -> tuple[str, ...]:
        """The points this owner holds live references on — for the refusal
        message; holds attach to the owner, the points name the refusal."""
        if not self.busy(owner):
            return ()
        return tuple(sorted({record.contribution.point_id
                             for record in self._published if record.owner == owner}))

    def held_owners(self) -> tuple[str, ...]:
        return tuple(sorted(self._holds))
