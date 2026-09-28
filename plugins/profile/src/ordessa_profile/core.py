"""ProfileCore: composition root of the Profile plugin family.

Owns the private store, the facet registry and the service facades.
Dependencies: ``pacthold`` only. Harness knowledge enters through two ports:
the ``HarnessCatalog`` (what exists / what items are required) and the
optional ``HarnessConfigPort`` (who actually applies configuration — v2).
Without the config port, switch applications are typed-blocked; they are
never simulated from database state (application.md §1-§3).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from . import application_journal as journal
from . import repository as repo
from .contracts import (
    Applicability,
    ConfigIntent,
    FacetDescriptor,
    MigratedItems,
    UNSET,
)
from .errors import ProfileError
from .facets import FacetRegistry, StoredValueVerdict, validate_provider_shape
from .ids import now, opaque_id
from .policy import PolicyService
from .profiles import ProfileService
from .sessions import SessionService
from .sensitive import json_dumps, json_loads
from .storage import ProfileDatabase


@runtime_checkable
class HarnessCatalog(Protocol):
    def exists(self, harness_id: str) -> bool: ...

    def required_item_ids(self, harness_id: str) -> frozenset[str]: ...


@dataclass
class ReloadReport:
    facet_id: str
    accepted: int = 0
    migrated: int = 0
    quarantined: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id, "accepted": self.accepted,
            "migrated": self.migrated, "quarantined": self.quarantined,
            "details": self.details,
        }


class StaticHarnessCatalog:
    """Minimal in-memory catalog; production wiring is host-owned."""

    def __init__(self, harness_ids: dict[str, frozenset[str]] | None = None) -> None:
        self._harnesses = harness_ids or {}

    def exists(self, harness_id: str) -> bool:
        return harness_id in self._harnesses

    def required_item_ids(self, harness_id: str) -> frozenset[str]:
        return self._harnesses.get(harness_id, frozenset())


class ProfileCore:
    def __init__(
        self,
        path: str | object,
        *,
        harnesses: HarnessCatalog,
        clock: Callable[[], str] | None = None,
        new_id: Callable[[str], str] | None = None,
        config_port: Any | None = None,
        commit_injection: Callable[[str], None] | None = None,
    ) -> None:
        self.db = ProfileDatabase(path)
        self.harnesses = harnesses
        self._clock = clock or now
        self._new_id = new_id or opaque_id
        # Harness-owned application seam (v2).  ``None`` means the host has
        # not composed one: switch applications stay typed-blocked.
        self.config_port = config_port
        # Counterexample hook only: raises inside the switch-commit
        # transaction to prove the unknown-outcome path (G10/G11).
        self.commit_injection = commit_injection
        # v1 read-back proof is retired: a database read can never confirm a
        # runtime application (application.md §2).  Recovery goes through
        # the port's reconcile; see sessions.verify_recovery.
        self.registry = FacetRegistry()
        self.policy = PolicyService(self)
        self.profiles = ProfileService(self)
        self.sessions = SessionService(self)

    # -- ports -------------------------------------------------------
    def timestamp(self) -> str:
        return self._clock()

    def mint_id(self, prefix: str) -> str:
        return self._new_id(prefix)

    def provider_lookup(self, facet_id: str) -> Any | None:
        return self.registry.get(facet_id)

    # -- facet provider lifecycle (US4) ------------------------------
    def register_provider(self, provider: Any) -> ReloadReport | None:
        """Register a v1 provider. First registration after an absence (or a
        same-owner upgrade) runs the stored-value compatibility pass so
        retained values become visible again only after a ruling (US4.5)."""
        validate_provider_shape(provider)
        existing = self.registry.get(provider.facet_id)
        if existing is not None and \
                existing.owner_plugin_id != provider.owner_plugin_id:
            raise ProfileError(
                "FACET_ID_CONFLICT",
                f"facet {provider.facet_id} is already declared by "
                f"{self.registry.owner_of(provider.facet_id)!r}",
                status=409,
            )
        self.registry.register(provider)
        if existing is provider:
            return None
        return self.reload_provider(provider)

    def register_v2_provider(self, provider: Any,
                             owner_plugin_id: str) -> ReloadReport | None:
        """Register a v2 ``FacetProviderV2``; the owner comes from the host
        scope, never from the provider itself (contracts.md §1)."""
        from .facets import validate_v2_provider_shape
        validate_v2_provider_shape(provider)
        descriptor = provider.descriptor()
        existing = self.registry.get(descriptor.facet_id)
        if existing is not None:
            raise ProfileError(
                "FACET_ID_CONFLICT",
                f"facet {descriptor.facet_id} is already declared by "
                f"{self.registry.owner_of(descriptor.facet_id)!r}",
                status=409,
            )
        self.registry.register(provider, owner_plugin_id=owner_plugin_id, v2=True)
        return self.reload_v2_provider(provider)

    def unregister_provider(self, provider: Any) -> None:
        self.registry.unregister(provider)

    def reload_provider(self, provider: Any) -> ReloadReport:
        """v1 stored-value compatibility pass (US4.5)."""
        validate_provider_shape(provider)
        report = ReloadReport(facet_id=provider.facet_id)
        with self.db.transaction() as conn:
            for profile in conn.execute(
                "SELECT profile_id, current_revision FROM profile_profiles"
            ).fetchall():
                for row in repo.facet_values_at(
                    conn, profile["profile_id"], profile["current_revision"],
                ):
                    if row["facet_id"] != provider.facet_id:
                        continue
                    try:
                        value = json_loads(row["value_json"])
                    except ValueError:
                        verdict = StoredValueVerdict.incompatible()
                    else:
                        verdict = provider.check_stored_value(
                            row["facet_version"], row["item_id"], value,
                        )
                    self._apply_stored_verdict(
                        conn, report, provider.facet_id,
                        provider.facet_version, profile, row, verdict)
        return report

    def _apply_stored_verdict(self, conn, report, facet_id, facet_version,
                              profile, row, verdict) -> None:
        if verdict.kind == "accepted":
            report.accepted += 1
        elif verdict.kind == "migrated":
            report.migrated += 1
            repo.upsert_facet_value(
                conn, profile_id=profile["profile_id"],
                config_revision=profile["current_revision"],
                facet_id=facet_id, item_id=row["item_id"],
                value_json=json_dumps(verdict.value),
                facet_version=facet_version,
                timestamp=self.timestamp(), quarantined=0,
            )
        else:
            report.quarantined += 1
            repo.upsert_facet_value(
                conn, profile_id=profile["profile_id"],
                config_revision=profile["current_revision"],
                facet_id=facet_id, item_id=row["item_id"],
                value_json=row["value_json"],
                facet_version=row["facet_version"],
                timestamp=self.timestamp(), quarantined=1,
            )
        report.details.append({
            "profile_id": profile["profile_id"],
            "item_id": row["item_id"], "verdict": verdict.kind,
        })

    def reload_v2_provider(self, provider: Any) -> ReloadReport:
        """Stored-value ruling for a v2 provider via its ``migrate``."""
        from .contracts import MigrationUnsupported
        report = ReloadReport(facet_id=provider.descriptor().facet_id)
        descriptor = provider.descriptor()
        with self.db.transaction() as conn:
            for profile in conn.execute(
                "SELECT profile_id, current_revision FROM profile_profiles"
            ).fetchall():
                for row in repo.facet_values_at(
                    conn, profile["profile_id"], profile["current_revision"],
                ):
                    if row["facet_id"] != descriptor.facet_id:
                        continue
                    try:
                        value = json_loads(row["value_json"])
                    except ValueError:
                        self._apply_stored_verdict(
                            conn, report, descriptor.facet_id,
                            row["facet_version"], profile, row,
                            StoredValueVerdict.incompatible())
                        continue
                    ruling = provider.migrate(
                        row["facet_version"], {row["item_id"]: value})
                    if isinstance(ruling, MigrationUnsupported):
                        self._apply_stored_verdict(
                            conn, report, descriptor.facet_id,
                            row["facet_version"], profile, row,
                            StoredValueVerdict.incompatible())
                        continue
                    migrated = dict(ruling.items)
                    if row["item_id"] in migrated:
                        self._apply_stored_verdict(
                            conn, report, descriptor.facet_id,
                            descriptor.schema_version, profile, row,
                            StoredValueVerdict.migrated(migrated[row["item_id"]]))
                    else:
                        self._apply_stored_verdict(
                            conn, report, descriptor.facet_id,
                            descriptor.schema_version, profile, row,
                            StoredValueVerdict.accepted())
        return report

    # -- v2 difference planning (application.md §1 step 3) ---------------
    def compile_switch_diffs(
        self, session: dict[str, Any], pending_profile: str,
    ) -> tuple[tuple[ConfigIntent, ...], list[dict[str, Any]]]:
        """Plan the complete A→B difference as typed intents.

        Removals become ``reset`` intents — a field present in A and absent
        in B may never quietly vanish from the plan (G08).  A difference
        whose facet is absent, not applicable or quarantined blocks the
        whole switch; filtering fields is never a pass.  Two facets claiming
        the same native key raise ``NATIVE_KEY_CONFLICT`` before any plan
        leaves the process (G16).
        """
        blockers: list[dict[str, Any]] = []
        intents: list[ConfigIntent] = []
        with self.db.read() as conn:
            current_raw = self._raw_items(
                conn, session["session_id"], session["current_profile_id"])
            target_profile = self.require_profile(conn, pending_profile)
            target_raw = self._raw_items(conn, None, pending_profile)
        revision = int(target_profile["current_revision"])
        harness_id = session["harness_id"]
        per_facet: dict[str, dict[str, dict[str, Any]]] = {}
        for key in sorted(set(current_raw) | set(target_raw)):
            facet_id, item_id = key
            cur = current_raw.get(key)
            tgt = target_raw.get(key)
            if cur is not None and tgt is not None \
                    and cur["value"] == tgt["value"]:
                continue
            provider = self.provider_lookup(facet_id)
            if provider is None:
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "provider_absent",
                })
                continue
            if tgt is not None and tgt["quarantined"]:
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "value_quarantined",
                })
                continue
            if self._is_v2_provider(provider):
                applicability = provider.applicability(
                    {"harness_id": harness_id})
                if applicability is Applicability.UNSUPPORTED:
                    blockers.append({
                        "facet_id": facet_id, "item_id": item_id,
                        "reason": "facet_not_applicable",
                    })
                    continue
                if applicability is Applicability.UNKNOWN:
                    # contracts.md §1: unknown capability honestly blocks —
                    # it is never promoted to supported (G08/G13).
                    blockers.append({
                        "facet_id": facet_id, "item_id": item_id,
                        "reason": "facet_applicability_unknown",
                    })
                    continue
            elif not provider.applies_to(harness_id):
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "facet_not_applicable",
                })
                continue
            per_facet.setdefault(facet_id, {})[item_id] = {
                "current": cur["value"] if cur else UNSET,
                "desired": tgt["value"] if tgt else UNSET,
            }
        target_facts = {"harness_id": harness_id, "source_revision": revision}
        for facet_id, entries in sorted(per_facet.items()):
            provider = self.provider_lookup(facet_id)
            if self._is_v2_provider(provider):
                self._compile_v2(
                    provider, entries, target_facts, intents, blockers)
            else:
                self._compile_v1(
                    provider, facet_id, entries, revision, intents, blockers)
        by_native_key: dict[str, list[ConfigIntent]] = {}
        for intent in intents:
            by_native_key.setdefault(intent.native_key, []).append(intent)
        for native_key, group in sorted(by_native_key.items()):
            owners = {(i.facet_id, i.item_id) for i in group}
            if len(owners) > 1:
                raise ProfileError(
                    "NATIVE_KEY_CONFLICT",
                    "two configuration facets claim the same native "
                    "configuration key; nothing is applied",
                    status=409,
                ).with_blockers([
                    {"facet_id": i.facet_id, "item_id": i.item_id,
                     "reason": "native_key_conflict", "detail": native_key}
                    for i in group
                ])
        return tuple(intents), blockers

    @staticmethod
    def _is_v2_provider(provider: Any) -> bool:
        factory = getattr(provider, "descriptor", None)
        return callable(factory) and callable(getattr(provider, "compile", None))

    def _compile_v2(self, provider: Any,
                    entries: dict[str, dict[str, Any]],
                    target_facts: dict[str, Any],
                    intents: list[ConfigIntent],
                    blockers: list[dict[str, Any]]) -> None:
        facet_id = provider.descriptor().facet_id
        desired = {
            item_id: entry["desired"] for item_id, entry in entries.items()
            if entry["desired"] is not UNSET
        }
        facts = dict(target_facts)
        facts["current_items"] = {
            item_id: entry["current"] for item_id, entry in entries.items()
        }
        result = provider.compile(desired, facts)
        for violation in result.violations:
            blockers.append({
                "facet_id": violation.facet_id,
                "item_id": violation.item_id,
                "reason": violation.code,
                "detail": violation.message,
            })
        intents.extend(result.intents)
        # Safety net: every removal must be covered by a reset the provider
        # declared — an uncovered removal cannot silently disappear (G08).
        declared_items = {
            i.item_id for i in provider.descriptor().item_descriptors
        }
        for item_id, entry in entries.items():
            if entry["desired"] is not UNSET:
                continue
            if item_id not in declared_items:
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "reset_unsupported",
                    "detail": "removed item is not declared by the provider",
                })
            elif not any(
                i.facet_id == facet_id and i.item_id == item_id
                and i.op == "reset" for i in intents
            ):
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "reset_missing",
                    "detail": "provider did not declare a reset for the "
                              "removed item",
                })

    def _compile_v1(self, provider: Any, facet_id: str,
                    entries: dict[str, dict[str, Any]], revision: int,
                    intents: list[ConfigIntent],
                    blockers: list[dict[str, Any]]) -> None:
        for item_id, entry in sorted(entries.items()):
            current = entry["current"]
            desired = entry["desired"]
            verdict = provider.session_apply(item_id, current, desired)
            if verdict != "apply_next_turn":
                blockers.append({
                    "facet_id": facet_id, "item_id": item_id,
                    "reason": "session_apply_blocked",
                })
                continue
            removing = desired is UNSET
            intents.append(ConfigIntent(
                facet_id=facet_id, item_id=item_id,
                op="reset" if removing else "set",
                native_key=f"{facet_id}.{item_id}",
                source=f"profile@{revision}",
                value=UNSET if removing else desired,
            ))

    def _raw_items(self, conn: sqlite3.Connection, session_id: str | None,
                   profile_id: str) -> dict[tuple[str, str], dict[str, Any]]:
        """Stored facts of one side: profile values at the latest revision,
        plus the session's overlays (session side only)."""
        profile = self.require_profile(conn, profile_id)
        raw: dict[tuple[str, str], dict[str, Any]] = {}
        for row in repo.facet_values_at(
            conn, profile_id, int(profile["current_revision"]),
        ):
            raw[(row["facet_id"], row["item_id"])] = {
                "value": json_loads(row["value_json"]),
                "quarantined": bool(row["quarantined"]),
            }
        if session_id is not None:
            for row in repo.session_overlays(conn, session_id):
                raw[(row["facet_id"], row["item_id"])] = {
                    "value": json_loads(row["value_json"]),
                    "quarantined": False,
                }
        return raw

    # -- v2 read-only catalog / preview ----------------------------------
    def describe_facets(self, harness_id: str | None = None) -> list[dict[str, Any]]:
        """Sanitized, editable facet catalog (contracts.md §3
        describeFacets).  Applicability is honest three-valued: providers
        that cannot decide from real capability facts answer ``unknown``."""
        entries: list[dict[str, Any]] = []
        for provider in self.registry.registered():
            if self._is_v2_provider(provider):
                descriptor = provider.descriptor()
                facet_id = descriptor.facet_id
            else:
                facet_id = provider.facet_id
            owner = self.registry.owner_of(facet_id)
            if self._is_v2_provider(provider):
                if harness_id is None:
                    applicability = Applicability.UNKNOWN
                else:
                    applicability = provider.applicability(
                        {"harness_id": harness_id})
                entries.append({
                    "facet_id": descriptor.facet_id,
                    "api_major": descriptor.api_major,
                    "schema_version": descriptor.schema_version,
                    "label": descriptor.label,
                    "description": descriptor.description,
                    "category": descriptor.category,
                    "order": descriptor.order,
                    "owner_plugin_id": owner,
                    "applicability": applicability.value,
                    "items": [
                        {
                            "item_id": item.item_id,
                            "value_schema": dict(item.value_schema),
                            "optional": item.optional,
                            "override_supported": item.override_supported,
                            "sensitivity": item.sensitivity,
                            "effect": item.effect,
                            "title": item.title,
                            "description": item.description,
                        }
                        for item in descriptor.item_descriptors
                    ],
                })
            else:
                applies = True if harness_id is None \
                    else provider.applies_to(harness_id)
                entries.append({
                    "facet_id": provider.facet_id,
                    "api_major": 1,
                    "schema_version": provider.facet_version,
                    "label": provider.title(),
                    "description": "",
                    "category": "advanced",
                    "order": 100,
                    "owner_plugin_id": owner or provider.owner_plugin_id,
                    "applicability": (
                        "supported" if applies else "unsupported"),
                    "items": [
                        {
                            "item_id": item_id,
                            "value_schema": {"type": "object",
                                             "description": "v1 provider: "
                                             "value validated by the "
                                             "provider itself"},
                            "optional": True,
                            "override_supported": True,
                            "sensitivity": "non-secret",
                            "effect": "configuration",
                            "title": item_id,
                            "description": "",
                        }
                        for item_id in provider.item_ids
                    ],
                })
        return sorted(entries, key=lambda e: (e["category"], e["order"],
                                              e["facet_id"]))

    def resolve_preview(self, profile_id: str,
                        session_id: str | None = None) -> dict[str, Any]:
        """Zero-side-effect resolution with per-item sources and conflicts
        (contracts.md §3 resolvePreview)."""
        from .resolution import resolve_profile_items, resolve_session_items, \
            validate_resolved_groups
        with self.db.read() as conn:
            profile = self.require_profile(conn, profile_id)
            if session_id is not None:
                session = self.sessions._require_session(conn, session_id)
                resolution = resolve_session_items(
                    conn, session_id=session["session_id"],
                    profile_id=profile["profile_id"],
                    harness_id=session["harness_id"],
                    config_revision=int(profile["current_revision"]),
                    provider_lookup=self.provider_lookup,
                )
                harness_id = session["harness_id"]
            else:
                resolution = resolve_profile_items(
                    conn, profile_id=profile["profile_id"],
                    harness_id=profile["harness_id"],
                    config_revision=int(profile["current_revision"]),
                    provider_lookup=self.provider_lookup,
                )
                harness_id = profile["harness_id"]
        conflicts: list[dict[str, Any]] = []
        try:
            validate_resolved_groups(resolution, self.provider_lookup)
        except ProfileError as exc:
            conflicts = exc.conflicts or []
        return {
            "profile_id": profile["profile_id"],
            "harness_id": harness_id,
            "revision": int(profile["current_revision"]),
            "items": resolution.items,
            "unavailable": resolution.unavailable,
            "conflicts": conflicts,
            "digest": resolution.source_digest(),
        }

    # -- shared internals --------------------------------------------
    def require_profile(self, conn: sqlite3.Connection, profile_id: str) -> dict[str, Any]:
        row = repo.get_profile(conn, profile_id)
        if row is None:
            raise ProfileError(
                "PROFILE_NOT_FOUND", "Profile was not found", status=404,
            )
        return row
