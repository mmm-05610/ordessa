"""C2 contribution protocol: declarations, batches, staged transactions.

A contribution is one author-declared entry for a host-owned extension
point: `point_id` + `api_version` + an opaque `payload` + a `required`
flag. This layer carries the shape rules and the transaction state
machine only — it never interprets a payload and never learns which
points exist. The host (T013) owns the point registry, conflict
semantics and admission freezing.

`PACTHOLD_CONTRIBUTIONS_POINT_ID` (version `PACTHOLD_CONTRIBUTIONS_API_VERSION`)
is declared here as the fixed core seam point; its payload is the C1
`CoreContributionSet`, checked by the eventual core binding in
`apps/server`, not by this package — a contribution payload is any
object here, and no pacthold type is referenced.

Owner is never author-declared: a `Contribution` has no owner field, and
a handler receives the owner as a parameter the host injects at stage
time (mirroring C1's `CoreRuntime.stage(owner, contributions)`).

Transaction rules (each pinned by the package tests):

- `stage` validates and prepares; nothing is visible and no handler
  `commit` runs before the batch commits.
- `commit` publishes every staged contribution of the batch, once.
- `rollback` before commit is idempotent; `rollback` after commit is a
  typed refusal (`ContributionRollbackRefusedError`) — a published
  batch is retired through the host's unregister path, never silently
  un-published.
- A contribution marked `required` without a payload, or a host-named
  required point the batch does not carry, refuses the batch
  (`RequiredContributionMissingError`). An optional point that is not
  carried resolves to an observable `AbsentContribution`, never an
  error.
- A rollback never replaces the primary exception and never swallows a
  cleanup fact: a failed staging undoes every already-staged entry, and a
  rollback that raises travels as `ContributionCleanupError` records on the
  in-flight exception's `cleanup_errors` attribute (accumulating; an
  exception that refuses attributes propagates unchanged). `rollback()`
  applies the same rule: attempt every entry, then carry the failures on
  the exception being handled if one is in flight, else raise one
  `ContributionBatchCleanupError` naming them all.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
import sys
from typing import Any, Iterable

from .errors import (
    ContributionBatchCleanupError,
    ContributionCleanupError,
    ContributionDeclarationError,
    ContributionRollbackRefusedError,
    ContributionStateError,
    DuplicateContributionError,
    RequiredContributionMissingError,
)

#: The fixed core contribution point. Its payload is the C1
#: `CoreContributionSet`; this package only names the point.
PACTHOLD_CONTRIBUTIONS_POINT_ID = "pacthold.contributions"
PACTHOLD_CONTRIBUTIONS_API_VERSION = "v1"

#: The host's wire/1 error-family seam (T014-S2a). Named here, like the core
#: point, without this package knowing anything about its payload: the host
#: owns the point and its aggregation semantics; components that produce
#: internal error codes publish their own `code -> family` mapping through
#: it. The point is OPEN (multi-owner): several plugins may publish rows,
#: and the host aggregates — this package never interprets the mapping.
#: (Spelled with the hyphen the frozen `CONTRIBUTION_POINT_ID` grammar
#: already admits; underscores are not part of the point-id vocabulary.)
WIRE_ERROR_FAMILIES_POINT_ID = "wire.error-families"
WIRE_ERROR_FAMILIES_API_VERSION = "v1"

#: The host's wire/1 discovery seam (T014-S3). `server.hello` publishes one
#: envelope the host owns (`serverId`, `protocolVersion`, `capabilities`,
#: `auth` — never overridable through this point) plus the *facets* the
#: composed domains advertise. A facet contribution's payload is
#: `facet name -> projector` (a zero-argument callable returning the entries
#: for that facet, or `None` to publish no key at all), because a facet's
#: content is a live deployment fact, not an activation-time snapshot: the
#: harness directory a facet projects can gain a member while the Server
#: runs. The point is OPEN (multi-owner — one facet per owning domain, several
#: domains per composition); the host aggregates and refuses two owners for
#: one facet name, and this package never calls a projector.
WIRE_DISCOVERY_FACETS_POINT_ID = "wire.discovery-facets"
WIRE_DISCOVERY_FACETS_API_VERSION = "v1"

#: The host CLI's business grammar (T014-S4). `python -m ordessa_server` keeps
#: only the transport-level flags the host owns (`--data-root`, `--port`);
#: every other flag the Server accepts is a `ServerFlagSpec` contributed by
#: the installed product under this point id — including the values that
#: decide which composition method the parsed facts feed
#: (`ServerCliPlan`). The CLI resolves the product through the same
#: `ordessa.server_product` seam as the runtime, so the point's contributor
#: is the product composition itself (there is no plugin host standing yet
#: when arguments are parsed); naming the point here keeps the registry a
#: single grep-complete list. The payload shape is contract (`ServerFlagSpec`
#: in `contract.py`); this package never parses arguments.
CLI_SERVER_FLAGS_POINT_ID = "cli.server-flags"
CLI_SERVER_FLAGS_API_VERSION = "v1"

#: A contribution point id: dot-separated lowercase words, the same wire
#: vocabulary shape as method ids (`pacthold.contributions`). Anything
#: else is a `ContributionDeclarationError`, not a host surprise later.
CONTRIBUTION_POINT_ID = re.compile(r"[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*\Z")

_CONTRIBUTION_API_VERSION = re.compile(r"v[1-9][0-9]*\Z")

_STAGE, _COMMIT, _ROLLBACK = "staged", "committed", "rolled-back"


def _undo_entries(handler: ServerContributionHandler, owner: str,
                  entries: "Iterable[tuple[Contribution, Any]]") -> "list[ContributionCleanupError]":
    """Roll back staged entries in reverse order, attempting every one.

    A rollback that raises is contained and returned as a
    `ContributionCleanupError` fact — it never stops the cleanups behind it
    and never becomes the caller's primary exception."""
    cleanup: "list[ContributionCleanupError]" = []
    for contribution, prepared in reversed(list(entries)):
        try:
            handler.rollback(contribution, prepared, owner)
        except Exception as err:  # noqa: BLE001 - carried, never primary
            cleanup.append(ContributionCleanupError(owner, contribution.point_id, err))
    return cleanup


