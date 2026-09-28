"""Shared fixtures: scripted harness catalog and facet provider doubles.

The doubles are *controlled* evidence instruments (constitution IV): they
script explicit capability verdicts so every counterexample is deliberate;
they never imitate a real Harness product.

v2 adds ``ScriptedConfigPort`` — a controlled Harness application-port
double.  It counts every plan/apply/inspect/reconcile call (the
"output-in-progress switch" scenario asserts counters stay 0) and scripts
plan/apply/reconcile verdicts.  Its confirmations are explicitly labelled
``controlled-fixture`` evidence: they prove Profile's journal/fence logic,
never a real Harness product.
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest

from ordessa_profile import ProfileCore, StaticHarnessCatalog
from ordessa_profile.contracts import (
    Applicability,
    ApplyConfirmed,
    ApplyRejected,
    ApplyUnknown,
    AppliedReceipt,
    CompileResult,
    FacetDescriptor,
    HarnessTargetFacts,
    InspectResult,
    ItemDescriptor,
    MigratedItems,
    MigrationUnsupported,
    PlanResult,
    PlannedItem,
    ReconcileOutcome,
    UNSET,
    Violation,
)
from ordessa_profile.sensitive import digest as _digest


class ScriptedProvider:
    """Facet provider double with per-item scripted behaviour."""

    def __init__(
        self,
        facet_id: str,
        item_ids: tuple[str, ...],
        *,
        owner: str = "test-owner",
        version: str = "1.0.0",
        applies: frozenset[str] | None = None,
        valid: set[str] | None = None,
        session_apply_verdict: str = "apply_next_turn",
        resolved_conflicts: list[str] | None = None,
        stored_ruling: str = "accepted",
        migrated_value: Any = None,
        title: str = "",
    ) -> None:
        self.facet_id = facet_id
        self.owner_plugin_id = owner
        self.facet_version = version
        self.item_ids = item_ids
        self._applies = applies
        self._valid = valid
        self.session_apply_verdict = session_apply_verdict
        self.resolved_conflicts = resolved_conflicts or []
        self.stored_ruling = stored_ruling
        self.migrated_value = migrated_value
        self._title = title or facet_id

    def title(self) -> str:
        return self._title

    def applies_to(self, harness_id: str) -> bool:
        return self._applies is None or harness_id in self._applies

    def validate_value(self, item_id: str, value: Any) -> None:
        if self._valid is not None and value not in self._valid:
            raise ValueError(f"invalid value for {item_id}: {value!r}")

    def session_apply(self, item_id: str, current_value: Any,
                      target_value: Any) -> str:
        return self.session_apply_verdict

    def validate_resolved(self, values: dict[str, Any]) -> None:
        if self.resolved_conflicts:
            from ordessa_profile.errors import ProfileError
            raise ProfileError(
                "CONFIG_CONFLICT",
                "scripted conflict",
            ).with_conflicts([
                {"facet_id": self.facet_id, "item_id": item}
                for item in self.resolved_conflicts
            ])

    def check_stored_value(self, stored_facet_version: str, item_id: str,
                           value: Any) -> Any:
        from ordessa_profile import StoredValueVerdict
        if self.stored_ruling == "accepted":
            return StoredValueVerdict.accepted()
        if self.stored_ruling == "migrated":
            return StoredValueVerdict.migrated(self.migrated_value)
        return StoredValueVerdict.incompatible()


class SequenceClock:
    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> str:
        self._n += 1
        return f"2026-09-27T00:00:{self._n:02d}+00:00"


class ScriptedConfigPort:
    """Controlled HarnessConfigPort double (constitution IV instrument).

    ``apply_verdict`` scripts the apply outcome: 'confirmed' | 'rejected' |
    'unknown'.  Counters let tests assert that selection never touches the
    port (G20) and that blocked switches reach plan but never apply (G08).
    """

    def __init__(self, *, plan_verdict: str = "live-update",
                 apply_verdict: str = "confirmed",
                 reconcile_verdict: str = "confirmed-current",
                 blocked_item_ids: tuple[tuple[str, str], ...] = ()) -> None:
        self.plan_verdict = plan_verdict
        self.apply_verdict = apply_verdict
        self.reconcile_verdict = reconcile_verdict
        self.blocked_item_ids = blocked_item_ids
        self.counters = {"inspect": 0, "plan": 0, "apply": 0,
                         "abort": 0, "restart": 0, "reconcile": 0}
        self.applied: list[tuple] = []
        self.reconciled: list[str] = []

    def inspect(self, target):
        self.counters["inspect"] += 1
        return InspectResult(
            target=HarnessTargetFacts(
                session_ref=target,
                runtime_generation=f"fixture-gen-{self.counters['inspect']}"),
            evidence_kind="controlled-fixture",
            current_config_digest="sha256:fixture-current",
        )

    def plan(self, target, desired, operation_key):
        self.counters["plan"] += 1
        items = []
        blocked = []
        for intent in desired:
            if (intent.facet_id, intent.item_id) in self.blocked_item_ids:
                status = "blocked"
                blocked.append(intent)
            else:
                status = "live-update"
            items.append(PlannedItem(
                facet_id=intent.facet_id, item_id=intent.item_id,
                op=intent.op, status=status,
                reason="scripted" if status == "blocked" else "",
            ))
        overall = "blocked" if blocked else self.plan_verdict
        return PlanResult(
            session_ref=target, operation_key=operation_key, overall=overall,
            items=tuple(items),
            plan_digest=_digest([i.native_key for i in desired]),
            fence={"runtime_generation":
                   f"fixture-gen-{self.counters['inspect']}"},
        )

    def apply(self, plan, desired):
        self.counters["apply"] += 1
        self.applied.append(tuple(desired))
        generation = f"fixture-gen-{self.counters['inspect']}"
        receipt = AppliedReceipt(
            operation_id=plan.operation_key.split(":")[-1],
            session_ref=plan.session_ref,
            runtime_generation=generation,
            config_digest=_digest([i.native_key for i in desired]),
            profile_id="fixture", profile_revision=1,
            overlay_revision=None, policy_revision=1,
            provider_generations={}, evidence_kind="controlled-fixture",
            confirmed_at="2026-09-28T00:00:00+00:00",
            execution_id="fixture-exec-1",
        )
        if self.apply_verdict == "confirmed":
            if plan.overall == "restart-resume":
                self.counters["restart"] += 1
            return ApplyConfirmed(state="confirmed", receipt=receipt)
        if self.apply_verdict == "rejected":
            return ApplyRejected(
                state="rejected-unchanged", reason="scripted rejection",
                items=tuple(PlannedItem(
                    facet_id=i.facet_id, item_id=i.item_id, op=i.op,
                    status="blocked", reason="scripted rejection")
                    for i in desired),
            )
        return ApplyUnknown(state="unknown", reason="scripted unknown")

    def reconcile(self, operation_key, target):
        self.counters["reconcile"] += 1
        self.reconciled.append(operation_key)
        generation = "fixture-gen-reconciled"
        receipt = AppliedReceipt(
            operation_id=operation_key.split(":")[-1],
            session_ref=target,
            runtime_generation=generation,
            config_digest="sha256:fixture-reconciled",
            profile_id="fixture", profile_revision=1,
            overlay_revision=None, policy_revision=1,
            provider_generations={}, evidence_kind="controlled-fixture",
            confirmed_at="2026-09-28T00:00:01+00:00",
            execution_id="fixture-exec-2",
        )
        if self.reconcile_verdict == "confirmed-current":
            return ReconcileOutcome(state="confirmed-current", receipt=receipt)
        if self.reconcile_verdict == "rejected-unchanged":
            return ReconcileOutcome(state="rejected-unchanged",
                                    reason="scripted unchanged")
        return ReconcileOutcome(state="unknown", reason="scripted unknown")


class ScriptedV2Provider:
    """v2 facet provider double: declarative descriptor, three-valued
    applicability, schema validation, migration and reset-aware compile."""

    def __init__(self, facet_id, items, *, owner="v2-owner",
                 schema_version="1.0.0", native_prefix=None,
                 applies=None, capability_rule="unknown",
                 valid=None, migrate_from=None, migrated_value=None,
                 omit_resets=False):
        self._facet_id = facet_id
        self._owner = owner
        self._items = tuple(items)  # (item_id, schema dict)
        self._schema_version = schema_version
        self._native_prefix = native_prefix or facet_id
        self._applies = applies
        self._capability_rule = capability_rule  # 'yes'|'no'|'unknown'
        self._valid = valid
        self._migrate_from = migrate_from
        self._migrated_value = migrated_value
        self._omit_resets = omit_resets

    def descriptor(self) -> FacetDescriptor:
        return FacetDescriptor(
            facet_id=self._facet_id, api_major=2,
            schema_version=self._schema_version,
            label=f"{self._facet_id} (scripted v2)",
            category="capabilities", order=50,
            item_descriptors=tuple(
                ItemDescriptor(item_id=item_id, value_schema=schema,
                               optional=True)
                for item_id, schema in self._items
            ),
        )

    def applicability(self, capability_facts: Mapping[str, Any]) -> Applicability:
        if self._capability_rule == "yes":
            return Applicability.SUPPORTED
        if self._capability_rule == "no":
            return Applicability.UNSUPPORTED
        return Applicability.UNKNOWN

    def validate(self, items, reference_facts):
        violations = []
        for item_id, value in sorted(items.items()):
            schema = dict(self.descriptor().require_item(item_id).value_schema)
            if self._valid is not None and value not in self._valid:
                violations.append(Violation(
                    facet_id=self._facet_id, item_id=item_id,
                    code="FACET_VALUE_INVALID",
                    message=f"scripted: {value!r} not permitted"))
                continue
            from ordessa_profile.contracts import validate_value_against_schema
            try:
                validate_value_against_schema(schema, value, where=item_id)
            except Exception as exc:
                violations.append(Violation(
                    facet_id=self._facet_id, item_id=item_id,
                    code="FACET_VALUE_INVALID", message=str(exc)))
        return tuple(violations)

    def migrate(self, old_schema_version, stored_items):
        if self._migrate_from is None:
            if old_schema_version == self._schema_version:
                return MigratedItems(
                    items=tuple(sorted(stored_items.items())),
                    from_schema_version=old_schema_version,
                    to_schema_version=self._schema_version)
            return MigrationUnsupported(
                reason=f"scripted: cannot migrate from {old_schema_version}",
                from_schema_version=old_schema_version,
                to_schema_version=self._schema_version)
        if old_schema_version != self._migrate_from:
            return MigrationUnsupported(
                reason="scripted: unexpected source version",
                from_schema_version=old_schema_version,
                to_schema_version=self._schema_version)
        return MigratedItems(
            items=tuple(
                (k, self._migrated_value(v) if self._migrated_value else v)
                for k, v in sorted(stored_items.items())),
            from_schema_version=old_schema_version,
            to_schema_version=self._schema_version)

    def compile(self, resolved_items, target_facts):
        facts_harness = target_facts.get("harness_id")
        if self._applies is not None and facts_harness not in self._applies:
            return CompileResult(violations=(Violation(
                facet_id=self._facet_id, item_id="*",
                code="FACET_NOT_APPLICABLE", message="scripted: not applicable"),))
        current_items = target_facts.get("current_items", {})
        intents = []
        for item_id, value in sorted(resolved_items.items()):
            intents.append(_mk_intent(
                self._facet_id, item_id, "set",
                f"{self._native_prefix}.{item_id}", value, target_facts))
        if not self._omit_resets:
            for item_id, current in sorted(current_items.items()):
                if item_id in resolved_items or current is UNSET:
                    continue
                intents.append(_mk_intent(
                    self._facet_id, item_id, "reset",
                    f"{self._native_prefix}.{item_id}", UNSET, target_facts))
        return CompileResult(intents=tuple(intents))


def _mk_intent(facet_id, item_id, op, native_key, value, target_facts):
    from ordessa_profile.contracts import ConfigIntent
    revision = target_facts.get("source_revision", "")
    return ConfigIntent(
        facet_id=facet_id, item_id=item_id, op=op, native_key=native_key,
        source=f"profile@{revision}" if revision else "profile",
        value=value,
    )


_DEFAULT_PORT = object()


def make_core(tmp_path, *, harnesses=None, config_port=_DEFAULT_PORT,
              commit_injection=None, providers: tuple = (),
              v2_providers: tuple = ()) -> ProfileCore:
    catalog = harnesses if isinstance(harnesses, StaticHarnessCatalog) else \
        StaticHarnessCatalog(harnesses or {"pi": frozenset(), "codex": frozenset()})
    port = ScriptedConfigPort() if config_port is _DEFAULT_PORT else config_port
    core = ProfileCore(
        tmp_path / "profile-store.sqlite",
        harnesses=catalog,
        clock=SequenceClock(),
        new_id=lambda prefix: f"{prefix}_{next_nonce():032x}",
        config_port=port,
        commit_injection=commit_injection,
    )
    for provider in providers:
        core.register_provider(provider)
    for provider, owner in v2_providers:
        core.register_v2_provider(provider, owner_plugin_id=owner)
    return core


_nonce = {"n": 0}


def next_nonce() -> int:
    _nonce["n"] += 1
    return _nonce["n"]


@pytest.fixture
def core(tmp_path):
    return make_core(tmp_path)


def write_legacy_db(path, rows: list[dict[str, Any]]) -> None:
    """Build a legacy v21-shaped ``server_profiles`` table (read-only input
    fixture; column shapes mirror pacthold.storage.database)."""
    conn = __import__("sqlite3").connect(str(path))
    conn.execute(
        """
        CREATE TABLE server_profiles (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            harness_type TEXT NOT NULL,
            config_revision INTEGER NOT NULL CHECK (config_revision >= 1),
            native_generation INTEGER NOT NULL DEFAULT 0,
            config_object_digest TEXT NOT NULL,
            credential_id TEXT,
            account_id TEXT,
            permission_preset TEXT,
            permission_rules_json TEXT,
            origin_profile_id TEXT,
            cloned_at TEXT,
            run_state TEXT NOT NULL DEFAULT 'idle',
            recovery_pending INTEGER NOT NULL DEFAULT 0,
            display_name TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    for row in rows:
        conn.execute(
            "INSERT INTO server_profiles(id, version, name, harness_type,"
            " config_revision, config_object_digest, credential_id,"
            " permission_preset, origin_profile_id, cloned_at, archived_at,"
            " created_at, updated_at, display_name)"
            " VALUES (:id, :version, :name, :harness_type, :config_revision,"
            " :config_object_digest, :credential_id, :permission_preset,"
            " :origin_profile_id, :cloned_at, :archived_at, :created_at,"
            " :updated_at, :display_name)",
            {
                "credential_id": None, "permission_preset": None,
                "origin_profile_id": None, "cloned_at": None,
                "archived_at": None, "display_name": None,
                **row,
            },
        )
    conn.commit()
    conn.close()


# Counterexample hook (constitution IV): an env var selects a deliberate
# behaviour break; the gate suite must then FAIL. Never set in normal runs.
import os as _os

if _os.environ.get("PROFILE_COUNTEREXAMPLE"):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from injections import apply_counterexample as _apply
    _apply()
