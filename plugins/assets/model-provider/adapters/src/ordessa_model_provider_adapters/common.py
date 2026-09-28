"""Shared adapter discipline: the canonical protocol vocabulary, per-brand
dialect tables, byte-stable rendering and registration-conflict checks.

The dialect tables are **golden facts with provenance**: transcribed from the
harness family modules ``ordessa_harness/{pi,codex,claude}/native.py`` at this
tree's snapshot (``96fef2db47``), where each value carries its first-hand
citation. A family/protocol pair absent here has no pinned native field and is
refused - never guessed (the 093 rule this package inherits).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

#: The canonical protocol vocabulary (092's contract, four values).
CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")

#: (native field, dialect token) per brand; ``None`` token = endpoint carries it.
#: provenance: ordessa_harness/{brand}/native.py DIALECTS @ 96fef2db47.
DIALECTS: dict[str, dict[str, tuple[str, str | None]]] = {
    "pi": {"openai-chat": ("api", "openai-completions")},
    "codex": {
        "openai-responses": ("wire_api", "responses"),
        "openai-chat": ("wire_api", "chat"),
    },
    "claude-code": {"anthropic-messages": ("ANTHROPIC_BASE_URL", None)},
}

#: Native target each brand writes inside its instance root (same provenance).
NATIVE_TARGET = {"pi": "models.json", "codex": "config.toml", "claude-code": "settings.json"}

#: The pinned upstream adapter versions this package was assessed against
#: (specs/011-z3-model-provider/t00-freeze.md §5). The tuple form drives
#: ``version_in_range``; the string form is what manifests declare and what
#: ``parse_range`` proves (dis)joint.
SUPPORTED_VERSION_RANGES: dict[str, tuple[str, str]] = {
    # (min inclusive, max exclusive) on the native adapter package version
    "pi": ("0.5.0", "0.6"),
    "codex": ("1.0", "2.0"),
    "claude-code": ("0.81", "0.82"),
}

RANGE_STRINGS: dict[str, str] = {
    "pi": ">=0.5.0 <0.6",
    "codex": ">=1.0 <2.0",
    "claude-code": ">=0.81 <0.82",
}


class ProtocolUnsupported(Exception):
    """No first-hand native field for this brand/protocol pair."""


class RegistrationConflict(Exception):
    """Two contributions claim an overlapping (facet, harness, entry, range)."""


def digest_label(request: Any) -> str:
    """A stable short content digest for a MountContent reference (the content
    itself stays with the harness; only the label identifies it)."""
    payload = json.dumps([
        request.provider_name, request.endpoint, request.protocol, request.model_id,
    ], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def translate_protocol(harness: str, protocol: str) -> tuple[str, str | None]:
    """(native field, dialect token) for one brand/protocol, or refusal."""
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    dialect = DIALECTS.get(harness, {}).get(protocol)
    if dialect is None:
        raise ProtocolUnsupported(
            f"{harness} has no first-hand native field for protocol {protocol!r}")
    return dialect


def parse_version(version: str | None) -> tuple[int, ...] | None:
    """A tolerant ``(major, minor, ...)`` parse; ``None`` = unrecognized (and
    unrecognized is *unknown*, never a guess)."""
    if not version or not isinstance(version, str):
        return None
    parts = version.strip().split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers) if numbers else None


def version_in_range(harness: str, version: str | None) -> str:
    """'supported' | 'unsupported' | 'unknown' for one native version."""
    parsed = parse_version(version)
    if parsed is None:
        return "unknown"
    low, high = SUPPORTED_VERSION_RANGES[harness]
    low_parsed, high_parsed = parse_version(low), parse_version(high)
    assert low_parsed is not None and high_parsed is not None
    padded = parsed + (0,) * max(0, len(low_parsed) - len(parsed))
    if padded < low_parsed or padded >= high_parsed:
        return "unsupported"
    return "supported"


def render_codex_provider_section(*, provider: str, base_url: str, protocol: str) -> str:
    """The ``[model_providers.<id>]`` TOML block, byte-stable (same input ->
    same bytes). provenance: ``ordessa_harness.native_materialization
    .render_codex_provider_section`` @ 96fef2db47; endpoint/protocol live
    *inside* the provider table and the credential stays an env-name."""

    field, dialect = translate_protocol("codex", protocol)
    lines = [
        f"[model_providers.{provider}]",
        f"name = \"{provider}\"",
        f"base_url = \"{base_url}\"",
        f"{field} = \"{dialect}\"",
        "env_key = \"CODEX_API_KEY\"",
    ]
    return "\n".join(lines) + "\n"


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
