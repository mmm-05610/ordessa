"""Harness-owned observation for offline Skill loading proofs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pacthold_runtime_compat.runtime_composition.protocol import content_digest


@dataclass(frozen=True)
class SkillLoadedEvidence:
    level: str
    skill_id: str
    revision: int
    digest: str
    loaded: bool
    marker: str


def observe_loaded_skill(*, skill_id: str, revision: int, digest: str, guest_root: Path) -> SkillLoadedEvidence:
    """Read the native target's manifest and emit only bounded evidence.

    The caller is a fake/native Harness target, not the Skill provider or
    sandbox.  Full content and source paths are intentionally discarded.
    """
    manifest = Path(guest_root) / "SKILL.md"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("SKILL_NATIVE_MANIFEST_NOT_FOUND")
    if content_digest(Path(guest_root)) != digest:
        raise ValueError("SKILL_NATIVE_DIGEST_MISMATCH")
    return SkillLoadedEvidence("LOADED", skill_id, revision, digest, True, f"SKILL_LOADED:{skill_id}:{digest}")


def observe_loaded_marker(*, marker: str, skill_id: str, revision: int, digest: str) -> SkillLoadedEvidence:
    """Accept a bounded marker emitted by a Harness-owned fake target."""
    expected = f"SKILL_LOADED:{skill_id}:{digest}"
    observed = expected if expected in "".join(marker.split()) else ""
    if not observed:
        raise ValueError("SKILL_LOADED_MARKER_MISMATCH")
    return SkillLoadedEvidence("LOADED", skill_id, revision, digest, True, expected)
