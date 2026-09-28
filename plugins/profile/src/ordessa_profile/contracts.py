"""Profile v2 public contracts (specs/011-z1-profile, docs/design/profile-v2).

This module is the importable API surface other lines consume (the
``profile-api`` checkpoint).  It freezes the typed vocabulary only: facet
descriptors, item schemas, value states, session identity, config intents,
applied receipts and the Harness application port.  Product behaviour lives
in the service modules; nothing here executes or stores anything.

Semantics sources (do not restate them differently elsewhere):
- docs/design/profile-v2/contracts.md §1 (facet providers), §3 (operations)
- docs/design/profile-v2/data-model.md §1-§2 (entities, resolution)
- docs/design/profile-v2/application.md §2 (Harness port)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from .errors import ProfileError

FACET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# --------------------------------------------------------------------------
# value states (PF04): unset / explicit value / disabled / provider-absent
# --------------------------------------------------------------------------


class _UnsetType:
    """Sentinel for "not set — defer to the target default".

    Deliberately a distinct type, not ``None``: an explicit ``None`` value is
    a real value when the item schema allows it (PF04).  Not equal to
    anything except itself; JSON-encodes as the string ``"$unset"`` only for
    diagnostics, never for stored bindings (unset items are simply absent).
    """

    _instance: "_UnsetType | None" = None

    def __new__(cls) -> "_UnsetType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _UnsetType()


class ValueDisabled:
    """Explicit business "off" — distinct from unset and from an empty value."""

    __slots__ = ("_reason",)

    def __init__(self, reason: str | None = None) -> None:
        if reason is not None and not isinstance(reason, str):
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "disabled reason must be a string",
                status=422,
            )
        object.__setattr__(self, "_reason", reason)

    @property
    def reason(self) -> str | None:
        return self._reason

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ValueDisabled) and other._reason == self._reason

    def __hash__(self) -> int:
        return hash(("ValueDisabled", self._reason))

    def __repr__(self) -> str:
        return f"ValueDisabled(reason={self._reason!r})"


def value_state(value: Any) -> str:
    """Classify one stored/resolved value into the four-state vocabulary.

    Returns ``'unset' | 'explicit' | 'disabled' | 'provider-absent'``.
    ``provider-absent`` is never a stored state; callers pass it explicitly
    when projecting registry absence (see resolution).
    """
    if value is UNSET:
        return "unset"
    if isinstance(value, ValueDisabled):
        return "disabled"
    return "explicit"


# --------------------------------------------------------------------------
# item schema: controlled subset, unknown keys refused (PV-03)
# --------------------------------------------------------------------------

_SCHEMA_TYPES = frozenset({
    "string", "integer", "number", "boolean", "array", "object", "null",
})
_SCHEMA_KEYS = frozenset({
    "type", "enum", "items", "minItems", "maxItems", "minimum", "maximum",
    "default", "title", "description", "allowNull",
})
_EFFECTS = frozenset({
    "configuration", "capability-selection", "permission", "instruction",
})
_SENSITIVITIES = frozenset({"non-secret", "opaque-reference"})
_CATEGORIES = frozenset({
    "model", "capabilities", "behavior", "instructions", "advanced",
})


def validate_schema_shape(schema: Mapping[str, Any], *, where: str) -> None:
    """Validate the *declaration* of one value schema (not a value).

    Unknown schema keywords are refused so a provider cannot smuggle an
    unreviewed evaluation vocabulary into the stored contract.
    """
    if not isinstance(schema, Mapping):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", f"{where}: schema must be an object",
            status=422,
        )
    unknown = sorted(set(schema) - _SCHEMA_KEYS)
    if unknown:
        raise ProfileError(
            "FACET_INVALID_PROVIDER",
            f"{where}: unknown schema keywords {unknown}",
            status=422,
        )
    kind = schema.get("type")
    if kind not in _SCHEMA_TYPES:
        raise ProfileError(
            "FACET_INVALID_PROVIDER", f"{where}: unsupported schema type {kind!r}",
            status=422,
        )
    if "items" in schema:
        if kind != "array":
            raise ProfileError(
                "FACET_INVALID_PROVIDER", f"{where}: items requires type=array",
                status=422,
            )
        validate_schema_shape(schema["items"], where=f"{where}.items")
    enum_values = schema.get("enum")
    if enum_values is not None:
        if not isinstance(enum_values, list) or not enum_values:
            raise ProfileError(
                "FACET_INVALID_PROVIDER", f"{where}: enum must be a non-empty list",
                status=422,
            )
        _ = json.dumps(enum_values, ensure_ascii=False)
    for key in ("minItems", "maxItems", "minimum", "maximum"):
        if key in schema and not isinstance(schema[key], int):
            raise ProfileError(
                "FACET_INVALID_PROVIDER", f"{where}: {key} must be an integer",
                status=422,
            )
    if "description" in schema and not isinstance(schema["description"], str):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", f"{where}: description must be a string",
            status=422,
        )
    if "title" in schema and not isinstance(schema["title"], str):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", f"{where}: title must be a string",
            status=422,
        )
    if "allowNull" in schema and not isinstance(schema["allowNull"], bool):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", f"{where}: allowNull must be a boolean",
            status=422,
        )


def validate_value_against_schema(schema: Mapping[str, Any], value: Any,
                                  *, where: str = "value") -> None:
    """Validate one value against the controlled schema subset."""
    kind = schema.get("type")
    nullable = bool(schema.get("allowNull")) and value is None
    if value is None and not nullable:
        raise ProfileError(
            "FACET_VALUE_INVALID", f"{where}: null is not allowed",
            status=422,
        ).with_item(where)
    if value is None:
        return
    type_ok: bool
    if kind == "string":
        type_ok = isinstance(value, str)
    elif kind == "integer":
        type_ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        type_ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "boolean":
        type_ok = isinstance(value, bool)
    elif kind == "array":
        type_ok = isinstance(value, list)
    elif kind == "object":
        type_ok = isinstance(value, dict)
    else:  # "null"
        type_ok = value is None
    if not type_ok:
        raise ProfileError(
            "FACET_VALUE_INVALID",
            f"{where}: expected {kind}, got {type(value).__name__}",
            status=422,
        ).with_item(where)
    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise ProfileError(
            "FACET_VALUE_INVALID", f"{where}: {value!r} is not one of the "
            "allowed values", status=422,
        ).with_item(where)
    if kind == "array":
        for bound, cmp in (("minItems", lambda n, v: v >= n),
                           ("maxItems", lambda n, v: v <= n)):
            if bound in schema and not cmp(schema[bound], len(value)):
                raise ProfileError(
                    "FACET_VALUE_INVALID",
                    f"{where}: array length violates {bound}",
                    status=422,
                ).with_item(where)
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, element in enumerate(value):
                validate_value_against_schema(
                    item_schema, element, where=f"{where}[{index}]",
                )
    if kind in ("integer", "number"):
        for bound, cmp in (("minimum", lambda n, v: v >= n),
                           ("maximum", lambda n, v: v <= n)):
            if bound in schema and not cmp(schema[bound], value):
                raise ProfileError(
                    "FACET_VALUE_INVALID",
                    f"{where}: value violates {bound}", status=422,
                ).with_item(where)


# --------------------------------------------------------------------------
# applicability (contracts.md §1): three-valued, unknown never promotes
# --------------------------------------------------------------------------


class Applicability(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# facet descriptor / item descriptor
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemDescriptor:
    """One configurable item contributed by a facet provider (PF01-PF04)."""

    item_id: str
    value_schema: Mapping[str, Any]
    optional: bool = False
    override_supported: bool = True
    sensitivity: str = "non-secret"
    effect: str = "configuration"
    title: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not ITEM_ID_RE.fullmatch(self.item_id):
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"invalid item_id: {self.item_id!r}", status=422,
            )
        validate_schema_shape(self.value_schema, where=f"item {self.item_id}")
        if "default" in self.value_schema:
            validate_value_against_schema(
                self.value_schema, self.value_schema["default"],
                where=f"item {self.item_id} default",
            )
        if self.sensitivity not in _SENSITIVITIES:
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"item {self.item_id}: invalid sensitivity {self.sensitivity!r}",
                status=422,
            )
        if self.effect not in _EFFECTS:
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"item {self.item_id}: invalid effect {self.effect!r}",
                status=422,
            )
        for name, value in (("title", self.title), ("description", self.description)):
            if not isinstance(value, str):
                raise ProfileError(
                    "FACET_INVALID_PROVIDER",
                    f"item {self.item_id}: {name} must be a string", status=422,
                )


@dataclass(frozen=True)
class FacetDescriptor:
    """Static declaration of one configuration facet (contracts.md §1)."""

    facet_id: str
    api_major: int
    schema_version: str
    label: str
    description: str = ""
    category: str = "advanced"
    order: int = 100
    item_descriptors: tuple[ItemDescriptor, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.facet_id, str) or not FACET_ID_RE.fullmatch(self.facet_id):
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"invalid facet_id: {self.facet_id!r}", status=422,
            )
        if not isinstance(self.api_major, int) or self.api_major < 1:
            raise ProfileError(
                "FACET_INVALID_PROVIDER", "api_major must be a positive int",
                status=422,
            )
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ProfileError(
                "FACET_INVALID_PROVIDER", "schema_version must be a non-empty string",
                status=422,
            )
        if not isinstance(self.label, str) or not self.label.strip():
            raise ProfileError(
                "FACET_INVALID_PROVIDER", "label must be a non-empty string",
                status=422,
            )
        if self.category not in _CATEGORIES:
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"invalid category {self.category!r}", status=422,
            )
        if not isinstance(self.order, int):
            raise ProfileError(
                "FACET_INVALID_PROVIDER", "order must be an int", status=422,
            )
        ids = [item.item_id for item in self.item_descriptors]
        if len(ids) != len(set(ids)):
            raise ProfileError(
                "FACET_INVALID_PROVIDER", "duplicate item_id in facet descriptor",
                status=422,
            )

    def item(self, item_id: str) -> ItemDescriptor | None:
        for candidate in self.item_descriptors:
            if candidate.item_id == item_id:
                return candidate
        return None

    def require_item(self, item_id: str) -> ItemDescriptor:
        found = self.item(item_id)
        if found is None:
            raise ProfileError(
                "FACET_VALUE_INVALID",
                f"unknown item {item_id} for facet {self.facet_id}",
                status=422,
            ).with_item(f"{self.facet_id}/{item_id}")
        return found


# --------------------------------------------------------------------------
# violations, intents, receipts, journal
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """One locate-able, non-secret validation failure."""

    facet_id: str
    item_id: str
    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.message, str):
            raise ValueError("violation message must be a string")


@dataclass(frozen=True)
class MigratedItems:
    """Result of a successful schema migration: new-shape stored items."""

    items: tuple[tuple[str, Any], ...]
    from_schema_version: str
    to_schema_version: str


@dataclass(frozen=True)
class MigrationUnsupported:
    reason: str
    from_schema_version: str
    to_schema_version: str


@dataclass(frozen=True)
class ConfigIntent:
    """One provider-declared native configuration step (contracts.md §1).

    Intents only *declare* what this facet owns — ``set`` or ``reset`` on one
    native key with its source facts.  Executing them is the Harness seam's
    job (application.md §1); Profile never runs them itself.
    """

    facet_id: str
    item_id: str
    op: str  # 'set' | 'reset'
    native_key: str
    source: str  # 'profile@<rev>' | 'session-overlay@<rev>'
    value: Any = UNSET  # set intents carry the value; reset intents stay UNSET
    request_hash: str = ""

    def __post_init__(self) -> None:
        if self.op not in ("set", "reset"):
            raise ProfileError(
                "PROFILE_VALUE_INVALID", f"invalid intent op {self.op!r}",
                status=422,
            )
        if self.op == "set" and self.value is UNSET:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "set intent requires a value",
                status=422,
            )
        if self.op == "reset" and self.value is not UNSET:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "reset intent must not carry a value",
                status=422,
            )
        if not self.native_key:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "intent native_key is required",
                status=422,
            )


@dataclass(frozen=True)
class CompileResult:
    intents: tuple[ConfigIntent, ...] = ()
    violations: tuple[Violation, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations


@dataclass(frozen=True)
class SessionRef:
    """Canonical, stable session identity (data-model.md §1).

    ``realm`` is the owning server data domain; ``harness_id`` the Harness;
    ``native_session_key`` the native-side key.  ``session_uid`` is the
    persistent primary key.  A short-lived channel/route id is *not* a
    session identity and must never be stored in its place.
    """

    realm: str
    harness_id: str
    native_session_key: str
    session_uid: str

    def __post_init__(self) -> None:
        for name in ("realm", "harness_id", "native_session_key", "session_uid"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ProfileError(
                    "PROFILE_VALUE_INVALID",
                    f"SessionRef.{name} must be a non-empty string", status=422,
                )

    @classmethod
    def legacy(cls, session_id: str, *, harness_id: str) -> "SessionRef":
        """Wrap a v1 single-string session id (migration path only)."""
        return cls(
            realm="local", harness_id=harness_id,
            native_session_key=session_id, session_uid=f"legacy:{session_id}",
        )

    def routing_key(self) -> str:
        """Diagnostics/short-lived routing only — never a stored identity."""
        return f"{self.realm}/{self.harness_id}/{self.native_session_key}"


# evidence kinds are an open, adapter-declared vocabulary; the two below are
# the only ones Profile itself can assert.
EVIDENCE_LEGACY_UNVERIFIED = "legacy-unverified"
EVIDENCE_PORT_CONFIRMED = "port-confirmed"


@dataclass(frozen=True)
class AppliedReceipt:
    """Proof that one application actually took effect (data-model.md §1).

    ``evidence_kind`` names *how* it was proven; a DB read-back is never a
    runtime proof and can only ever appear as ``legacy-unverified``.
    """

    operation_id: str
    session_ref: SessionRef
    runtime_generation: str
    config_digest: str
    profile_id: str
    profile_revision: int
    overlay_revision: int | None
    policy_revision: int
    provider_generations: Mapping[str, int]
    evidence_kind: str
    confirmed_at: str
    execution_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile_revision, int) or self.profile_revision < 1:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "receipt profile_revision must be >= 1",
                status=422,
            )
        if self.evidence_kind == EVIDENCE_LEGACY_UNVERIFIED:
            raise ProfileError(
                "LEGACY_RECEIPT_UNVERIFIED",
                "a legacy-unverified record can never be stored as a receipt",
                status=409,
            )

    def as_public_dict(self) -> dict[str, Any]:
        """Non-secret projection (no config values, no credentials)."""
        return {
            "operation_id": self.operation_id,
            "session_uid": self.session_ref.session_uid,
            "realm": self.session_ref.realm,
            "harness_id": self.session_ref.harness_id,
            "native_session_key": self.session_ref.native_session_key,
            "runtime_generation": self.runtime_generation,
            "config_digest": self.config_digest,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
            "overlay_revision": self.overlay_revision,
            "policy_revision": self.policy_revision,
            "provider_generations": dict(self.provider_generations),
            "evidence_kind": self.evidence_kind,
            "confirmed_at": self.confirmed_at,
            "execution_id": self.execution_id,
        }


JOURNAL_STATES = ("planned", "applying", "confirmed", "rejected", "unknown")


@dataclass(frozen=True)
class JournalEntry:
    """One application attempt's durable facts (application.md §3)."""

    operation_id: str
    session_ref: SessionRef
    state: str
    profile_id: str
    profile_revision: int
    plan_digest: str
    failure: str | None = None
    detail_refs: tuple[str, ...] = ()  # non-secret references only
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.state not in JOURNAL_STATES:
            raise ProfileError(
                "PROFILE_VALUE_INVALID",
                f"invalid journal state {self.state!r}", status=422,
            )

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "session_uid": self.session_ref.session_uid,
            "state": self.state,
            "profile_id": self.profile_id,
            "profile_revision": self.profile_revision,
            "plan_digest": self.plan_digest,
            "failure": self.failure,
            "detail_refs": list(self.detail_refs),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --------------------------------------------------------------------------
