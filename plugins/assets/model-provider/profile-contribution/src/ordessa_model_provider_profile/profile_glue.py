"""PB-6: the ``assets.model-provider`` facet, registered through the REAL
profile-api v2 facet surface (REQ-Z3-3 landed by P-A's r2, consumed here —
this package never re-authors a registry of its own and never writes
``plugins/profile``).

Consumption SHA: profile-api r2 ``implementationSha =
e6f720d347d3258bfb795c12ee703676c24ca24f`` (branch ``codex/014-a-profile``,
merged into this tree at the PB-6 merge commit; ancestry recorded in the P-B
report). The provider below speaks the published ``FacetProviderV2``
protocol (``ordessa_profile.facets.FacetRegistry.register(..., v2=True)``):

- one atomic item ``choice`` (provider+model never split, MP-01), bound to
  the profile's harness — the binding rule lives in
  :mod:`ordessa_model_provider_profile.facet_registration` and is enforced in
  ``validate``/``compile`` against the target facts' harness id;
- ``compile`` emits ``ConfigIntent``s with the ModelChoice payload the C2
  adapters' payload schema validates (the facet never invents native keys);
- session semantics (override/switch clearing) stay with
  :class:`EffectiveChoiceResolver`; the archive-time reference check stays
  with :class:`ProfileViewReferencePort`.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_profile.contracts import (
    Applicability, CompileResult, ConfigIntent, FacetDescriptor,
    FacetProviderV2, ItemDescriptor, MigratedItems, MigrationUnsupported,
    UNSET, Violation,
)
from ordessa_profile.errors import ProfileError
from ordessa_profile.facets import FacetRegistry

from .facet_registration import (
    API_MAJOR, CHOICE_ITEM_ID, FACET_ID, SCHEMA_VERSION,
    validate_choice_value,
)

#: The brands the facet serves (the C2 adapters' harness ids, frozen).
BRANDS = ("pi", "codex", "claude-code")

_OWNER_PLUGIN_ID = "ordessa.model-provider-profile"

#: The native key the choice intent addresses (the facet declares WHAT it
#: owns; the harness seam decides how it lands per brand).
_CHOICE_NATIVE_KEY = "model-provider/choice"


def facet_descriptor_v2() -> FacetDescriptor:
    """The v2 declaration of the single atomic choice item."""
    return FacetDescriptor(
        facet_id=FACET_ID, api_major=API_MAJOR, schema_version=str(SCHEMA_VERSION),
        label="模型选择", description="Provider/Model 原子选择(不拆分继承)",
        category="model", order=10,
        item_descriptors=(ItemDescriptor(
            item_id=CHOICE_ITEM_ID,
            value_schema={
                "type": "object",
                "title": "ModelChoice",
                "description": "exactly {harnessId, providerConfigId, modelId}",
            },
            optional=False, override_supported=True, sensitivity="non-secret",
            effect="configuration", title="默认模型",
        ),),
    )


class ModelProviderFacetProvider:
    """The facet as a real v2 provider (protocol-checked at registration)."""

    def __init__(self) -> None:
        self._descriptor = facet_descriptor_v2()

    def descriptor(self) -> FacetDescriptor:
        return self._descriptor

    def applicability(self, capability_facts: Mapping[str, Any]) -> Applicability:
        harness = capability_facts.get("harnessId")
        if harness in BRANDS:
            return Applicability.SUPPORTED
        if harness is None:
            return Applicability.UNKNOWN
        return Applicability.UNSUPPORTED

    def validate(self, items: Mapping[str, Any],
                 reference_facts: Mapping[str, Any]) -> tuple[Violation, ...]:
        harness = reference_facts.get("harnessId")
        if not isinstance(harness, str) or not harness:
            return (_violation(CHOICE_ITEM_ID, "HARNESS_FACT_MISSING",
                               "reference facts carry no harness id"),)
        value = items.get(CHOICE_ITEM_ID)
        if value is None:
            return ()  # an absent optional-less item is the profile side's gap
        try:
            validate_choice_value(value, harness_id=harness)
        except Exception as error:  # FacetValueError is the typed shape here
            return (_violation(CHOICE_ITEM_ID, "PROFILE_FACET_VALUE_INVALID",
                               str(error)),)
        return ()

    def migrate(self, old_schema_version: str,
                stored_items: Mapping[str, Any]) -> MigratedItems | MigrationUnsupported:
        return MigrationUnsupported(
            reason=f"facet {FACET_ID} has no migration path from {old_schema_version!r}",
            from_schema_version=old_schema_version,
            to_schema_version=str(SCHEMA_VERSION))

    def compile(self, resolved_items: Mapping[str, Any],
                target_facts: Mapping[str, Any]) -> CompileResult:
        harness = target_facts.get("harnessId")
        value = resolved_items.get(CHOICE_ITEM_ID)
        if not isinstance(harness, str) or not harness:
            return CompileResult(violations=(
                _violation(CHOICE_ITEM_ID, "HARNESS_FACT_MISSING",
                           "target facts carry no harness id"),))
        if value is None:
            return CompileResult(violations=(
                _violation(CHOICE_ITEM_ID, "CHOICE_MISSING",
                           "the resolved profile carries no choice"),))
        try:
            validate_choice_value(value, harness_id=harness)
        except Exception as error:
            return CompileResult(violations=(
                _violation(CHOICE_ITEM_ID, "PROFILE_FACET_VALUE_INVALID",
                           str(error)),))
        source = str(target_facts.get("source") or "profile@resolved")
        return CompileResult(intents=(ConfigIntent(
            facet_id=FACET_ID, item_id=CHOICE_ITEM_ID, op="set",
            native_key=_CHOICE_NATIVE_KEY, source=source, value=dict(value),
        ),))


def _violation(item_id: str, code: str, message: str) -> Violation:
    return Violation(facet_id=FACET_ID, item_id=item_id, code=code, message=message)


def register_model_provider_facet(registry: FacetRegistry,
                                  *, owner_plugin_id: str = _OWNER_PLUGIN_ID) -> ModelProviderFacetProvider:
    """Register the facet into the REAL profile facet registry (v2 surface).

    The owner is injected here exactly as the profile host scope injects it
    in production; a second owner claiming the facet is the registry's
    ``FACET_ID_CONFLICT`` refusal (pinned in the tests).
    """
    provider = ModelProviderFacetProvider()
    assert isinstance(provider, FacetProviderV2)  # protocol conformance, cheap
    registry.register(provider, owner_plugin_id=owner_plugin_id, v2=True)
    return provider
