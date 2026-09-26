"""The isolated guest home: one root, generic targets, no Harness knowledge.

Every Harness home is a projection inside one execution-private guest directory
(:data:`GUEST_HOME`): read-only configuration *files* and one bounded writable
*state* directory, both named by a deployment through the generic
``projectionFiles`` / ``stateProjection`` fields.  Nothing here knows which
Harness declared what - this module owns the *layout grammar* only, so the
Server, the Worker and bwrap agree on one syntax and on one refusal set.

The guest home is never the host home: it is a directory the execution's own
mount namespace creates (``--dir``), and the only thing ever bound onto it is a
reviewed bundle file or the one declared state directory.  That is what makes a
Harness's *default* location (``$HOME``-derived, or ``$XDG_*``-derived) and its
*explicit* variable resolve to the same projection: the deployment names the
target, and the guest environment derives the same path from the one home root.

Two relations make the difference between "a projection" and "a shadowed
projection", and both are settled here rather than hoped for:

* a read-only file *inside* the writable state directory is a **protected
  state path**: the read-only overlay is what the guest sees, so the same
  relative name must never be captured into, or restored from, a native
  checkpoint (an overlay that merely happens to hide it is not a guarantee);
* the state directory may never live inside a projected read-only target
  (**reverse shadowing**), because no bind order can express both meanings.

A symbolic link is not expressible as a target either: every segment is a
literal name, so a declaration cannot smuggle link resolution into the layout.
The sources those targets bind are required to be real, non-symlinked files
where they are read (see the deployment loader and the mount compiler), which
is the other half of the same rule.

Grammar (version 1)::

    target      := GUEST_HOME "/" segment ("/" segment){0,5}   # 1..6 segments
    segment     := [A-Za-z0-9._-]{1,64}, never "." or ".."

A canonical path is exactly its ``PurePosixPath`` spelling: no empty segment
(``//``), no trailing slash, no ``.``/``..``, no NUL, no backslash and no
control character.  ``projectionFiles.target`` names a *file*;
``stateProjection.target`` names a *directory*.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Iterable

from pacthold.extensions.runtime_composition import ProjectionRejected

#: The one isolated home root inside the execution's mount namespace. It is
#: created by the sandbox compiler and is never the host home or a Windows
#: profile root.
GUEST_HOME = "/runtime/home"
HOME_TARGET_PREFIX = GUEST_HOME + "/"
#: Target shape limits. Six segments reach
#: ``/runtime/home/.local/share/<harness>/<sub>/<file>``, which is as deep as a
#: reviewed layout needs to be while staying readable in a Worker argv.
MAX_TARGET_SEGMENTS = 6
MAX_TARGET_SEGMENT_LENGTH = 64
#: The two target kinds a deployment may declare.
PROJECTION_FILE = "file"
PROJECTION_DIRECTORY = "directory"
_TARGET_KINDS = frozenset({PROJECTION_FILE, PROJECTION_DIRECTORY})
_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,%d}\Z" % MAX_TARGET_SEGMENT_LENGTH)


class HomeProjectionRejected(ProjectionRejected):
    """A typed refusal of one guest-home projection target or relation.

    It is a :class:`ProjectionRejected`, so every caller that already refuses a
    rejected projection refuses this too, while :attr:`code` names the exact
    rule that was broken.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _reject(code: str, message: str) -> None:
    raise HomeProjectionRejected(code, message)


