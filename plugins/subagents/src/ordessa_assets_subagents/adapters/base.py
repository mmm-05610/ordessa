"""The assess/compile/verify triad, re-based onto the published C0 contract.

Since `harness-api` was published (checkpoint `codex/011-harness-api-ready`,
SR-1b), this module is a *producer* layer over `ordessa_harness_api`, not a
parallel vocabulary:

* `assess(context, request)` returns the real
  :class:`ordessa_harness_api.Assessment`; the per-pin, per-cell honesty
  record (capability-matrix.md) survives as the INTERNAL
  :class:`Assessment`/`CellVerdict` shape behind :meth:`assess_detail`, so
  `supported` can never be claimed without proof even though the contract
  itself would allow an evidence-less `supported` (gap reported);
* `compile(context, collection, source)` returns the real
  :class:`ordessa_harness_api.IntentSet` built by
  :func:`~.intents.compile_all` — the target is the server-issued
  `TargetHandle` inside the injected `AdapterContext`, the ownership is the
  host-injected `IntentSource`; there is no `TargetSlot` any more;
* `verify(context, observed)` returns the real
  :class:`ordessa_harness_api.Verification` (`Match` / `Mismatch` /
  `VerificationUnknown`). The observation state machine — a materialised
  file can never yield `loaded` (G11/G12) — still decides: `Match` requires
  a loader-class observation, so the ladder is preserved and the protocol
  shape maps onto it.

The ladder itself (kept, mutation-tested):

* `loaded` requires a :class:`NativeLoaderObservation` (an observation of
  the target's own loader);
* `invokable` requires a :class:`ControlEntryObservation`;
* `used` requires an :class:`InvocationEventObservation` — model narration
  or a menu click is not one (FR15/G17);
* :class:`FileExistenceObservation` attests `projected` and nothing more.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence, Union

from ordessa_harness_api import (
    AdapterContext, AdapterRefusal, Assessment as RealAssessment,
    ConfigurationAdapterDescriptor, ErrorCode, FieldClaim, IntentSet,
    IntentSource, Match, Mismatch, TargetDescriptor as RealTargetDescriptor,
    TargetHandle, VerificationUnknown, VersionRange,
)

from .. import errors
from . import intents
from .intents import NATIVE_NAME_RE, _check_token

HARNESS_ID_RE_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"

#: Maps Q3's domain refusal codes onto the published contract's ErrorCode so
#: the future wiring (T12) can present a `AdapterRefusal` without inventing
#: a second error vocabulary.
DOMAIN_TO_CONTRACT_CODE: Mapping[str, ErrorCode] = {
    errors.DEFINITION_INVALID: ErrorCode.INVALID_FRAGMENT,
    errors.REFERENCE_UNRESOLVED: ErrorCode.INVALID_FRAGMENT,
    errors.PERMISSION_EXCEEDS_CEILING: ErrorCode.AUTHORIZATION_REFUSED,
    errors.NATIVE_NAME_CONFLICT: ErrorCode.TARGET_CONFLICT,
    errors.TARGET_CONFLICT: ErrorCode.TARGET_CONFLICT,
    errors.NATIVE_VERSION_UNKNOWN: ErrorCode.VERSION_UNVERIFIED,
    errors.NATIVE_DISCOVERY_UNCONTROLLED: ErrorCode.CAPABILITY_UNSUPPORTED,
    errors.NATIVE_ENTRY_UNAVAILABLE: ErrorCode.CAPABILITY_UNSUPPORTED,
    errors.ADAPTER_MISSING: ErrorCode.ADAPTER_MISSING,
    errors.LOAD_UNVERIFIED: ErrorCode.VERIFICATION_MISMATCH,
    errors.OPERATION_UNKNOWN: ErrorCode.OPERATION_UNKNOWN,
    errors.PROVIDER_BUSY: ErrorCode.BUSY,
    errors.REVISION_STALE: ErrorCode.STALE_PLAN,
    errors.ASSIGNMENT_CONFLICT: ErrorCode.TARGET_CONFLICT,
}


def adapter_refusal_for(error: errors.DomainError) -> AdapterRefusal:
    """Translate a Q3 refusal into the contract's `AdapterRefusal` shape."""
    if not isinstance(error, errors.DomainError):
        raise TypeError("adapter_refusal_for needs a DomainError")
    code = DOMAIN_TO_CONTRACT_CODE.get(error.code)
    if code is None:
        raise errors.DomainError(
            errors.DEFINITION_INVALID,
            detail=f"no contract ErrorCode mapping for refusal {error.code!r}",
        )
    return AdapterRefusal(code, error.detail or error.code)


