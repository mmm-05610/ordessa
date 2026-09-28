"""Shared adapter discipline: canonical vocabularies, byte-stable rendering
and version gates for the runtime-preferences adapters.

Byte stability is a conformance-pinned property: the same inputs render the
same bytes, every time and on every host (golden tests hold the exact
outputs). The renderers cover the codecs this evidence level actually writes
(JSON for most brands, TOML for codex); hermes (YAML) and dsh (no pinnable
target) compile nothing at document level, so no YAML renderer is claimed.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from . import keys

#: The canonical facet vocabulary (spec §4 ruling 2: one facet, four items).
FACET_ID = "assets.runtime-preferences"
FACET_SCHEMA_VERSION = "1"
CONTRIBUTOR_VERSION = "1"
#: The C2 entry (channel) the adapters serve; the harness service matches
#: ``context.entry`` against this (same entry vocabulary as model-provider).
ENTRY = "acp"
PAYLOAD_SCHEMA_ID = "runtime-preferences.item.v1"

#: Local reconfiguration vocabulary. ``unverified`` dominates: with any
#: compiled key whose apply mode is unknown at this evidence level, the
#: package refuses to claim a mechanism (R3: never write hot-reload without
#: evidence). Verified levels rank restart-resume > reload > session-local.
RECONFIGURATION_VOCABULARY = ("session-local", "reload", "restart-resume", "unverified")

_APPLY_TO_RECONFIGURATION = {
    keys.APPLY_RESTART: "restart-resume",
    keys.APPLY_RELOAD: "reload",
    keys.APPLY_NEXT_SESSION: "session-local",
    keys.APPLY_UNKNOWN: "unverified",
}


class GroupUnsupported(Exception):
    """No document-level native surface for this brand/group pair."""


class InvalidPreference(Exception):
    """A value outside the canonical vocabulary (closed schemas refuse)."""


def item_reconfiguration(brand: str, group: str) -> str:
    """The honest reconfiguration declaration for one compiled item: the
    least verified claim across its compiled keys. ``unknown`` beats the
    rest — an item mixing verified and unknown keys stays ``unverified``."""
    modes = [key.apply_mode for key in keys.cell(brand, group).keys
             if key.canonical is not None and not key.admin_only]
    if not modes:
        raise GroupUnsupported(f"{brand}/{group} compiles no keys at this evidence level")
    if any(mode == keys.APPLY_UNKNOWN for mode in modes):
        return "unverified"
    if any(mode == keys.APPLY_RESTART for mode in modes):
        return _APPLY_TO_RECONFIGURATION[keys.APPLY_RESTART]
    if any(mode == keys.APPLY_RELOAD for mode in modes):
        return _APPLY_TO_RECONFIGURATION[keys.APPLY_RELOAD]
    return _APPLY_TO_RECONFIGURATION[keys.APPLY_NEXT_SESSION]


# -- byte-stable rendering -----------------------------------------------------

def render_json_object(value: Mapping[str, Any]) -> str:
    """Deterministic JSON document for a compiled native object: sorted keys,
    compact separators, UTF-8, one trailing newline. Golden-pinned."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False) + "\n"


def render_codex_compaction_lines(*, token_limit: int) -> str:
    """The codex ``config.toml`` lines for one compiled compaction parameter,
    byte-stable (same input -> same bytes). provenance:
    ``ordessa_harness.native_materialization.render_codex_provider_section``
    shape (model-provider adapters @ codex/014-b-model-provider), applied to
    this domain's documented key; the value travels inside the typed intent
    as the parsed table, never as this text."""
    lines = [
        f"model_auto_compact_token_limit = {int(token_limit)}",
    ]
    return "\n".join(lines) + "\n"


def render_preference_document(brand: str, group: str, native_object: Mapping[str, Any]) -> str:
    """The golden text one compiled item materializes on its target.
    codex targets are TOML and take line sections; every other pinnable
    target is JSON."""
    target, codec = keys.BRAND_TARGETS[brand]
    if target is None or codec is None:
        raise GroupUnsupported(f"{brand} has no pinnable native target at document level")
    if codec == "toml":
        if group != "compaction":
            raise InvalidPreference(f"codex {group} compiles no keys at document level")
        return render_codex_compaction_lines(**native_object)
    if codec == "json":
        return render_json_object(native_object)
    raise GroupUnsupported(f"{brand} codec {codec!r} has no renderer at this evidence level")


# -- version gates ---------------------------------------------------------------

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


def version_gate(version: str | None) -> str:
    """'supported' | 'unknown' for a reported native version.

    The assessment window is deliberately open: at document evidence level
    this package has NO pinned per-brand version thresholds (sources-and-gaps
    R1 is an open item, registered in the report). An unrecognizable version
    string is ``unknown`` — never silently treated as supported. The real
    per-key gate is the catalog: a brand/group pair without documented keys
    never reaches a compiled intent.
    """
    if parse_version(version) is None:
        return "unknown"
    return "supported"


def digest_label(value: Any) -> str:
    """A stable short content digest for verify evidence references."""
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