def _carry_cleanup_errors(errors: "list[ContributionCleanupError]") -> None:
    """Attach a rollback's cleanup failures to the exception in flight.

    Mirrors the host's carrying rule: the rollback's own failure stays the
    primary exception; the cleanup facts ride on its `cleanup_errors`
    attribute. Attachments ACCUMULATE. An exception object that refuses
    attributes still propagates unchanged."""
    if not errors:
        return
    primary = sys.exc_info()[1]
    if primary is None:
        return
    try:
        existing = getattr(primary, "cleanup_errors", ())
        primary.cleanup_errors = tuple(existing) + tuple(errors)
    except (AttributeError, TypeError):
        pass


@dataclass(frozen=True)
class Contribution:
    """One contribution declaration carried by a registration.

    `payload` is opaque at this layer: any object, never validated here,
    never a platform type. `payload=None` states an explicit absence;
    combined with `required=True` it refuses the batch. There is
    deliberately no owner field — the host injects the owner when it
    stages the batch.
    """

    point_id: str
    api_version: str
    payload: Any = None
    required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.point_id, str) or not CONTRIBUTION_POINT_ID.fullmatch(self.point_id):
            raise ContributionDeclarationError(
                f"invalid contribution point id: {self.point_id!r}")
        if not isinstance(self.api_version, str) or not _CONTRIBUTION_API_VERSION.fullmatch(self.api_version):
            raise ContributionDeclarationError(
                f"contribution {self.point_id}: api_version must look like 'v1', "
                f"got {self.api_version!r}")
        if type(self.required) is not bool:
            raise ContributionDeclarationError(
                f"contribution {self.point_id}: required must be a boolean")


@dataclass(frozen=True)
class AbsentContribution:
    """Observable typed absence: a point the batch does not carry.

    Returned by resolution instead of raising — an optional missing
    contribution is a fact a consumer can see and branch on, not an
    error. `reason` states why nothing is there.
    """

    point_id: str
    reason: str