# -- internal per-pin assessment record (NOT the published shape) -------------


class AssessmentError(ValueError):
    """A triad value that would claim a verdict without proof (G01/G03)."""

    def __init__(self, rule: str, detail: str) -> None:
        self.rule = rule
        super().__init__(f"{rule}: {detail}")


class AssessmentState(str, Enum):
    SUPPORTED = "supported"
    EXTENSION_BACKED = "extension-backed"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


#: The published contract has no "extension-backed" assessment status: the
#: better available expression for 「extension-backed: absent」 is
#: `Assessment(status="unsupported", reason=<what is absent + evidence>)`
#: (plus ConfigurationCapability.reason at inspect level). SR-1b answer.
_REAL_STATUS: Mapping[AssessmentState, str] = {
    AssessmentState.SUPPORTED: "supported",
    AssessmentState.EXTENSION_BACKED: "unsupported",
    AssessmentState.UNSUPPORTED: "unsupported",
    AssessmentState.UNKNOWN: "unknown",
}

_VERDICT_STATES = (AssessmentState.SUPPORTED, AssessmentState.EXTENSION_BACKED,
                   AssessmentState.UNSUPPORTED)


def _coerce_state(value: Any, *, what: str) -> AssessmentState:
    if isinstance(value, AssessmentState):
        return value
    if isinstance(value, str):
        try:
            return AssessmentState(value)
        except ValueError:
            pass
    raise AssessmentError(what, f"not an assessment state: {value!r}")


@dataclass(frozen=True)
class CellVerdict:
    """One capability-matrix cell: verdict + reason + proof, per pin (G03).

    Internal only: the contract's `Assessment` is one tri-state; the matrix
    detail stays here so the per-cell evidence rule (no verdict without an
    evidence tuple) survives the mapping.
    """

    cell: str
    state: AssessmentState
    reason: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cell",
                           _check_token(self.cell, what="cell name",
                                        pattern=NATIVE_NAME_RE))
        object.__setattr__(self, "state", _coerce_state(self.state, what="cell state"))
        if not isinstance(self.reason, str) or not self.reason:
            raise AssessmentError("cell.reason", "every cell verdict must carry a reason string")
        if not isinstance(self.evidence, tuple):
            object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.state in _VERDICT_STATES and not self.evidence:
            raise AssessmentError(
                "cell.evidence",
                f"cell {self.cell!r} claims {self.state!r} with an empty "
                "evidence tuple: a verdict needs concrete proof references",
            )


