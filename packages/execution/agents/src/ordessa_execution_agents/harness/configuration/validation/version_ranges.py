"""Neutral declared range and conflict checks; no brand facts or discovery."""
from typing import Any, Iterable, Mapping
from ordessa_execution_agents.harness.definitions.model_compilation import parse_version

class RegistrationConflict(Exception):
    """Two contributions claim overlapping facet/harness/entry/range."""

def version_in_range(version: str | None, declared_range: tuple[str, str]) -> str:
    """'supported' | 'unsupported' | 'unknown' for one native version."""
    parsed = parse_version(version)
    if parsed is None:
        return "unknown"
    low, high = declared_range
    low_parsed, high_parsed = parse_version(low), parse_version(high)
    assert low_parsed is not None and high_parsed is not None
    padded = parsed + (0,) * max(0, len(low_parsed) - len(parsed))
    if padded < low_parsed or padded >= high_parsed:
        return "unsupported"
    return "supported"




def _version_key(parsed: tuple[int, ...]) -> tuple[int, int]:
    return (parsed + (0, 0))[0], (parsed + (0, 0))[1]


def parse_range(range_spec: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Parse the package's declared range format ``">=X <Y"`` (inclusive low,
    exclusive high) into comparable (major, minor) keys; ``None`` = unprovable."""
    if not isinstance(range_spec, str):
        return None
    low_token, high_token = None, None
    for token in range_spec.replace(",", " ").split():
        if token.startswith(">="):
            low_token = token[2:]
        elif token.startswith("<"):
            high_token = token[1:]
        else:
            return None
    if low_token is None or high_token is None:
        return None
    low, high = parse_version(low_token), parse_version(high_token)
    if low is None or high is None:
        return None
    return _version_key(low), _version_key(high)


def ranges_provably_disjoint(range_a: str, range_b: str) -> bool:
    """Whether two declared ranges cannot overlap. A range this package cannot
    parse is unprovable -> False (refuse, never order-dependent)."""
    a, b = parse_range(range_a), parse_range(range_b)
    if a is None or b is None:
        return False
    return a[1] <= b[0] or b[1] <= a[0]


def check_registration_conflicts(entries: Iterable[Mapping[str, Any]]) -> None:
    """Refuse overlapping ``(facet_id, harness_id, entry, version-range)``
    claims; ranges that cannot be proven disjoint are refused too - never
    resolved by registration order."""
    seen: list[tuple[str, str, str, str]] = []
    for manifest in entries:
        key_base = (str(manifest["facet_id"]), str(manifest["harness_id"]),
                    str(manifest["supported_native_versions"]))
        for entry in manifest["entries"]:
            key = key_base + (str(entry),)
            for other in seen:
                same_claim = (other[0] == key[0] and other[1] == key[1]
                              and other[3] == key[3])
                if not same_claim:
                    continue
                if other[2] == key[2]:
                    raise RegistrationConflict(
                        f"{key[0]}/{key[1]}/{key[3]} claimed twice "
                        f"({key[2]} vs {other[2]})")
                if not ranges_provably_disjoint(other[2], key[2]):
                    raise RegistrationConflict(
                        f"version ranges {other[2]!r} and {key[2]!r} cannot be "
                        f"proven disjoint for {key[0]}/{key[1]}/{key[3]}")
            seen.append(key)
