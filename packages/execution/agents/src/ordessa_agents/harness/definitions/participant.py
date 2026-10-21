"""Public evidence DTOs for T007-01 participant/surface/scope adaptation.

Thin adapter vocabulary only: the Harness keeps its own start/connect/close
lifecycle untouched; these frozen facts describe what a participant instance
observed about its managed scope so the caller can hand Environment lifecycle
facts (``mark_object_management`` / ``drain`` / ``retire`` /
``register_settlement``) honest closure evidence.  This module is NOT a second
lifecycle implementation and never drives the Environment itself.

Field semantics (aligned with ``pacthold.environment.Environment``, order 004):

* ``managed_scope`` — what the participant could see of the scope it was
  exiting: ``complete`` (whole scope observed), ``partial`` (some of it),
  ``opaque`` (cannot see inside at all).  Per T007-07 an owned instance with
  ``partial``/``opaque`` scope does NOT carry sufficient exit evidence and
  must stay ``retire-pending``.
* ``object_discovery_completeness`` — the same closed scale, recorded for the
  objects discovered inside that scope; it travels into the settlement notes
  as-is so consumers weigh it instead of the adapter hiding it.
* ``exit_contract`` — the three management kinds of
  ``Environment.mark_object_management``: an ``owned`` process owes scope
  evidence on exit, a ``borrowed`` one only releases its usage (no kill path),
  and a ``static-projection`` keeps its content while the relation closes.
* ``surface_ids`` — the logical surfaces the participant exposed.
* ``evidence_digest`` — sha256 hex digest of the harness-side evidence bundle
  this record summarises (same pattern as the C4 native receipt digests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from .errors import ContractError

__all__ = [
    "ParticipantEvidence",
    "from_settlement_notes",
    "to_settlement_notes",
]

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")

_NOTE_PREFIX = "participant-exit:"

#: managed_scope / object_discovery_completeness — closed scale (T007-07).
SCOPES = frozenset({"complete", "partial", "opaque"})

#: exit_contract — exactly the Environment.mark_object_management three values.
EXIT_CONTRACTS = frozenset({"owned", "borrowed", "static-projection"})

#: Late-object cleanup disposition per exit contract (settlement wording).
_DISPOSITIONS = {
    "owned": "scope-evidence-required",
    "borrowed": "release-only",
    "static-projection": "content-preserved",
}

_MANAGED_SCOPE = Literal["complete", "partial", "opaque"]
_DISCOVERY = Literal["complete", "partial", "opaque"]
_EXIT_CONTRACT = Literal["owned", "borrowed", "static-projection"]

RequiredScope = Literal["sufficient", "insufficient"]

_KNOWN_NOTE_KEYS = frozenset(
    {"managed_scope", "object_discovery", "exit_contract", "exit_disposition",
     "scope_evidence", "evidence_digest"}
)


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContractError(f"invalid {name}")


@dataclass(frozen=True)
class ParticipantEvidence:
    """What one participant instance recorded while exiting its scope.

    A frozen observation record — never a command.  Insufficiency is
    represented, not hidden: ``partial``/``opaque`` scope on an ``owned``
    exit stays visible so retirement can honestly remain pending.
    """

    managed_scope: _MANAGED_SCOPE
    object_discovery_completeness: _DISCOVERY
    exit_contract: _EXIT_CONTRACT
    surface_ids: tuple[str, ...]
    evidence_digest: str
    kind: Literal["participant-evidence"] = field(default="participant-evidence", init=False)

    def __post_init__(self) -> None:
        if self.managed_scope not in SCOPES:
            raise ContractError(f"invalid managed_scope {self.managed_scope!r}")
        if self.object_discovery_completeness not in SCOPES:
            raise ContractError(
                f"invalid object_discovery_completeness {self.object_discovery_completeness!r}"
            )
        if self.exit_contract not in EXIT_CONTRACTS:
            raise ContractError(f"invalid exit_contract {self.exit_contract!r}")
        if isinstance(self.surface_ids, (list, tuple)):
            surfaces = tuple(self.surface_ids)
        else:
            raise ContractError("surface_ids must be a tuple of surface ids")
        for surface in surfaces:
            _nonempty(surface, "surface id")
        object.__setattr__(self, "surface_ids", surfaces)
        if not isinstance(self.evidence_digest, str) or not _DIGEST.fullmatch(self.evidence_digest):
            raise ContractError("invalid evidence digest (sha256 hex expected)")

    @property
    def scope_evidence_sufficient(self) -> bool:
        """Whether this record satisfies the exit contract's evidence demand.

        ``owned`` requires a ``complete`` managed scope; ``borrowed`` (release
        only) and ``static-projection`` (content preserved) never owe scope
        evidence, so any honestly recorded scope suffices for them.
        """
        if self.exit_contract == "owned":
            return self.managed_scope == "complete"
        return True


def to_settlement_notes(evidence: ParticipantEvidence) -> tuple[str, ...]:
    """Turn participant evidence into ``Environment.register_settlement`` notes.

    Deterministic, ordered, machine-parseable records of the two exit facts
    that must never be claimed away: how late-discovered objects are cleaned
    up (``exit_disposition``) and whether the stop leaves continuation work
    covered (``scope_evidence``).  Notes describe; they never retire.
    """
    if not isinstance(evidence, ParticipantEvidence):
        raise ContractError("settlement notes need ParticipantEvidence")
    notes = [
        f"{_NOTE_PREFIX}managed_scope={evidence.managed_scope}",
        f"{_NOTE_PREFIX}object_discovery={evidence.object_discovery_completeness}",
        f"{_NOTE_PREFIX}exit_contract={evidence.exit_contract}",
        f"{_NOTE_PREFIX}exit_disposition={_DISPOSITIONS[evidence.exit_contract]}",
        f"{_NOTE_PREFIX}scope_evidence="
        + ("sufficient" if evidence.scope_evidence_sufficient else "insufficient"),
    ]
    notes.extend(f"{_NOTE_PREFIX}surface={surface}" for surface in evidence.surface_ids)
    notes.append(f"{_NOTE_PREFIX}evidence_digest={evidence.evidence_digest}")
    return tuple(notes)


def from_settlement_notes(notes: Iterable[str]) -> ParticipantEvidence:
    """Strict inverse of :func:`to_settlement_notes`.

    Malformed, unknown, duplicated or inconsistent notes are refused — the
    parser never synthesizes an evidence record from a partial set.
    """
    fields: dict[str, str] = {}
    surfaces: list[str] = []
    for note in notes:
        if not isinstance(note, str) or not note.startswith(_NOTE_PREFIX):
            raise ContractError(f"not a participant-exit settlement note: {note!r}")
        payload = note[len(_NOTE_PREFIX):]
        key, sep, value = payload.partition("=")
        if not sep or not key or not value:
            raise ContractError(f"malformed settlement note: {note!r}")
        if key == "surface":
            surfaces.append(value)
            continue
        if key not in _KNOWN_NOTE_KEYS:
            raise ContractError(f"unknown settlement note key {key!r}")
        if key in fields:
            raise ContractError(f"duplicate settlement note key {key!r}")
        fields[key] = value
    required = ("managed_scope", "object_discovery", "exit_contract",
                "exit_disposition", "scope_evidence", "evidence_digest")
    missing = [key for key in required if key not in fields]
    if missing:
        raise ContractError(f"incomplete settlement notes, missing {missing}")
    if fields["managed_scope"] not in SCOPES:
        raise ContractError(f"invalid managed_scope in notes: {fields['managed_scope']!r}")
    if fields["object_discovery"] not in SCOPES:
        raise ContractError(
            f"invalid object_discovery in notes: {fields['object_discovery']!r}"
        )
    if fields["exit_contract"] not in EXIT_CONTRACTS:
        raise ContractError(f"invalid exit_contract in notes: {fields['exit_contract']!r}")
    if fields["exit_disposition"] != _DISPOSITIONS[fields["exit_contract"]]:
        raise ContractError(
            f"exit_disposition {fields['exit_disposition']!r} does not match "
            f"exit_contract {fields['exit_contract']!r}"
        )
    if fields["scope_evidence"] not in ("sufficient", "insufficient"):
        raise ContractError(f"invalid scope_evidence in notes: {fields['scope_evidence']!r}")
    evidence = ParticipantEvidence(
        managed_scope=fields["managed_scope"],  # type: ignore[arg-type]
        object_discovery_completeness=fields["object_discovery"],  # type: ignore[arg-type]
        exit_contract=fields["exit_contract"],  # type: ignore[arg-type]
        surface_ids=tuple(surfaces),
        evidence_digest=fields["evidence_digest"],
    )
    expected = "sufficient" if evidence.scope_evidence_sufficient else "insufficient"
    if fields["scope_evidence"] != expected:
        raise ContractError(
            f"scope_evidence {fields['scope_evidence']!r} contradicts the recorded scope"
        )
    return evidence