@dataclass(frozen=True)
class ContributionBatch:
    """The contributions one registration declares, validated as a whole.

    Points are exclusive unless named in `open_points`: a duplicate
    point id inside one batch is a `DuplicateContributionError`, never
    a silent last-wins. Exclusivity per point is the host's registry
    fact; this batch only carries the author's own declaration set.
    """

    contributions: "tuple[Contribution, ...]" = ()
    open_points: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.contributions, tuple):
            raise ContributionDeclarationError(
                "ContributionBatch.contributions must be a tuple")
        for item in self.contributions:
            if not isinstance(item, Contribution):
                raise ContributionDeclarationError(
                    f"batch entries must be Contribution, got {type(item).__name__}")
        if not isinstance(self.open_points, frozenset) or any(
                not isinstance(point, str) or not point for point in self.open_points):
            raise ContributionDeclarationError(
                "ContributionBatch.open_points must be a frozenset of point ids")
        seen: set[str] = set()
        for item in self.contributions:
            if item.point_id in seen and item.point_id not in self.open_points:
                raise DuplicateContributionError(item.point_id)
            seen.add(item.point_id)

    def resolve(self, point_id: str) -> "Contribution | AbsentContribution":
        """The batch's answer for one point: a carried contribution with a
        payload, or an observable `AbsentContribution`. Never raises."""
        for item in self.contributions:
            if item.point_id == point_id:
                if item.payload is not None:
                    return item
                return AbsentContribution(point_id, "declared with a null payload")
        return AbsentContribution(point_id, "not declared in this batch")

    def check_required(self, required_points: "Iterable[str]" = ()) -> None:
        """Refuse the batch when a required contribution is missing.

        Two sources of "required": the author's own `required` flag with
        no payload carried, and the point ids the host passes in
        `required_points` (the C2 admission contract) that this batch
        does not observably carry. Raises
        `RequiredContributionMissingError`; optional absences are not
        checked and stay observable via `resolve`.
        """
        missing = {item.point_id for item in self.contributions
                   if item.required and item.payload is None}
        missing |= {point for point in required_points
                    if isinstance(self.resolve(point), AbsentContribution)}
        if missing:
            raise RequiredContributionMissingError(tuple(sorted(missing)))


class ServerContributionHandler(ABC):
    """Host-driven transaction over one contribution batch.

    The host — never an author — supplies `owner` to every call.
    `stage(contribution, owner)` validates and returns an opaque
    prepared record with no externally visible side effect;
    `commit(contribution, prepared, owner)` publishes it;
    `rollback(contribution, prepared, owner)` undoes a staged,
    uncommitted record and must tolerate being called twice. `StagedBatch`
    enforces the ordering and idempotency rules around these calls.
    """

    @abstractmethod
    def stage(self, contribution: Contribution, owner: str) -> Any:
        """Validate `contribution` for this handler; prepare, do not publish."""

    @abstractmethod
    def commit(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        """Publish a staged contribution. Called only after `stage` succeeded."""

    @abstractmethod
    def rollback(self, contribution: Contribution, prepared: Any, owner: str) -> None:
        """Undo a staged contribution. May be called more than once."""


@dataclass(frozen=True)
class ContributionPointSpec:
    """A product's host-neutral declaration of one contribution point.

    The product passes these facts to its public composition seam; the host
    remains responsible for registration, admission, owner identity and busy
    retirement. A point without a handler is never silently accepted.
    """

    point_id: str
    api_version: str
    handler: ServerContributionHandler
    exclusive: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.point_id, str) or not CONTRIBUTION_POINT_ID.fullmatch(self.point_id):
            raise ContributionDeclarationError(f"invalid contribution point id: {self.point_id!r}")
        if not isinstance(self.api_version, str) or not _CONTRIBUTION_API_VERSION.fullmatch(self.api_version):
            raise ContributionDeclarationError(f"invalid contribution point API version: {self.api_version!r}")
        if not isinstance(self.handler, ServerContributionHandler):
            raise ContributionDeclarationError(f"contribution point {self.point_id!r} needs a ServerContributionHandler")
        if type(self.exclusive) is not bool:
            raise ContributionDeclarationError("contribution point exclusive must be a boolean")