@dataclass(frozen=True)
class Assessment:
    """The internal, per-pin detail record; `to_real` yields the contract DTO.

    The contract would let `Assessment("supported")` stand with no evidence
    at all (`ordessa_harness_api/contracts.py:191-206` only requires a
    *reason* for the negative states) — Q3 keeps its stricter constructor
    rule so `supported` can never be claimed without proof (SR-1b(c) answer
    plus a reported gap asking C0 to make evidence mandatory).
    """

    state: AssessmentState
    pinned_version: str
    evidence: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    cells: tuple[CellVerdict, ...] = ()

    def __post_init__(self) -> None:
        state = _coerce_state(self.state, what="assessment state")
        object.__setattr__(self, "state", state)
        if not isinstance(self.pinned_version, str) or not self.pinned_version.strip():
            raise errors.DomainError(
                errors.NATIVE_VERSION_UNKNOWN,
                detail="an assessment is always versioned per pin (G01); "
                       "a blank pinned_version is refused",
            )
        for name in ("evidence", "reasons", "cells"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))
        if state in _VERDICT_STATES and not self.evidence:
            raise AssessmentError(
                "assessment.evidence",
                f"an assessment claiming {state.value!r} with an empty evidence "
                "tuple is a construction error: no cell may be claimed "
                "supported (or a proven absence) without proof (G01/G03)",
            )
        for cell in self.cells:
            if not isinstance(cell, CellVerdict):
                raise AssessmentError("assessment.cells", "cells must be CellVerdict")

    def verdict(self, cell: str) -> CellVerdict:
        for entry in self.cells:
            if entry.cell == cell:
                return entry
        raise KeyError(cell)

    def to_real(self) -> RealAssessment:
        """The published `Assessment` DTO for this pin record."""
        status = _REAL_STATUS[self.state]
        evidence_ref = (f"pin {self.pinned_version} ;; "
                        + " ;; ".join(self.evidence)) if self.evidence else None
        reason = " ;; ".join(self.reasons) if self.reasons else None
        if status != "supported" and not reason:
            raise AssessmentError(
                "assessment.reasons",
                "the contract requires a reason for a non-supported assessment; "
                "refusing to emit one we cannot justify",
            )
        return RealAssessment(status, evidence_ref=evidence_ref, reason=reason)


# -- verification ladder (internal) + real Verification mapping ---------------


class VerifyState(str, Enum):
    PROJECTED = "projected"
    LOADED = "loaded"
    INVOKABLE = "invokable"
    USED = "used"
    UNKNOWN = "unknown"


_LADDER: tuple[VerifyState, ...] = (
    VerifyState.PROJECTED, VerifyState.LOADED, VerifyState.INVOKABLE, VerifyState.USED,
)

#: What each rung additionally demands, spelled as the observation type name
#: (data-model.md §状态和迁移: separate facts, never upgraded by a file digest
#: or a model's narration).
RUNG_REQUIREMENT: Mapping[VerifyState, str] = {
    VerifyState.PROJECTED: "ProjectedArtifactObservation or FileExistenceObservation",
    VerifyState.LOADED: "NativeLoaderObservation (an observation of the target's loader)",
    VerifyState.INVOKABLE: "ControlEntryObservation (an observation of the control entry)",
    VerifyState.USED: "InvocationEventObservation (an observed invocation event)",
}

#: Field on each observation type that carries the evidence reference.
_REF_FIELD: Mapping[str, str] = {
    "ProjectedArtifactObservation": "projection_ref",
    "NativeLoaderObservation": "loader_ref",
    "ControlEntryObservation": "control_entry_ref",
    "InvocationEventObservation": "event_ref",
}


def _check_observed_name(value: Any) -> str:
    return _check_token(value, what="native_name", pattern=NATIVE_NAME_RE)


def _check_ref(value: Any, *, what: str) -> str:
    return _check_token(value, what=what)


@dataclass(frozen=True)
class ProjectedArtifactObservation:
    """The Harness reports it materialised the content into the slot."""

    native_name: str
    projection_ref: str

    ATTESTS: ClassVar[frozenset[VerifyState]] = frozenset({VerifyState.PROJECTED})

    def __post_init__(self) -> None:
        _check_observed_name(self.native_name)
        _check_ref(self.projection_ref, what="projection_ref")


@dataclass(frozen=True)
class FileExistenceObservation:
    """Someone saw a file with that name on disk. G11/G12: that is a
    *projection* fact and nothing more — it can never attest `loaded`."""

    native_name: str

    ATTESTS: ClassVar[frozenset[VerifyState]] = frozenset({VerifyState.PROJECTED})

    def __post_init__(self) -> None:
        _check_observed_name(self.native_name)