# mechanism policy (data-model.md §1 MechanismPolicy)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MechanismPolicy:
    """Session-modification and facet-enablement policy for one server realm.

    This is configuration-surface policy only.  It grants no execution
    permission, carries no secrets, and never overrides Harness/平台 runtime
    authorization (G03).
    """

    realm: str
    revision: int
    facet_enabled: Mapping[str, bool] = field(default_factory=dict)
    allow_user_override_writes_global: bool = True
    allow_user_override_writes: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.realm, str) or not self.realm:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "policy realm must be a non-empty string",
                status=422,
            )
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "policy revision must be a positive int",
                status=422,
            )
        for facet_id, enabled in self.facet_enabled.items():
            if not isinstance(enabled, bool):
                raise ProfileError(
                    "PROFILE_VALUE_INVALID",
                    f"facet_enabled[{facet_id!r}] must be boolean", status=422,
                )
        for facet_id, allowed in self.allow_user_override_writes.items():
            if not isinstance(allowed, bool):
                raise ProfileError(
                    "PROFILE_VALUE_INVALID",
                    f"allow_user_override_writes[{facet_id!r}] must be boolean",
                    status=422,
                )

    def facet_enabled_for(self, facet_id: str) -> bool:
        """Default-facilitated: registered facets are enabled unless disabled."""
        return self.facet_enabled.get(facet_id, True)

    def override_writes_allowed(self, facet_id: str | None = None) -> bool:
        if not self.allow_user_override_writes_global:
            return False
        if facet_id is not None:
            return self.allow_user_override_writes.get(facet_id, True)
        return True


