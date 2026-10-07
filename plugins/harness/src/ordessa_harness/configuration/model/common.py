"""Shared adapter discipline: the canonical protocol vocabulary, per-brand
dialect tables, byte-stable rendering and registration-conflict checks.

The dialect tables are **golden facts with provenance**: transcribed from the
harness family modules ``ordessa_harness/{pi,codex,claude}/native.py`` at this
tree's snapshot (``96fef2db47``), where each value carries its first-hand
citation. A family/protocol pair absent here has no pinned native field and is
refused - never guessed (the 093 rule this package inherits).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping
from pacthold.harness_contracts.model_compilation import parse_version
from ordessa_harness_claude_code import acp_model_facts as claude_facts
from ordessa_harness_codex import acp_model_facts as codex_facts
from ordessa_harness_pi import acp_model_facts as pi_facts
from ordessa_harness_codex.acp_model_facts import codex_effort_values, digest_label, render_codex_provider_section

#: The canonical protocol vocabulary (092's contract, four values).
CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")

#: (native field, dialect token) per brand; ``None`` token = endpoint carries it.
#: provenance: ordessa_harness/{brand}/native.py DIALECTS @ 96fef2db47.
DIALECTS: dict[str, dict[str, tuple[str, str | None]]] = {
    "pi": pi_facts.DIALECT,
    "codex": codex_facts.DIALECT,
    "claude-code": claude_facts.DIALECT,
}

#: Native target each brand writes inside its instance root (same provenance).
NATIVE_TARGET = {"pi": pi_facts.NATIVE_TARGET["pi"], "codex": codex_facts.NATIVE_TARGET["codex"], "claude-code": claude_facts.NATIVE_TARGET["claude-code"]}

#: The pinned upstream adapter versions this package was assessed against
#: (specs/011-z3-model-provider/t00-freeze.md §5). The tuple form drives
#: ``version_in_range``; the string form is what manifests declare and what
#: ``parse_range`` proves (dis)joint.
SUPPORTED_VERSION_RANGES: dict[str, tuple[str, str]] = {
    # (min inclusive, max exclusive) on the native adapter package version
    "pi": pi_facts.VERSION_RANGE,
    "codex": codex_facts.VERSION_RANGE,
    "claude-code": claude_facts.VERSION_RANGE,
}

RANGE_STRINGS: dict[str, str] = {
    "pi": pi_facts.RANGE_STRINGS["pi"],
    "codex": codex_facts.RANGE_STRINGS["codex"],
    "claude-code": claude_facts.RANGE_STRINGS["claude-code"],
}


#: ---- MPX (016) request-level param facts, first-hand pinned in THIS tree ----
#: provenance: ordessa_harness/codex/remote.py (_EFFORTS + the
#: `-c model_reasoning_effort="..."` request spelling and the config.toml
#: form) @ this tree; deepseek provider subsets the vocabulary (validate_remote_configuration).
CODEX_EFFORT_FIELD = codex_facts.CODEX_EFFORT_FIELD
CODEX_EFFORT_VALUES = codex_facts.CODEX_EFFORT_VALUES
CODEX_DEEPSEEK_EFFORT_VALUES = codex_facts.CODEX_DEEPSEEK_EFFORT_VALUES
#: provenance: plugins/harness/deploy/pi/settings.json — the checked-in native
#: settings template carries exactly this retry block (read by
#: ordessa_harness.pi.production.settings_document).
PI_SETTINGS_NATIVE_TARGET = pi_facts.PI_SETTINGS_NATIVE_TARGET
#: the handle id the host must issue for the pi native settings target (the
#: models.json handle stays HANDLE_IDS["pi"]; this one carries the retry block)
PI_SETTINGS_HANDLE_ID = pi_facts.PI_SETTINGS_HANDLE_ID
#: provenance: plugins/harness/deploy/pi/models.json — every model entry
#: carries ``maxTokens`` (the production template writes it via
#: ordessa_harness.pi.production.gate_models_document).
PI_MAX_TOKENS_KEY = pi_facts.PI_MAX_TOKENS_KEY
#: The timeout facts that DO exist first-hand live on the harness deployment
#: descriptor (``timeoutMs`` in ordessa_harness/{pi,codex,claude}/production.py
#: harness_deployment) — a target this facet is not authorized to claim, so
#: the timeout family projects as a typed refusal everywhere (MPX matrix).


class ParamUnsupported(Exception):
    """No first-hand pinned native key for this brand/param family."""




class ProtocolUnsupported(Exception):
    """No first-hand native field for this brand/protocol pair."""


class RegistrationConflict(Exception):
    """Two contributions claim an overlapping (facet, harness, entry, range)."""




def translate_protocol(harness: str, protocol: str) -> tuple[str, str | None]:
    """(native field, dialect token) for one brand/protocol, or refusal."""
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    dialect = DIALECTS.get(harness, {}).get(protocol)
    if dialect is None:
        raise ProtocolUnsupported(
            f"{harness} has no first-hand native field for protocol {protocol!r}")
    return dialect




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