@dataclass(frozen=True)
class NativeLoaderObservation:
    """The target's own loader was observed having picked the definition up."""

    native_name: str
    loader_ref: str

    ATTESTS: ClassVar[frozenset[VerifyState]] = frozenset({VerifyState.LOADED})

    def __post_init__(self) -> None:
        _check_observed_name(self.native_name)
        _check_ref(self.loader_ref, what="loader_ref")


@dataclass(frozen=True)
class ControlEntryObservation:
    """The target's control entry (menu/tool/endpoint) exposes the definition."""

    native_name: str
    control_entry_ref: str

    ATTESTS: ClassVar[frozenset[VerifyState]] = frozenset({VerifyState.INVOKABLE})

    def __post_init__(self) -> None:
        _check_observed_name(self.native_name)
        _check_ref(self.control_entry_ref, what="control_entry_ref")


@dataclass(frozen=True)
class InvocationEventObservation:
    """An independent native invocation event (e.g. `subagent_spawned`,
    capability-matrix C-2) named this definition."""

    native_name: str
    event_ref: str

    ATTESTS: ClassVar[frozenset[VerifyState]] = frozenset({VerifyState.USED})

    def __post_init__(self) -> None:
        _check_observed_name(self.native_name)
        _check_ref(self.event_ref, what="event_ref")


Observation = Union[
    ProjectedArtifactObservation, FileExistenceObservation, NativeLoaderObservation,
    ControlEntryObservation, InvocationEventObservation, "ObservationSet",
]

#: The JSON observation kinds the contract-shaped `verify(context, observed)`
#: accepts as an observed readback (the contract passes a plain JsonValue —
#: C0's service hands it `NativeReadback.observed_value`; Q3 defines this
#: closed shape as the facet's readback protocol and documents it).
OBSERVATION_KINDS: Mapping[str, str] = {
    "projection": "projection_ref",
    "file-existence": "",
    "loader": "loader_ref",
    "control-entry": "control_entry_ref",
    "invocation-event": "event_ref",
}

_CLASSES_BY_KIND: Mapping[str, type] = {
    "projection": ProjectedArtifactObservation,
    "file-existence": FileExistenceObservation,
    "loader": NativeLoaderObservation,
    "control-entry": ControlEntryObservation,
    "invocation-event": InvocationEventObservation,
}


def observation_from_json(value: Any) -> Observation | None:
    """Parse one readback (or a list of same-name readbacks) into the ladder.

    Returns None when the payload is not an interpretable observation — the
    caller must then report `VerificationUnknown`, never a guessed state.
    """
    entries = value
    if isinstance(entries, Mapping):
        entries = [entries]
    if not isinstance(entries, (tuple, list)) or not entries:
        return None
    observations = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            return None
        kind = entry.get("kind")
        if kind not in OBSERVATION_KINDS:
            return None
        cls = _CLASSES_BY_KIND[kind]
        fields: dict[str, Any] = {}
        if dataclasses.is_dataclass(cls):
            names = [f.name for f in dataclasses.fields(cls)]
        else:  # pragma: no cover - defensive
            return None
        for name in names:
            if name == "native_name":
                fields[name] = entry.get("native_name")
            else:
                fields[name] = entry.get("ref")
        if any(v is None for v in fields.values()):
            return None
        try:
            observations.append(cls(**fields))
        except (errors.DomainError, AssessmentError, ValueError):
            return None
    if len(observations) == 1:
        return observations[0]
    try:
        return ObservationSet(tuple(observations))
    except errors.DomainError:
        return None


def attested_states(observation: Observation) -> frozenset[VerifyState]:
    if isinstance(observation, ObservationSet):
        out: frozenset[VerifyState] = frozenset()
        for entry in observation.observations:
            out |= attested_states(entry)
        return out
    if hasattr(observation, "ATTESTS"):
        return observation.ATTESTS
    raise errors.DomainError(
        errors.DEFINITION_INVALID,
        detail=f"{type(observation).__name__} is not an observation type",
    )


