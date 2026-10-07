"""`(harnessId, nativeVersionRange)` keys: bounded ranges and overlap detection.

The §C2 contribution is keyed by `(harnessId, nativeVersionRange)` with
uniqueness and overlap refused **at composition time — never last-wins**
(contracts.md §C1/C2). A range is the half-open interval ``[minimum, maximum)``
over dotted numeric versions, bounded on both sides: an adapter claims exactly
the pins it was measured against, not "everything".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["NativeVersionRange", "VersionRangeError", "parse_version"]

_VERSION_OK: Final[re.Pattern[str]] = re.compile(r"\A\d+(\.\d+)*([-+].+)?\Z")


class VersionRangeError(ValueError):
    """A version or range that cannot be compared was given."""


def parse_version(text: str) -> tuple[int, ...]:
    """Numeric segments; a pre-release/build suffix orders as its numeric core."""
    if not isinstance(text, str) or _VERSION_OK.fullmatch(text.strip()) is None:
        raise VersionRangeError(f"unparseable version: {text!r}")
    core = re.split(r"[-+]", text.strip(), maxsplit=1)[0]
    return tuple(int(part) for part in core.split("."))


def _cmp(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


@dataclass(frozen=True)
class NativeVersionRange:
    """Half-open ``[minimum, maximum)`` over parsed versions, both ends required."""

    minimum: str
    maximum: str

    def __post_init__(self) -> None:
        low, high = parse_version(self.minimum), parse_version(self.maximum)
        if _cmp(low, high) >= 0:
            raise VersionRangeError(
                f"range must be bounded and increasing: [{self.minimum},{self.maximum})")
        object.__setattr__(self, "_low", low)
        object.__setattr__(self, "_high", high)

    def contains(self, version: str) -> bool:
        try:
            value = parse_version(version)
        except VersionRangeError:
            return False
        return _cmp(self._low, value) <= 0 and _cmp(value, self._high) < 0

    def overlaps(self, other: "NativeVersionRange") -> bool:
        return _cmp(self._low, other._high) < 0 and _cmp(other._low, self._high) < 0

    def key(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        return (self._low, self._high)

    def __str__(self) -> str:  # pragma: no cover - diagnostic rendering
        return f">={self.minimum},<{self.maximum}"
