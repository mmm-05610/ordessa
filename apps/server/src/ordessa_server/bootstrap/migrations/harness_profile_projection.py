"""Explicit read-only historical Profile projection from a fixed modern revision.

This module performs no discovery, filesystem IO, registration, mutation or
provider admission. Historical provenance is a fact, not an authenticity or
native execution grant. The selected ProfileService enforces Environment and
read ACL before any provenance is exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from ordessa_execution_agents.profiles import ProfileRevision, ProfileRevisionRef, ProfileService, encode_content
from .harness_profile_history import CapturedHarnessProfile, validated_capture
from .harness_profile_import import PROVENANCE_FIELD


@dataclass(frozen=True)
class HistoricalHarnessRef:
    harness_type: str
    profile_id: str
    revision: int
    digest: str


@dataclass(frozen=True)
class HistoricalProfileView:
    modern_ref: ProfileRevisionRef | None
    historical_ref: HistoricalHarnessRef
    canonical_envelope_json: str

    def envelope(self) -> dict:
        """Return a fresh copy of the verified old envelope, never a live map."""
        return json.loads(self.canonical_envelope_json)


def _view(value: dict, expected: HistoricalHarnessRef,
          modern_ref: ProfileRevisionRef | None) -> HistoricalProfileView:
    if type(expected) is not HistoricalHarnessRef:
        raise TypeError("explicit historical Profile reference required")
    # Recheck the persisted dict under the original digest algorithm. This is
    # self-consistency only: a caller may create such JSON without an importer.
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    capture = CapturedHarnessProfile(expected.harness_type, expected.profile_id,
                                     expected.revision, expected.digest,
                                     canonical.encode("utf-8"))
    validated = validated_capture(capture)
    return HistoricalProfileView(modern_ref, expected,
                                 json.dumps(validated, sort_keys=True,
                                            separators=(",", ":"), ensure_ascii=False))


def read_imported_historical_revision(*, profiles: ProfileService,
                                      modern_ref: ProfileRevisionRef,
                                      expected: HistoricalHarnessRef) -> HistoricalProfileView:
    """Audit an exact imported revision through its admitted modern read ACL."""
    if type(profiles) is not ProfileService or type(modern_ref) is not ProfileRevisionRef:
        raise TypeError("admitted ProfileService and fixed modern revision required")
    revision = profiles.get_revision(modern_ref)
    return project_imported_historical_revision(revision=revision, expected=expected)


def project_imported_historical_revision(*, revision: ProfileRevision,
                                         expected: HistoricalHarnessRef) -> HistoricalProfileView:
    """Project one already authorized immutable revision without a second read.

    The caller must obtain this revision through ProfileService.select_current
    or get_revision; historical metadata never creates its own read grant.
    """
    if type(revision) is not ProfileRevision:
        raise TypeError("admitted Profile revision required")
    metadata = encode_content(revision.content).get("metadata") or {}
    value = metadata.get(PROVENANCE_FIELD)
    if type(value) is not dict:
        raise ValueError("HISTORICAL_PROFILE_PROVENANCE_MISSING")
    return _view(value, expected, revision.ref)


def select_current_imported_historical(*, profiles: ProfileService, profile_id: str,
                                       expected: HistoricalHarnessRef) -> HistoricalProfileView:
    """Select only the current unarchived imported revision; no old FS fallback."""
    if type(profiles) is not ProfileService:
        raise TypeError("admitted ProfileService required")
    revision = profiles.select_current(profile_id)
    view = project_imported_historical_revision(revision=revision, expected=expected)
    if view.envelope()["disabled"]:
        raise ValueError("PROFILE_DISABLED")
    return view


def read_captured_historical(*, captured: CapturedHarnessProfile,
                             expected: HistoricalHarnessRef) -> HistoricalProfileView:
    """Explicit source audit; no import, modern authority or execution claim."""
    return _view(validated_capture(captured), expected, None)


def resolve_captured_historical(*, captured: CapturedHarnessProfile,
                                expected: HistoricalHarnessRef) -> HistoricalProfileView:
    """Preserve old exact-ref disabled refusal for explicit historical reads."""
    view = read_captured_historical(captured=captured, expected=expected)
    if view.envelope()["disabled"]:
        raise ValueError("PROFILE_DISABLED")
    return view