def as_state_machine(observation: Observation) -> VerifyState:
    """The highest rung whose OWN observation type is present.

    Each rung is attested only by its own input type — a file sighting can
    never lift to `loaded`, and a loader claim can never lift to `invokable`
    or `used`. An invocation event alone does reach `used` (contracts.md
    §C4: 「只有原生调用事件能记录 used」), because the event IS that fact;
    what it can never do is be *inferred* from anything weaker.
    """
    attests = attested_states(observation)
    for rung in reversed(_LADDER):
        if rung in attests:
            return rung
    return VerifyState.UNKNOWN


def require_state(observation: Observation, wanted: VerifyState) -> VerifyState:
    """Gate: claim `wanted` only if the observations actually support it."""
    if not isinstance(wanted, VerifyState):
        wanted = VerifyState(wanted)
    attests = attested_states(observation)
    if wanted is VerifyState.UNKNOWN:
        return as_state_machine(observation)
    if wanted not in attests:
        name = getattr(observation, "native_name", None)
        raise errors.DomainError(
            errors.LOAD_UNVERIFIED,
            item_id=name,
            detail=(f"cannot report {wanted.value!r}: {wanted.value} requires "
                    f"{RUNG_REQUIREMENT[wanted]}; attested rungs: "
                    f"{sorted(s.value for s in attests) or ['none']}"),
        )
    return wanted


@dataclass(frozen=True)
class ItemVerification:
    native_name: str
    state: VerifyState
    attested: frozenset[VerifyState] = frozenset()
    basis: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, VerifyState):
            object.__setattr__(self, "state", VerifyState(self.state))


@dataclass(frozen=True)
class VerifyResult:
    items: tuple[ItemVerification, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))

    def state_of(self, native_name: str) -> VerifyState:
        for item in self.items:
            if item.native_name == native_name:
                return item.state
        return VerifyState.UNKNOWN

    @property
    def max_state(self) -> VerifyState:
        states = {i.state for i in self.items}
        for rung in reversed(_LADDER):
            if rung in states:
                return rung
        return VerifyState.UNKNOWN


@dataclass(frozen=True)
class ObservationSet:
    """Several observations of the SAME native name, combined for verify."""

    observations: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple):
            object.__setattr__(self, "observations", tuple(self.observations))
        if not self.observations:
            raise errors.DomainError(
                errors.DEFINITION_INVALID,
                detail="an ObservationSet must carry at least one observation",
            )
        names = set()
        for observation in self.observations:
            if not hasattr(observation, "ATTESTS"):
                raise errors.DomainError(
                    errors.DEFINITION_INVALID,
                    detail=f"{type(observation).__name__} is not an observation type",
                )
            names.add(observation.native_name)
        if len(names) != 1:
            raise errors.DomainError(
                errors.TARGET_CONFLICT,
                detail="an ObservationSet must describe exactly one native name",
            )

    @property
    def native_name(self) -> str:
        first = self.observations[0]
        assert isinstance(first, (ProjectedArtifactObservation, FileExistenceObservation,
                                  NativeLoaderObservation, ControlEntryObservation,
                                  InvocationEventObservation))
        return first.native_name


# -- the triad base ------------------------------------------------------------


