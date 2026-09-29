"""Strictly bounded, read-only observation of native skill discovery.

Scope (FR10, FR12, data-model.md §原生发现项与命名冲突):
`NativeDiscovery` is a read-only view LIMITED TO a given guest/instance
root — it is NOT a SkillRecord, its bodies are never imported into the
Ordessa library, and the observer

* never scans the real `$HOME` (refuses a root at/inside the home dir),
* never follows a symlink out of the given root (symlinked skill dirs and
  SKILL.md files are skipped with a diagnostic, never resolved),
* inherits its budgets from `api/identity.py` (entry count, frontmatter
  bytes), and
* writes nothing at all.

Honest disable state (design: `disable` 只能约束**受管**项; ux.md §原生发
现和错误): a native-discovered row carries `can_be_masked`, and with no
in-repo evidence of any masking control (all brands) the value is the
string ``"unknown"`` — which the UI must render as "无法由 Ordessa 关闭",
never as "已禁用". `disable_outcome_for()` is the single honest
vocabulary for that state.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..api.errors import AssetDomainError
from ..api.identity import MAX_ASSET_ENTRIES, MAX_FRONTMATTER_BYTES
from ..harness_adapters.capabilities import SUPPORTED, UNKNOWN, UNSUPPORTED

#: The stable refusal codes of this observer.
HOME_CODE = "NATIVE_DISCOVERY_HOME_REFUSED"
BUDGET_CODE = "NATIVE_DISCOVERY_BUDGET_EXCEEDED"
ROOT_CODE = "NATIVE_DISCOVERY_ROOT_INVALID"
SLOT_CODE = "NATIVE_DISCOVERY_SLOT_INVALID"

#: The honest answer to "can Ordessa mask this native item?" — no
#: disable_outcome_for() path may ever return "disabled" for a row below.
CANNOT_DISABLE = "unmanaged_native_not_disableable"

#: `disable` constrains managed assignments only (data-model.md §原生发现
#: 项与命名冲突 last paragraph).
ORDISSA_DISABLE_SCOPE = "managed_only"

_BLOCK = re.compile(r"\A---\r?\n(.*?)\r?\n---(\r?\n|\Z)", re.S)
_NAME_FIELD = re.compile(r"^name:[ \t]+(\S.*?)[ \t]*$", re.M)
_MAX_NATIVE_NAME_CHARS = 128
_CATEGORY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class NativeDiscoveryError(AssetDomainError):
    """The observation was refused before reading anything."""


@dataclass(frozen=True)
class DiscoverySlot:
    """A brand-relative place inside the guest root that a brand may scan.

    `relative_path` is relative-only (the Claude-style leading dot of
    `.claude/skills` is allowed; traversal and absolute shapes are not)
    and `category` is the discovery-location category reported to the UI
    (data-model.md: 发现位置类别).
    """

    relative_path: str
    category: str

    def __post_init__(self) -> None:
        value = self.relative_path
        if (not value or value.startswith("/") or value.startswith("~")
                or "\\" in value or "://" in value
                or any(part in ("", ".", "..") for part in value.split("/"))):
            raise NativeDiscoveryError(
                SLOT_CODE, f"slot path {value!r} must be a clean relative path")
        if _CATEGORY.fullmatch(self.category) is None:
            raise NativeDiscoveryError(
                SLOT_CODE, f"slot category {self.category!r} is not a token")


@dataclass(frozen=True)
class NativeDiscovery:
    """One read-only row: 原生发现的 skill, not imported, not managed."""

    native_name: str
    location_category: str
    #: Where the row came from, expressed RELATIVE to the observed root.
    provenance: str
    #: sha256 of the SKILL.md bytes as seen (a fact for identity, not a
    #: load claim — digest facts grade at most `projected` elsewhere).
    content_digest: str
    #: bool only when a brand masking capability was VERIFIED; the honest
    #: default is the string "unknown" (无法由 Ordessa 关闭).
    can_be_masked: bool | str

    @property
    def managed(self) -> bool:
        """Native-discovered rows are never managed content (FR10, G11)."""
        return False

    @property
    def disable_state(self) -> str:
        return disable_outcome_for(self)


@dataclass(frozen=True)
class DiscoveryReport:
    observations: tuple[NativeDiscovery, ...]
    diagnostics: tuple[str, ...]


def _masking_state(masking: str) -> bool | str:
    if masking == SUPPORTED:
        return True
    if masking == UNSUPPORTED:
        return False
    if masking == UNKNOWN:
        return "unknown"
    raise NativeDiscoveryError(SLOT_CODE, f"masking capability {masking!r} invalid")


def disable_outcome_for(observation: NativeDiscovery) -> str:
    """The only honest disable outcome for a native-discovered row.

    `disable` in Ordessa constrains *managed* assignments; a native row
    from the guest/project scope cannot be reported as disabled from here
    — the UI shows CANNOT_DISABLE, never "禁用成功" (ux.md, G11 counter-
    example: 原生项被误报"已禁用").
    """
    if observation.can_be_masked is True:
        # Reachable only with a VERIFIED brand masking port — none exists
        # in-repo; observation rows are constructed with `unknown` unless
        # the caller supplies evidenced capability.
        return "maskable_managed_only"
    if observation.can_be_masked is False:
        return CANNOT_DISABLE
    return CANNOT_DISABLE


def _assert_outside_home(root: Path) -> Path:
    resolved = root.resolve()
    home = Path.home().resolve()
    if resolved == home or resolved.is_relative_to(home):
        raise NativeDiscoveryError(
            HOME_CODE,
            "the observer reads a given guest/instance root only; the real "
            "user home directory is never scanned (FR12)")
    return resolved


def _read_bounded(file_path: Path, *, budget_bytes: int) -> bytes:
    size = file_path.stat().st_size
    if size > budget_bytes:
        raise _BudgetRefused(
            f"SKILL.md exceeds {budget_bytes} bytes frontmatter budget")
    data = file_path.read_bytes()
    if len(data) > budget_bytes:
        raise _BudgetRefused(f"SKILL.md exceeds {budget_bytes} bytes")
    return data


class _BudgetRefused(Exception):
    pass


def _extract_native_name(text: str) -> tuple[str | None, str | None]:
    """(name, diagnostic). Native brands keep their own naming rules —
    unknown per capabilities — so the observer reports the frontmatter
    `name` field when present and falls back to the directory name with a
    diagnostic; it never rejects a native item as "not a skill"."""
    match = _BLOCK.match(text)
    if match is None:
        return None, "no frontmatter block"
    field_match = _NAME_FIELD.search(match.group(1))
    if field_match is None:
        return None, "frontmatter has no name field"
    raw = field_match.group(1).strip().strip("\"'")
    if not raw or len(raw) > _MAX_NATIVE_NAME_CHARS:
        return None, f"native name {raw[:32]!r} is unbounded or empty"
    return raw, None


def observe_native_skills(
    root: Path | str,
    slots: Sequence[DiscoverySlot],
    *,
    masking: str = UNKNOWN,
    budget_entries: int = MAX_ASSET_ENTRIES,
    budget_bytes: int = MAX_FRONTMATTER_BYTES,
) -> DiscoveryReport:
    """Read-only sweep of the GIVEN root's slot directories (G11).

    Refuses: non-directory root, a root at/inside the real `$HOME`,
    over-budget scans. Skips (with diagnostics, never following):
    symlinked slots, symlinked skill dirs, symlinked/oversize/unreadable
    SKILL.md files. Imports nothing into the library — this function has
    no dependency on `library/` and returns metadata rows only.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise NativeDiscoveryError(ROOT_CODE, f"{root!r} is not a directory")
    resolved_root = _assert_outside_home(root_path)
    if budget_entries <= 0 or budget_bytes <= 0:
        raise NativeDiscoveryError(BUDGET_CODE, "budgets must be positive")

    mask = _masking_state(masking)
    observations: list[NativeDiscovery] = []
    diagnostics: list[str] = []
    scanned = 0

    for slot in slots:
        slot_dir = root_path / slot.relative_path
        if slot_dir.is_symlink():
            diagnostics.append(f"slot {slot.relative_path} is a symlink; skipped")
            continue
        if not slot_dir.is_dir():
            diagnostics.append(f"slot {slot.relative_path} absent")
            continue
        # Close the directory handle as soon as it is drained: `sorted`
        # materialises every DirEntry (they stay usable after close), so no
        # fd is held while the per-entry work runs below.
        slot_scan = os.scandir(slot_dir)
        try:
            slot_entries = sorted(slot_scan, key=lambda item: item.name)
        finally:
            slot_scan.close()
        for entry in slot_entries:
            scanned += 1
            if scanned > budget_entries:
                raise NativeDiscoveryError(
                    BUDGET_CODE,
                    f"more than {budget_entries} entries under the observed root")
            if entry.is_symlink():
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: symlinked dir; not followed")
                continue
            if not entry.is_dir():
                continue
            skill_file = Path(entry.path) / "SKILL.md"
            if skill_file.is_symlink():
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}/SKILL.md: symlink; skipped")
                continue
            if not skill_file.is_file():
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: no SKILL.md")
                continue
            # Containment guard: nothing may resolve outside the given root.
            resolved_child = skill_file.parent.resolve()
            if not resolved_child.is_relative_to(resolved_root):
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: escapes root; skipped")
                continue
            try:
                data = _read_bounded(skill_file, budget_bytes=budget_bytes)
            except _BudgetRefused as exc:
                diagnostics.append(f"{slot.relative_path}/{entry.name}: {exc}")
                continue
            except OSError as exc:
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: unreadable ({exc.strerror})")
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: SKILL.md is not utf-8")
                continue
            name, problem = _extract_native_name(text)
            if problem is not None:
                # Fall back to the directory name, honestly diagnosed: a
                # native item keeps its own brand naming rules (unknown —
                # they are still compared conservatively in conflict.py).
                diagnostics.append(
                    f"{slot.relative_path}/{entry.name}: {problem}; "
                    "directory name used")
                name = entry.name
            observations.append(NativeDiscovery(
                native_name=name,
                location_category=slot.category,
                provenance=f"{slot.relative_path}/{entry.name}/SKILL.md",
                content_digest="sha256:" + hashlib.sha256(data).hexdigest(),
                can_be_masked=mask,
            ))
    return DiscoveryReport(observations=tuple(observations),
                           diagnostics=tuple(diagnostics))
