"""Facet provider protocol and registry (US4, contracts/facet-provider.md).

The core owns no facet business semantics: providers enter as data through
this protocol, so a brand-new facet requires zero core changes (FR-014).

v2 adds (docs/design/profile-v2/contracts.md §1): the declarative
``FacetProviderV2`` protocol, a backward-compatible v1 adapter, host-injected
ownership (the registering plugin id is recorded by the caller, never
self-reported) and a registry generation counter that invalidates late
in-flight results after any register/unregister.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .contracts import (
    Applicability,
    CompileResult,
    ConfigIntent,
    FacetDescriptor,
    MigratedItems,
    MigrationUnsupported,
    UNSET,
    validate_v2_provider_shape,
    Violation,
)
from .errors import ProfileError

_FACET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@runtime_checkable
class FacetProvider(Protocol):
    facet_id: str
    owner_plugin_id: str
    facet_version: str
    item_ids: tuple[str, ...]

    def title(self) -> str: ...

    def applies_to(self, harness_id: str) -> bool: ...

    def validate_value(self, item_id: str, value: Any) -> None: ...

    def session_apply(self, item_id: str, current_value: Any,
                      target_value: Any) -> str:
        """``"apply_next_turn"`` or ``"blocked"`` — never inferred by core."""

    def validate_resolved(self, values: Mapping[str, Any]) -> None:
        """Cross-item validation of this facet's resolved values (FR-021);
        raise ProfileError("CONFIG_CONFLICT") with .conflicts to refuse."""

    def check_stored_value(self, stored_facet_version: str, item_id: str,
                           value: Any) -> "StoredValueVerdict": ...


@dataclass(frozen=True)
class StoredValueVerdict:
    """Reload ruling for one stored facet value (US4.5)."""

    kind: str  # "accepted" | "migrated" | "incompatible"
    value: Any = None

    @classmethod
    def accepted(cls) -> "StoredValueVerdict":
        return cls("accepted")

    @classmethod
    def migrated(cls, value: Any) -> "StoredValueVerdict":
        return cls("migrated", value=value)

    @classmethod
    def incompatible(cls) -> "StoredValueVerdict":
        return cls("incompatible")


def validate_provider_shape(provider: Any) -> None:
    """Structural acceptance check; raises FACET_VALUE_INVALID-shaped errors
    as ProfileError with stable codes before anything is registered."""
    for attr in ("facet_id", "owner_plugin_id", "facet_version"):
        value = getattr(provider, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"facet provider.{attr} must be a non-empty string",
                status=422,
            )
    if not _FACET_ID.fullmatch(provider.facet_id):
        raise ProfileError(
            "FACET_INVALID_PROVIDER",
            f"invalid facet_id: {provider.facet_id!r}",
            status=422,
        )
    item_ids = getattr(provider, "item_ids", None)
    if not isinstance(item_ids, tuple) or not item_ids or \
            not all(isinstance(i, str) and i for i in item_ids):
        raise ProfileError(
            "FACET_INVALID_PROVIDER",
            "facet provider.item_ids must be a non-empty tuple of strings",
            status=422,
        )
    if len(set(item_ids)) != len(item_ids):
        raise ProfileError(
            "FACET_INVALID_PROVIDER",
            "facet provider.item_ids must be unique",
            status=422,
        )
    for method in (
        "title", "applies_to", "validate_value", "session_apply",
        "validate_resolved", "check_stored_value",
    ):
        if not callable(getattr(provider, method, None)):
            raise ProfileError(
                "FACET_INVALID_PROVIDER",
                f"facet provider is missing {method}()",
                status=422,
            )


class FacetRegistry:
    """facet_id -> provider; unique across owners (US4.3), no last-wins.

    ``generation`` increments on every register/unregister.  Callers capture
    ``generation`` when they start a resolve/compile flow and re-check it
    before using the result: anything computed against an older generation
    is stale and must be refused (FACET_GENERATION_STALE) — a provider that
    vanished mid-flight can no longer contribute (G13).
    """

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}
        self._owners: dict[str, str] = {}
        self._generation: int = 1

    @property
    def generation(self) -> int:
        return self._generation

    def owner_of(self, facet_id: str) -> str | None:
        return self._owners.get(facet_id)

    def get(self, facet_id: str) -> Any | None:
        return self._providers.get(facet_id)

    def require(self, facet_id: str) -> Any:
        provider = self._providers.get(facet_id)
        if provider is None:
            raise ProfileError(
                "FACET_UNKNOWN",
                f"facet provider is not loaded: {facet_id}",
                status=409,
            ).with_item(facet_id)
        return provider

    def registered(self) -> tuple[Any, ...]:
        return tuple(self._providers.values())

    def is_registered(self, provider: Any) -> bool:
        return self._providers.get(provider.facet_id) is provider

    def check_current(self, generation: int) -> None:
        if generation != self._generation:
            raise ProfileError(
                "FACET_GENERATION_STALE",
                f"facet registry moved on (was {generation}, "
                f"now {self._generation}); re-run the flow",
                status=409,
            )

    @staticmethod
    def _facet_id_of(provider: Any, v2: bool) -> str:
        return provider.descriptor().facet_id if v2 else provider.facet_id

    def register(self, provider: Any, *, owner_plugin_id: str | None = None,
                 v2: bool = False) -> None:
        if v2:
            validate_v2_provider_shape(provider)
            if not isinstance(owner_plugin_id, str) or not owner_plugin_id:
                raise ProfileError(
                    "FACET_INVALID_PROVIDER",
                    "v2 registration requires the host-injected owner",
                    status=422,
                )
            declared_owner = owner_plugin_id
        else:
            validate_provider_shape(provider)
            declared_owner = owner_plugin_id or provider.owner_plugin_id
        facet_id = self._facet_id_of(provider, v2)
        existing = self._providers.get(facet_id)
        if existing is not None and existing is not provider:
            raise ProfileError(
                "FACET_ID_CONFLICT",
                f"facet {facet_id} is already declared by "
                f"{self._owners.get(facet_id, 'another plugin')!r}",
                status=409,
            )
        # Ownership is injected by the host scope at registration time; a
        # provider's self-declared owner_plugin_id is never trusted for the
        # v2 surface (contracts.md §1).
        self._owners[facet_id] = declared_owner
        self._providers[facet_id] = provider
        if existing is not provider:
            self._generation += 1

    def unregister(self, provider: Any) -> None:
        """Idempotent unload: absence of the provider must never be an error
        that would keep a stale contribution alive."""
        is_v2 = callable(getattr(provider, "descriptor", None)) and \
            callable(getattr(provider, "compile", None))
        facet_id = self._facet_id_of(provider, is_v2)
        current = self._providers.get(facet_id)
        if current is provider:
            del self._providers[facet_id]
            self._generation += 1


class V1ProviderAdapter:
    """Adapt a v1 ``FacetProvider`` to the v2 declarative surface.

    The v1 provider keeps working unchanged: ``applies_to`` maps to
    applicability, ``validate_value``/``validate_resolved`` stay authoritative
    for validation, and the old ``session_apply`` string verdict decides
    whether differences compile at all.  The adapter never fabricates v2
    declarations the v1 provider did not make.
    """

    def __init__(self, provider: Any, *, descriptor: FacetDescriptor) -> None:
        self._provider = provider
        self._descriptor = descriptor
        self.facet_id = provider.facet_id
        self.owner_plugin_id = provider.owner_plugin_id
        self.facet_version = provider.facet_version
        self.item_ids = provider.item_ids

    @property
    def v1(self) -> Any:
        return self._provider

    def descriptor(self) -> FacetDescriptor:
        return self._descriptor

    def title(self) -> str:
        return self._provider.title()

    def applies_to(self, harness_id: str) -> bool:
        return self._provider.applies_to(harness_id)

    def applicability(self, capability_facts: Mapping[str, Any]) -> Applicability:
        harness_id = capability_facts.get("harness_id")
        if not isinstance(harness_id, str) or not harness_id:
            return Applicability.UNKNOWN
        if self._provider.applies_to(harness_id):
            return Applicability.SUPPORTED
        return Applicability.UNSUPPORTED

    def validate_value(self, item_id: str, value: Any) -> None:
        self._provider.validate_value(item_id, value)

    def validate(self, items: Mapping[str, Any],
                 reference_facts: Mapping[str, Any]) -> tuple:
        """v1 providers validate per item; the first failure becomes a
        violation list entry (v1 raised, v2 returns violations)."""
        violations = []
        for item_id, value in sorted(items.items()):
            try:
                self._provider.validate_value(item_id, value)
            except ProfileError as exc:
                violations.append(_violation_from_error(self.facet_id, item_id, exc))
            except (TypeError, ValueError) as exc:
                violations.append(Violation(
                    facet_id=self.facet_id, item_id=item_id,
                    code="FACET_VALUE_INVALID", message=str(exc),
                ))
        return tuple(violations)

    def validate_resolved(self, values: Mapping[str, Any]) -> None:
        self._provider.validate_resolved(values)

    def migrate(self, old_schema_version: str,
                stored_items: Mapping[str, Any]) -> MigratedItems | MigrationUnsupported:
        """v1 stored-value compatibility pass expressed as v2 migration."""
        verdicts: dict[str, Any] = {}
        for item_id, value in sorted(stored_items.items()):
            ruling = self._provider.check_stored_value(
                old_schema_version, item_id, value,
            )
            if ruling.kind == "accepted":
                verdicts[item_id] = value
            elif ruling.kind == "migrated":
                verdicts[item_id] = ruling.value
            else:
                return MigrationUnsupported(
                    reason=f"stored value for {item_id} is incompatible",
                    from_schema_version=old_schema_version,
                    to_schema_version=self._descriptor.schema_version,
                )
        return MigratedItems(
            items=tuple(sorted(verdicts.items())),
            from_schema_version=old_schema_version,
            to_schema_version=self._descriptor.schema_version,
        )

    def compile(self, resolved_items: Mapping[str, Any],
                target_facts: Mapping[str, Any]) -> CompileResult:
        harness_id = target_facts.get("harness_id")
        if not self._provider.applies_to(harness_id):
            return CompileResult(violations=(Violation(
                facet_id=self.facet_id, item_id="*",
                code="FACET_NOT_APPLICABLE",
                message=f"facet does not apply to harness {harness_id!r}",
            ),))
        intents = []
        revision = target_facts.get("source_revision", "")
        for item_id, entry in sorted(resolved_items.items()):
            value = entry["value"] if isinstance(entry, dict) and "value" in entry \
                else entry
            if value is UNSET:
                continue
            verdict = self._provider.session_apply(item_id, None, value)
            if verdict != "apply_next_turn":
                return CompileResult(violations=(Violation(
                    facet_id=self.facet_id, item_id=item_id,
                    code="SWITCH_ITEM_BLOCKED",
                    message=f"v1 provider blocks session application for {item_id}",
                ),))
            intents.append(ConfigIntent(
                facet_id=self.facet_id, item_id=item_id, op="set",
                native_key=_native_key(self.facet_id, item_id),
                source=f"profile@{revision}" if revision else "profile",
                value=value,
            ))
        return CompileResult(intents=tuple(intents))


def _violation_from_error(facet_id: str, item_id: str, exc: ProfileError):
    return Violation(
        facet_id=facet_id, item_id=item_id,
        code=exc.code or "FACET_VALUE_INVALID", message=exc.message,
    )


def _native_key(facet_id: str, item_id: str) -> str:
    return f"{facet_id}.{item_id}"