class ConfigurationAdapter:
    """The §C3 triad: pure `assess` / `compile` / `verify` over one brand,
    speaking the published contract types in and out."""

    adapter_id: str = ""
    harness_id: str = ""
    pinned_version: str = ""
    #: contract descriptor (registration shape). `claims`/`entries`/
    # `native_versions`/`adapter_versions` are the REAL FieldClaim /
    # VersionRange types — this is where per-pin version honesty lives now.
    descriptor: ConfigurationAdapterDescriptor | None = None
    mount_suffix: str = ".md"
    mount_directory: str = intents.MOUNT_DIRECTORY

    # -- context admission (replaces the old TargetDescriptor checks) ------
    def _validate_context(self, context: Any) -> AdapterContext:
        checked = intents.validate_context(context)
        if self.descriptor is None:
            raise errors.DomainError(
                errors.ADAPTER_MISSING, detail=f"adapter {self.adapter_id!r} has no descriptor",
            )
        installation = checked.installation
        if installation.harness_id != self.harness_id:
            raise errors.DomainError(
                errors.TARGET_CONFLICT,
                detail=f"adapter {self.adapter_id!r} does not serve harness "
                       f"{installation.harness_id!r}",
            )
        if checked.entry not in self.descriptor.entries:
            raise errors.DomainError(
                errors.TARGET_CONFLICT,
                detail=f"context entry {checked.entry!r} is not an entry this "
                       f"adapter registered ({list(self.descriptor.entries)})",
            )
        if self.descriptor.adapter_versions.contains(installation.adapter_version) is not True:
            raise errors.DomainError(
                errors.NATIVE_VERSION_UNKNOWN,
                detail=f"this adapter is versioned for pin "
                       f"{self.pinned_version!r}, not adapter version "
                       f"{installation.adapter_version} (G01: an unversioned or "
                       "out-of-pin installation never assesses supported)",
            )
        if installation.native_version is not None and \
                self.descriptor.native_versions.contains(installation.native_version) is not True:
            raise errors.DomainError(
                errors.NATIVE_VERSION_UNKNOWN,
                detail=f"native version {installation.native_version} is outside "
                       f"the pinned range of {self.pinned_version!r}; host facts "
                       "are not pin facts",
            )
        return checked

    def _source_target(self, context: AdapterContext, source: Any):
        checked_source = intents.validate_source(source)
        handle = intents.select_content_target(context, harness_id=self.harness_id)
        return checked_source, handle

    # -- assess --------------------------------------------------------------
    def assess(self, context: Any, request: Any = None) -> RealAssessment:
        """The contract `Assessment`; the pin/cell detail lives in `assess_detail`."""
        return self.assess_detail(context, request).to_real()

    def assess_detail(self, context: Any, request: Any = None) -> Assessment:
        raise NotImplementedError

    # -- compile ---------------------------------------------------------------
    def compile(self, context: Any, collection: Sequence[intents.ManagedItem],
                source: Any, *, native_names: frozenset[str] | None = None,
                stage_content: Any = None,
                secret_bindings: Sequence[tuple[str, str]] = ()) -> IntentSet:
        raise NotImplementedError

    # -- verify: internal ladder over a REAL intent set -------------------------
    def managed_names(self, intent_set: IntentSet) -> set[str]:
        """The native names this adapter's compiled set mounted."""
        names: set[str] = set()
        for intent in intent_set.intents:
            if isinstance(intent, intents.MountContent):
                names.add(intents.mount_native_name(
                    intent, suffix=self.mount_suffix, directory=self.mount_directory))
        return names

    def verify_observations(self, observation: Observation,
                            intent_set: Any) -> VerifyResult:
        """The ladder state machine, now over the real `IntentSet`.

        The old closed-slot check ('a set compiled for slot X cannot be
        verified here') is replaced by the contract's own ownership rule:
        every intent must carry this facet's source, and C0's merge already
        refuses any set whose source differs from the authorized submission.
        """
        if not isinstance(intent_set, IntentSet):
            raise errors.DomainError(
                errors.DEFINITION_INVALID,
                detail="verify needs the real ordessa_harness_api IntentSet it observes",
            )
        for intent in intent_set.intents:
            if intent.source.facet_id != intents.FACET_ID:
                raise errors.DomainError(
                    errors.TARGET_CONFLICT,
                    detail="intent set carries a foreign facet; this adapter "
                           "only verifies its own compiled output",
                )
        if isinstance(observation, ObservationSet):
            for entry in observation.observations:
                self._on_observation_kind(entry)
        else:
            self._on_observation_kind(observation)
        names = self.managed_names(intent_set)
        observed_name = observation.native_name
        state = as_state_machine(observation)
        attests = attested_states(observation)
        items = []
        for name in sorted(names):
            if name == observed_name:
                items.append(ItemVerification(
                    native_name=name, state=state, attested=attests,
                    basis="ladder over the provided observations only",
                ))
            else:
                items.append(ItemVerification(
                    native_name=name, state=VerifyState.UNKNOWN,
                    basis="no observation for this item (data-model: no "
                          "mechanism means Unknown, never false)",
                ))
        if observed_name not in names:
            items.append(ItemVerification(
                native_name=observed_name, state=VerifyState.UNKNOWN, attested=attests,
                basis="observed name is not part of the compiled intent set",
            ))
        return VerifyResult(items=tuple(items))

    # -- verify: contract-shaped -----------------------------------------------
    def verify(self, context: Any, observed: Any) -> Union[Match, Mismatch, VerificationUnknown]:
        """Real `Verification` from a JSON observation.

        `Match` (C0's sole path to `Confirmed`,
        `configuration_service.py:303-305`) requires a LOADED-rung-or-higher
        observation: a file-existence/projection readback yields
        `VerificationUnknown`, never `Match` — 「文件生成即记 loaded」 stays
        unrepresentable after the re-basing.
        """
        checked = intents.validate_context(context)
        del checked
        try:
            observation = observation_from_json(observed)
        except Exception:  # noqa: BLE001 - malformed readback is not a crash path
            observation = None
        if observation is None:
            return VerificationUnknown(
                "the observed readback is not an interpretable target "
                "observation; state stays Unknown, never guessed (data-model: "
                "no mechanism means Unknown)")
        try:
            entries = (observation.observations if isinstance(observation, ObservationSet)
                       else (observation,))
            for entry in entries:
                self._on_observation_kind(entry)
        except errors.DomainError as exc:
            fallback = "observation cannot be attributed to this target at this pin"
            return Mismatch(f"{exc.code}: {exc.detail or fallback}")
        state = as_state_machine(observation)
        if state in (VerifyState.LOADED, VerifyState.INVOKABLE, VerifyState.USED):
            evidence = self._top_rung_evidence(observation, state)
            return Match(evidence)
        return VerificationUnknown(
            "only a projection/file-existence observation was made: "
            f"`{state.value}` is not loader evidence ({RUNG_REQUIREMENT[VerifyState.LOADED]}); "
            "a materialised file can never yield `loaded` (G11/G12)")

    def _top_rung_evidence(self, observation: Observation, state: VerifyState) -> str:
        entries = (observation.observations
                   if isinstance(observation, ObservationSet) else (observation,))
        for entry in reversed(tuple(entries)):
            if state in getattr(entry, "ATTESTS", frozenset()):
                ref_field = _REF_FIELD.get(type(entry).__name__)
                value = getattr(entry, ref_field, None) if ref_field else None
                return (f"{type(entry).__name__}:{entry.native_name}@"
                        f"{value or 'observed'}")
        return f"{state.value}:{getattr(observation, 'native_name', '?')}"

    # Hook for brands whose target *provably* has no loader/entry today:
    # subclasses raise to refuse an observation the target cannot have
    # produced (see Codex/Pi — G12/G14).
    def _on_observation_kind(self, observation: Observation) -> None:
        """Override to refuse observations the target cannot have produced."""


__all__ = [
    "AdapterContext", "AdapterRefusal", "Assessment", "AssessmentError",
    "AssessmentState", "CellVerdict", "ConfigurationAdapter",
    "ConfigurationAdapterDescriptor", "ControlEntryObservation",
    "DOMAIN_TO_CONTRACT_CODE", "FieldClaim", "FileExistenceObservation",
    "IntentSet", "IntentSource", "InvocationEventObservation",
    "ItemVerification", "Match", "Mismatch", "OBSERVATION_KINDS",
    "ObservationSet", "ProjectedArtifactObservation", "RealTargetDescriptor",
    "TargetHandle", "VerificationUnknown", "VersionRange", "adapter_refusal_for",
    "as_state_machine", "attested_states", "observation_from_json",
    "require_state",
]