# --------------------------------------------------------------------------
# Harness application port (application.md §2) — consumed, never invented
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessTargetFacts:
    """Server-verified facts about the application target."""

    session_ref: SessionRef
    runtime_generation: str
    capability_facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InspectResult:
    target: HarnessTargetFacts
    evidence_kind: str
    current_config_digest: str | None = None


@dataclass(frozen=True)
class PlannedItem:
    facet_id: str
    item_id: str
    op: str
    status: str  # 'live-update' | 'restart-resume' | 'blocked'
    reason: str = ""


@dataclass(frozen=True)
class PlanResult:
    session_ref: SessionRef
    operation_key: str
    overall: str  # 'live-update' | 'restart-resume' | 'blocked'
    items: tuple[PlannedItem, ...] = ()
    plan_digest: str = ""
    fence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.overall == "blocked"


@dataclass(frozen=True)
class ApplyConfirmed:
    """Port-confirmed application; the only outcome that yields a receipt."""

    state: str
    receipt: AppliedReceipt


@dataclass(frozen=True)
class ApplyRejected:
    """Port proves the target still runs the previous configuration."""

    state: str
    reason: str
    items: tuple[PlannedItem, ...] = ()


@dataclass(frozen=True)
class ApplyUnknown:
    """Outcome cannot be proven; blocks the next turn until reconcile."""

    state: str
    reason: str


