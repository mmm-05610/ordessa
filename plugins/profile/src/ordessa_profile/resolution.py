"""Turn effective-config resolution (FR-018/FR-021, plan §3.4).

Resolution is: the selected Profile's *latest* revision, overlaid item-by-item
by the session overlay layer. Every item carries its non-secret source facts;
providers absent from the registry can never contribute or mask values
(FR-005), and required-but-unavailable items are surfaced to the caller.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from . import repository as repo
from .errors import ProfileError
from .sensitive import digest, reject_sensitive_keys


def _loads(raw: str) -> Any:
    return json.loads(raw)


@dataclass
class Resolution:
    """Per-item facts for one resolution pass (never contains secrets)."""

    items: list[dict[str, Any]] = field(default_factory=list)
    unavailable: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    profile_id: str = ""

    def item_map(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {(i["facet_id"], i["item_id"]): i for i in self.items}

    def source_digest(self) -> str:
        return digest({
            "profile_id": self.profile_id,
            "revision": self.revision,
            "items": self.items,
        })


def _provider_state(provider: Any | None, harness_id: str,
                    quarantined: bool) -> str | None:
    """None when usable, else the honest unavailability reason."""
    if provider is None:
        return "provider_absent"
    if quarantined:
        return "value_quarantined"
    if callable(getattr(provider, "descriptor", None)) and \
            callable(getattr(provider, "applicability", None)):
        from .contracts import Applicability
        if provider.applicability(
            {"harness_id": harness_id}) is Applicability.UNSUPPORTED:
            return "facet_not_applicable"
        return None
    if not provider.applies_to(harness_id):
        return "facet_not_applicable"
    return None


def resolve_profile_items(
    conn: sqlite3.Connection, *, profile_id: str, harness_id: str,
    config_revision: int, provider_lookup: Callable[[str], Any | None],
) -> Resolution:
    """Resolve one profile revision without overlays (target/current base)."""
    resolution = Resolution(profile_id=profile_id, revision=config_revision)
    for row in repo.facet_values_at(conn, profile_id, config_revision):
        provider = provider_lookup(row["facet_id"])
        reason = _provider_state(provider, harness_id, bool(row["quarantined"]))
        if reason is not None:
            resolution.unavailable.append({
                "facet_id": row["facet_id"], "item_id": row["item_id"],
                "reason": reason,
            })
            continue
        resolution.items.append({
            "facet_id": row["facet_id"], "item_id": row["item_id"],
            "value": _loads(row["value_json"]), "source": "profile",
            "revision": config_revision,
        })
    return resolution


def resolve_session_items(
    conn: sqlite3.Connection, *, session_id: str, profile_id: str,
    harness_id: str, config_revision: int,
    provider_lookup: Callable[[str], Any | None],
) -> Resolution:
    """Latest profile revision + this session's overlays, per item (D-001)."""
    resolution = resolve_profile_items(
        conn, profile_id=profile_id, harness_id=harness_id,
        config_revision=config_revision, provider_lookup=provider_lookup,
    )
    return apply_overlays(
        conn, session_id=session_id, harness_id=harness_id,
        resolution=resolution, provider_lookup=provider_lookup,
    )


def overlay_lookup(conn: sqlite3.Connection, session_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row["facet_id"], row["item_id"]): row
        for row in repo.session_overlays(conn, session_id)
    }


def apply_overlays(
    conn: sqlite3.Connection, *, session_id: str, harness_id: str,
    resolution: Resolution, provider_lookup: Callable[[str], Any | None],
) -> Resolution:
    """Overlay application is strictly per (facet_id, item_id): one overlaid
    item never masks its facet siblings (FR-017, edge case 4)."""
    for (facet_id, item_id), row in overlay_lookup(conn, session_id).items():
        provider = provider_lookup(facet_id)
        reason = _provider_state(provider, harness_id, quarantined=False)
        if reason is not None:
            # Stored overlay survives (FR-019 persistence), but an absent
            # provider's value is never applied nor surfaced as effective.
            resolution.unavailable.append({
                "facet_id": facet_id, "item_id": item_id,
                "reason": "overlay_provider_absent", "source": "session_overlay",
            })
            continue
        entry = {
            "facet_id": facet_id, "item_id": item_id,
            "value": _loads(row["value_json"]), "source": "session_only",
            "revision": resolution.revision,
        }
        merged = {(i["facet_id"], i["item_id"]): i for i in resolution.items}
        merged[(facet_id, item_id)] = entry
        resolution.items = sorted(
            merged.values(), key=lambda i: (i["facet_id"], i["item_id"]),
        )
    return resolution


def check_required(resolution: Resolution, required: frozenset[str] | set[str]) -> None:
    """Every harness-required item must resolve to a usable value (US4.6)."""
    available = {(i["facet_id"], i["item_id"]) for i in resolution.items}
    for required_id in sorted(required):
        facet_id, _, item_id = required_id.partition("/")
        if (facet_id, item_id) not in available:
            raise ProfileError(
                "FACET_PROVIDER_UNAVAILABLE",
                f"required configuration item is not available: {required_id}",
                status=409,
            ).with_item(required_id)


def validate_resolved_groups(resolution: Resolution, provider_lookup) -> None:
    """Give each registered provider its facet's resolved values; a conflict
    refuses the turn with locatable items and never rewrites data (FR-021)."""
    groups: dict[str, dict[str, Any]] = {}
    for item in resolution.items:
        groups.setdefault(item["facet_id"], {})[item["item_id"]] = item["value"]
    for facet_id in sorted(groups):
        provider = provider_lookup(facet_id)
        if provider is None:
            continue
        if not callable(getattr(provider, "validate_resolved", None)):
            # v2 providers: their validate() already ran over these items
            continue
        try:
            provider.validate_resolved(groups[facet_id])
        except ProfileError as exc:
            if exc.code == "CONFIG_CONFLICT":
                conflicts = exc.conflicts or [
                    {"facet_id": facet_id, "item_id": item_id}
                    for item_id in sorted(groups[facet_id])
                ]
                raise ProfileError(
                    "CONFIG_CONFLICT",
                    exc.message or "resolved configuration is incompatible",
                    status=409,
                ).with_conflicts(conflicts) from exc
            raise


def conflict_free(resolution: Resolution, provider_lookup) -> None:
    reject_sensitive_keys([i["value"] for i in resolution.items])
    validate_resolved_groups(resolution, provider_lookup)
