"""Brand-native permission modes, kept per brand (FR-03).

`allow`/`ask`/`deny` are Ordessa's interpretation results; `plan`, `auto`,
`bypassPermissions`, `untrusted`, `on-failure` and friends are a brand's own
names for its own enforcement. Nothing here maps one brand's spelling onto
another's, and a brand with no declared vocabulary is `unsupported`, never an
empty mode set that "probably means ask".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from .codes import PolicyRefusal

__all__ = ["BRAND_NATIVE_MODES", "BrandMode", "declared_native_modes"]

_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,128}\Z")

#: First-hand vocabularies only, as the pinned adapters declare them. An empty
#: tuple is a real answer: that brand has no native permission mode to name.
BRAND_NATIVE_MODES: Final[Mapping[str, tuple[str, ...]]] = {
    "claude-code": ("default", "plan", "acceptEdits", "auto", "bypassPermissions"),
    "codex": ("untrusted", "on-request", "on-failure", "never"),
    # Pi's gate is an optional extension, not a declared native mode set; naming
    # one here would invent a capability the product has not verified.
    "pi": (),
}


def declared_native_modes(brand: Any) -> tuple[str, ...]:
    """The modes one brand declares; an unknown brand is refused, not guessed."""
    if not isinstance(brand, str) or _TEXT_OK.fullmatch(brand) is None:
        raise PolicyRefusal("PERMISSION_BRAND_UNSUPPORTED", source="brand.declared_native_modes",
                            target=None if brand is None else type(brand).__name__)
    modes = BRAND_NATIVE_MODES.get(brand)
    if modes is None:
        raise PolicyRefusal("PERMISSION_BRAND_UNSUPPORTED", source="brand.declared_native_modes",
                            target=brand)
    return modes


@dataclass(frozen=True)
class BrandMode:
    """A (brand, mode) pair. Two brands sharing a spelling do not share a mode."""

    brand: str
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TEXT_OK.fullmatch(self.name) is None \
                or not self.name.strip():
            raise PolicyRefusal("PERMISSION_MODE_UNSUPPORTED", source="brand.BrandMode",
                                target=None if isinstance(self.name, str) else type(
                                    self.name).__name__)
        if self.name not in declared_native_modes(self.brand):
            raise PolicyRefusal("PERMISSION_MODE_UNSUPPORTED", source="brand.BrandMode",
                                target=f"{self.brand}:{self.name}")

    @classmethod
    def declare(cls, brand: Any, name: Any) -> "BrandMode":
        return cls(brand=brand, name=name)

    @classmethod
    def known_brands(cls) -> Sequence[str]:
        return tuple(BRAND_NATIVE_MODES)

    def __str__(self) -> str:
        return f"{self.brand}:{self.name}"
