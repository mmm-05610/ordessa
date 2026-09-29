"""Ordessa Profile plugin family: per-Harness profiles, contributed facets,
session overlays and same-session switching. Depends on ``pacthold`` only.

The v2 public contract surface lives in ``ordessa_profile.contracts`` and is
re-exported here: facet descriptors, item schemas, value states, session
identity, config intents, applied receipts, the mechanism policy and the
Harness application port (the ``profile-api`` checkpoint surface).
"""
from __future__ import annotations

from .core import HarnessCatalog, ProfileCore, ReloadReport, StaticHarnessCatalog
from .errors import ProfileError
from .facets import FacetProvider, FacetRegistry, StoredValueVerdict, V1ProviderAdapter
from .migration import LegacyImportReport, import_legacy
from .plugin import ProfilePlugin, ProfilePluginServices, create_plugin

from .contracts import (
    Applicability,
    AppliedReceipt,
    ApplyConfirmed,
    ApplyRejected,
    ApplyUnknown,
    CompileResult,
    ConfigIntent,
    EVIDENCE_LEGACY_UNVERIFIED,
    EVIDENCE_PORT_CONFIRMED,
    FacetDescriptor,
    HarnessConfigPort,
    HarnessConfigPortAbsent,
    HarnessTargetFacts,
    InspectResult,
    ItemDescriptor,
    JournalEntry,
    MigratedItems,
    MigrationUnsupported,
    PlanResult,
    PlannedItem,
    ReconcileOutcome,
    MechanismPolicy,
    SessionRef,
    UNSET,
    ValueDisabled,
    Violation,
    validate_schema_shape,
    validate_value_against_schema,
    validate_v2_provider_shape,
    value_state,
)

__all__ = [
    # v1 surface (preserved)
    "FacetProvider", "FacetRegistry", "HarnessCatalog", "LegacyImportReport",
    "ProfileCore", "ProfileError", "ProfilePlugin", "ReloadReport",
    "StaticHarnessCatalog", "StoredValueVerdict", "create_plugin",
    "import_legacy", "V1ProviderAdapter",
    # v2 contract surface
    "Applicability", "AppliedReceipt", "ApplyConfirmed", "ApplyRejected",
    "ApplyUnknown", "CompileResult", "ConfigIntent",
    "EVIDENCE_LEGACY_UNVERIFIED", "EVIDENCE_PORT_CONFIRMED",
    "FacetDescriptor", "HarnessConfigPort", "HarnessConfigPortAbsent",
    "HarnessTargetFacts", "InspectResult", "ItemDescriptor", "JournalEntry",
    "MigratedItems", "MigrationUnsupported", "PlanResult", "PlannedItem",
    "ReconcileOutcome", "MechanismPolicy", "SessionRef", "UNSET",
    "ValueDisabled", "Violation", "ProfilePluginServices",
    "validate_schema_shape", "validate_value_against_schema",
    "validate_v2_provider_shape", "value_state",
]
