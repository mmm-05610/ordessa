"""SandboxOptionCatalogue — per (harnessId, nativeVersionRange) native options.

FR-05 / §C2. A UI may never guess an option list from a Harness brand name;
the menu is assembled only for pins this repository actually measures:

- the pinned families/versions come from ``plugins/harness/.../harnesses.toml``
  read with ``tomllib`` (no harness import),
- the per-brand option vocabulary, sources, platform limits and coverage
  come from the API's brand matrix (``BRAND_OPTIONS`` via ``describe_sandbox``),
- administrator locking is delegated to the API's ``SandboxCeiling``.

A lookup for anything else — an unpinned version, or a family with no closed
native-sandbox schema (opencode/hermes/dsh/qwen/kilo) — returns an explicit
``unknown`` result with **no menu**, and selecting from it refuses.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from ordessa_sandbox_api import (
    BRAND_OPTIONS,
    SandboxApiError,
    SandboxCeiling,
    SandboxDescription,
    SandboxErrorCode,
    SandboxOption,
    describe_sandbox,
)

#: harness_type values (harnesses.toml) that have a closed native-sandbox
#: vocabulary measured in the API; every other family gets no menu.
SANDBOX_BRANDS = frozenset(BRAND_OPTIONS)


class CatalogueStatus(str, Enum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


@dataclass(frozen=True)
class CatalogueResult:
    status: CatalogueStatus
    harness_id: str
    native_version: str
    options: tuple[SandboxOption, ...]
    description: SandboxDescription | None
    reason: str = ""
    source: str = ""

    @property
    def locked_by_administrator(self) -> bool:
        return self.description.locked_by_administrator if self.description else False

    def menu(self) -> tuple[SandboxOption, ...]:
        """The only options a UI may show; unknown gives no menu at all."""
        return self.description.options_for_ui() if self.description else ()

    def select(self, option_id: str) -> SandboxOption:
        if self.description is None:
            raise SandboxApiError(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                f"no option list is registered for ({self.harness_id!r}, "
                f"{self.native_version!r}); selecting from an unknown pin "
                "would invent a menu",
                suggestion="describe the current pin first; unproven options "
                           "are never offered")
        return self.description.select(option_id)


@dataclass(frozen=True)
class _Pin:
    harness_id: str
    native_version: str
    source: str


class SandboxOptionCatalogue:
    """The backend's authoritative option/version management (T04)."""

    def __init__(self, pins: Sequence[_Pin] = ()) -> None:
        self._pins: tuple[_Pin, ...] = tuple(pins)

    # ------------------------------------------------------------- building

    @classmethod
    def from_repo(cls, *, harnesses_toml: Path | str) -> "SandboxOptionCatalogue":
        """Register every pinned sandbox-brand family from the real
        ``harnesses.toml`` (the only repo-side family/version/capability
        registry). Families without a closed native-sandbox schema are not
        registered and therefore answer ``unknown`` — never a guessed menu.
        """
        path = Path(harnesses_toml)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        pins: list[_Pin] = []
        for entry in data.get("harness", ()):
            identity = entry.get("identity", {})
            harness_type = str(identity.get("harness_type", ""))
            version = str(identity.get("version", ""))
            if harness_type in SANDBOX_BRANDS and version:
                pins.append(_Pin(
                    harness_id=harness_type,
                    native_version=version,
                    source=f"{path.name}: [[harness]] harness_type="
                           f"{harness_type!r} version={version!r} "
                           f"(capabilities={entry.get('capabilities', [])!r})"))
        return cls(pins)

    # -------------------------------------------------------------- queries

    def known_pin(self, harness_id: str, native_version: str) -> bool:
        return any(p.harness_id == harness_id and p.native_version == native_version
                   for p in self._pins)

    def source_for(self, harness_id: str, native_version: str) -> str:
        for p in self._pins:
            if p.harness_id == harness_id and p.native_version == native_version:
                return p.source
        return ""

    def lookup(self, harness_id: str, native_version: str | None, *,
               platform_os: str = "linux", platform_version: str = "",
               admin_lock: SandboxCeiling | None = None,
               provider_state: str = "ready") -> CatalogueResult:
        """Options for one pin: version/source/platform/coverage/locked.

        An unregistered pin returns ``unknown`` with an empty option set —
        the catalogue never falls back to a brand-wide menu. A busy/deferred
        provider state is refused by the API's describe (§C4).
        """
        if native_version is None or not self.known_pin(harness_id, native_version):
            return CatalogueResult(
                status=CatalogueStatus.UNKNOWN,
                harness_id=harness_id,
                native_version=str(native_version or ""),
                options=(),
                description=None,
                reason=f"({harness_id!r}, {native_version!r}) is not a pinned "
                       "native-sandbox family/version in this repository; no "
                       "menu is invented")
        description = describe_sandbox(
            harness_id=harness_id, native_version=native_version,
            platform_os=platform_os, platform_version=platform_version,
            admin_lock=admin_lock, provider_state=provider_state)
        return CatalogueResult(
            status=CatalogueStatus.AVAILABLE,
            harness_id=harness_id,
            native_version=native_version,
            options=description.options,
            description=description,
            source=self.source_for(harness_id, native_version))