def unique_contribution_point_specs(specs: Iterable[ContributionPointSpec]) -> tuple[ContributionPointSpec, ...]:
    """Validate a product's entire declaration list before registering any.

    A repeated point ID is ambiguous even when the version or handler differs;
    the caller can run this pure check before the first host-side mutation.
    """
    result = tuple(specs)
    seen: set[str] = set()
    for spec in result:
        if not isinstance(spec, ContributionPointSpec):
            raise ContributionDeclarationError("contribution point declarations must be ContributionPointSpec values")
        if spec.point_id in seen:
            raise ContributionDeclarationError(f"duplicate contribution point declaration: {spec.point_id}")
        seen.add(spec.point_id)
    return result


class StagedBatch:
    """One batch staged against one handler, held as a single transaction.

    Created by `stage_contributions` only. Before `commit`, nothing the
    batch staged is visible through `resolve`; after `commit`, every
    carried payload is. `rollback` is idempotent while staged and a
    typed refusal once committed.
    """

    def __init__(self, handler: ServerContributionHandler, owner: str,
                 batch: ContributionBatch,
                 entries: "tuple[tuple[Contribution, Any], ...]") -> None:
        self._handler = handler
        self._owner = owner
        self._batch = batch
        self._entries = entries
        self._state = _STAGE

    @property
    def state(self) -> str:
        return self._state

    @property
    def owner(self) -> str:
        """The host-injected owner this batch was staged under."""
        return self._owner

    @property
    def entries(self) -> "tuple[tuple[Contribution, Any], ...]":
        """The staged (contribution, prepared record) pairs, in batch order."""
        return self._entries

    def resolve(self, point_id: str) -> "Contribution | AbsentContribution":
        """The published view: a carried contribution once committed, an
        `AbsentContribution` while staged or after rollback."""
        if self._state != _COMMIT:
            return AbsentContribution(
                point_id, f"batch is {self._state}; committed contributions are the only published view")
        return self._batch.resolve(point_id)

    def commit(self) -> None:
        """Publish every staged contribution, exactly once, in batch order."""
        if self._state == _COMMIT:
            raise ContributionStateError(
                "contribution batch is already committed; commit runs exactly once")
        if self._state == _ROLLBACK:
            raise ContributionStateError(
                "contribution batch was rolled back; a rolled-back batch cannot commit")
        for contribution, prepared in self._entries:
            self._handler.commit(contribution, prepared, self._owner)
        self._state = _COMMIT

    def rollback(self) -> None:
        """Undo the staged batch. Idempotent while staged-and-uncommitted;
        once committed, rollback is refused (`ContributionRollbackRefusedError`)
        — published contributions retire through the host's unregister path.

        A raising entry rollback never skips the entries behind it: every
        staged entry is attempted, the batch ends rolled back, and the
        failures surface together — carried on the in-flight exception's
        `cleanup_errors` while unwinding a failed staging, else raised as
        one `ContributionBatchCleanupError`."""
        if self._state == _COMMIT:
            raise ContributionRollbackRefusedError(
                tuple(contribution.point_id for contribution, _ in self._entries))
        if self._state == _ROLLBACK:
            return
        cleanup = _undo_entries(self._handler, self._owner, self._entries)
        self._state = _ROLLBACK
        if cleanup:
            if sys.exc_info()[1] is None:
                raise ContributionBatchCleanupError(tuple(cleanup))
            _carry_cleanup_errors(cleanup)


def stage_contributions(handler: ServerContributionHandler, owner: str,
                        batch: ContributionBatch,
                        required_points: "Iterable[str]" = ()) -> StagedBatch:
    """Stage one batch: required-check first, then the handler's stage pass.

    `owner` is the host-injected identity passed to every handler call.
    If any handler stage raises, entries staged earlier in this pass are
    rolled back before the original error propagates — a failed staging
    never leaves half a batch prepared. A rollback that raises there is
    carried on the stage error's `cleanup_errors`, never raised in its
    place.
    """
    batch.check_required(required_points)
    entries: "list[tuple[Contribution, Any]]" = []
    try:
        for contribution in batch.contributions:
            entries.append((contribution, handler.stage(contribution, owner)))
    except BaseException:
        _carry_cleanup_errors(_undo_entries(handler, owner, entries))
        raise
    return StagedBatch(handler, owner, batch, tuple(entries))