@dataclass(frozen=True)
class ReconcileOutcome:
    state: str  # 'confirmed-current' | 'rejected-unchanged' | 'unknown'
    receipt: AppliedReceipt | None = None
    reason: str = ""


@runtime_checkable
class HarnessConfigPort(Protocol):
    """The Harness-owned application seam (application.md §2).

    Profile consumes this port; it never implements it.  When no port is
    registered in the host, switch applications are typed-blocked — they are
    never reported as applied (PV-07, G09-G11).
    """

    def inspect(self, target: SessionRef) -> InspectResult: ...

    def plan(self, target: SessionRef, desired: tuple[ConfigIntent, ...],
             operation_key: str) -> PlanResult: ...

    def apply(self, plan: PlanResult,
              desired: tuple[ConfigIntent, ...]) -> ApplyConfirmed | ApplyRejected | ApplyUnknown: ...

    def reconcile(self, operation_key: str,
                  target: SessionRef) -> ReconcileOutcome: ...


class HarnessConfigPortAbsent(RuntimeError):
    """Typed absence of a registered Harness application port."""


# --------------------------------------------------------------------------
# v2 facet provider protocol + v1 adapter
# --------------------------------------------------------------------------


@runtime_checkable
class FacetProviderV2(Protocol):
    """v2 provider contract (contracts.md §1): declarative, pure, scoped."""

    def descriptor(self) -> FacetDescriptor: ...

    def applicability(self, capability_facts: Mapping[str, Any]) -> Applicability: ...

    def validate(self, items: Mapping[str, Any],
                 reference_facts: Mapping[str, Any]) -> tuple[Violation, ...]: ...

    def migrate(self, old_schema_version: str,
                stored_items: Mapping[str, Any]) -> MigratedItems | MigrationUnsupported: ...

    def compile(self, resolved_items: Mapping[str, Any],
                target_facts: Mapping[str, Any]) -> CompileResult: ...


def validate_v2_provider_shape(provider: Any) -> FacetDescriptor:
    """Structural acceptance for a v2 provider before registration."""
    descriptor_factory = getattr(provider, "descriptor", None)
    if not callable(descriptor_factory):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", "v2 provider is missing descriptor()",
            status=422,
        )
    descriptor = descriptor_factory()
    if not isinstance(descriptor, FacetDescriptor):
        raise ProfileError(
            "FACET_INVALID_PROVIDER", "descriptor() must return FacetDescriptor",
            status=422,
        )
    for method in ("applicability", "validate", "migrate", "compile"):
        if not callable(getattr(provider, method, None)):
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"v2 provider is missing {method}()", status=422,
            )
    return descriptor