def home_projection_target(target: Any, *, kind: str) -> str:
    """Validate one declared projection target and return it unchanged.

    ``kind`` is :data:`PROJECTION_FILE` or :data:`PROJECTION_DIRECTORY`; the
    distinction is what keeps a deployment from pointing a *file* projection at
    a directory spelling and the other way round.  The target is returned
    exactly as declared: a valid target is already canonical, so there is
    nothing to normalize - normalizing would mean accepting a spelling whose
    meaning depended on resolution.
    """
    if kind not in _TARGET_KINDS:
        _reject("HOME_PROJECTION_KIND_INVALID", f"unknown projection target kind: {kind!r}")
    if not isinstance(target, str) or not target:
        _reject("HOME_PROJECTION_TARGET_INVALID", f"a {kind} target must be a non-empty string")
    if any(character == "\x00" or character == "\\"
           or ord(character) < 0x20 or ord(character) == 0x7F for character in target):
        _reject("HOME_PROJECTION_TARGET_INVALID",
                f"a {kind} target may not carry NUL, a backslash or a control character")
    if not target.startswith(HOME_TARGET_PREFIX):
        _reject("HOME_PROJECTION_TARGET_OUTSIDE_HOME",
                f"a {kind} target must be inside {GUEST_HOME}")
    if target.endswith("/") or "//" in target:
        _reject("HOME_PROJECTION_TARGET_INVALID",
                f"a {kind} target must be canonical (no trailing slash, no empty segment)")
    segments = target[len(HOME_TARGET_PREFIX):].split("/")
    if not 1 <= len(segments) <= MAX_TARGET_SEGMENTS:
        _reject("HOME_PROJECTION_TARGET_INVALID",
                f"a {kind} target must name 1..{MAX_TARGET_SEGMENTS} segments below {GUEST_HOME}")
    for segment in segments:
        if segment in {".", ".."} or _SEGMENT.fullmatch(segment) is None:
            _reject("HOME_PROJECTION_TARGET_INVALID",
                    f"a {kind} target segment is not a plain name: {segment!r}")
    if str(PurePosixPath(target)) != target:
        _reject("HOME_PROJECTION_TARGET_INVALID",
                f"a {kind} target is not its own canonical spelling: {target!r}")
    return target


def protected_state_paths(
    projection_targets: Iterable[str], state_target: str | None,
) -> tuple[str, ...]:
    """Derive the read-only paths the writable state subtree must protect.

    The protected set is *never* hardcoded per Harness: it is exactly "the
    declared read-only projection files that sit inside the declared writable
    state directory", named relative to that directory.  A native checkpoint
    must not capture them (they are not state) and must not restore them (a
    restored copy would be a second, unreviewed configuration).

    Returns the protected relative paths, sorted, or an empty tuple when the
    deployment declares no state projection.  Raises
    :class:`HomeProjectionRejected` for a declaration whose two halves cannot
    both be expressed:

    * a projection target equal to the state target,
    * a projection target strictly inside another projection target (one file
      cannot also be another file's parent directory),
    * a state target strictly inside a projection target (reverse shadowing).
    """
    projections = tuple(projection_targets)
    seen: set[str] = set()
    for target in projections:
        if target in seen:
            _reject("HOME_PROJECTION_TARGET_DUPLICATED",
                    f"{target} is declared as a projection target twice")
        seen.add(target)
        if not target.startswith(HOME_TARGET_PREFIX):
            _reject("HOME_PROJECTION_TARGET_OUTSIDE_HOME",
                    f"a projection target must be inside {GUEST_HOME}")
    for index, target in enumerate(projections):
        for other in projections[index + 1:]:
            if target.startswith(other + "/") or other.startswith(target + "/"):
                _reject("HOME_PROJECTION_TARGET_OVERLAPS",
                        f"{target} and {other} cannot both be projected files")
    if state_target is None:
        return ()
    if not state_target.startswith(HOME_TARGET_PREFIX):
        _reject("HOME_PROJECTION_TARGET_OUTSIDE_HOME",
                f"a state target must be inside {GUEST_HOME}")
    protected: list[str] = []
    for target in projections:
        if target == state_target:
            _reject("HOME_PROJECTION_STATE_COLLISION",
                    f"the state target {state_target} is also declared as a projection file")
        if target.startswith(state_target + "/"):
            protected.append(target[len(state_target) + 1:])
        elif state_target.startswith(target + "/"):
            _reject("HOME_PROJECTION_STATE_SHADOWED",
                    f"the state target {state_target} is inside the projected file {target}")
    if len(set(protected)) != len(protected):
        _reject("HOME_PROJECTION_PROTECTED_CONFLICT",
                "two projection files resolve to the same protected state path")
    return tuple(sorted(protected))


def is_protected_state_path(protected: Iterable[str], relative: str) -> bool:
    """Whether one state-relative path is owned by a read-only projection."""
    return relative in frozenset(protected)
