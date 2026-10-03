"""Thin memory→harness-api bridge: the eight brand adapters register into
the real C2 point (``harness.configuration-adapters``) as typed
``ConfigurationAdapter``s (MB-1).

Direction discipline (model-provider form, not its imports): this module may
import the public ``ordessa_harness_api`` contract; the reverse import never
exists.

The honest C2 semantics of this facet, pinned here and in the conformance
tests:

* the binding has NO harness-writable native target — FieldClaim's closed
  vocabulary (file/directory/environment) has no instruction-slot kind, and
  memory injection rides the instruction-slot facet merge (AR-4, EXT pending,
  not on this baseline). The descriptors therefore claim nothing;
* ``assess`` is ``unknown`` for an empty probe, ``unsupported`` while the
  injection mount is absent (spec red line 5: a missing mount is reported,
  never silently degraded), ``supported`` only for a brand the binding
  actually mounts — with the recorded coexistence note for the four brands
  that have native memory;
* ``compile`` refuses honestly: on this baseline nothing is harness-writable,
  the binding is consumed in-domain through the plugin's own validated
  binding store (``memory.binding.set``). When the AR-4 mount lands, this
  refusal — not a silent no-op — is the seam that gets revisited;
* ``verify`` compares the observed binding state to the desired one.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_harness_api import (
    AdapterRefusal, Assessment, ConfigurationAdapterDescriptor, ErrorCode,
    IntentSet as HarnessIntentSet, Match, Mismatch, ValueSchema,
    VerificationUnknown, VersionRange,
)

from . import common, facet

#: This package's adapter version, as the descriptor's ``adapter_versions``
#: single point (installed dist is 1.0.0a1).
ADAPTER_VERSION = (1, 0, 0)

#: The document-level assessment window (runtime-preferences form, same
#: rationale): not a support claim — the window this evidence round assessed.

#: The capability fact key the (future) injection mount would set on the
#: adapter context. Absent on this baseline — hence the honest ``unsupported``.
MOUNT_CAPABILITY = "instruction_slot_facet"

_IMPL_ADAPTER_IDS = {brand: f"{common.FACET_ID}.{brand}" for brand in common.BRANDS}


def payload_schema() -> ValueSchema:
    """The ``memory.binding.v1`` payload: one ``memory`` item object with the
    four closed keys (the AR-5 mirrored three plus ``boundBrands``)."""
    return ValueSchema("object", properties=(
        ("memory", ValueSchema("object", properties=(
            ("enabled", ValueSchema("boolean")),
            ("budgetTokens", ValueSchema("integer", nullable=True)),
            ("extractionModelRef", ValueSchema("string", nullable=True)),
            ("boundBrands", ValueSchema("array", nullable=True,
                                        items=ValueSchema("string"))),
        ), required=("enabled", "budgetTokens", "extractionModelRef", "boundBrands"))),
    ), required=("memory",))


def descriptor_for(brand: str) -> ConfigurationAdapterDescriptor:
    """The real C2 ``ConfigurationAdapterDescriptor`` for one brand."""
    if brand not in common.BRANDS:
        raise ValueError(f"unknown brand {brand!r}")
    return ConfigurationAdapterDescriptor(
        _IMPL_ADAPTER_IDS[brand], "v1", common.FACET_ID, common.FACET_SCHEMA_VERSION,
        brand, VersionRange((0, 1, 0), (2, 0, 0)), VersionRange(ADAPTER_VERSION),
        (common.ENTRY,), payload_schema(), (),
    )


def _binding_of(payload: Mapping[str, Any]) -> dict[str, Any]:
    item = payload.get("memory")
    if not isinstance(item, Mapping):
        raise facet.FacetValueError("invalid-binding", "payload carries no memory item")
    return facet.validate_binding(item)


def _mount_present(context: Any) -> bool:
    capabilities = getattr(context, "capabilities", None)
    if not isinstance(capabilities, Mapping):
        return False
    return capabilities.get(MOUNT_CAPABILITY) == common.INSTRUCTION_FACET_NAME


class BridgeMemoryAdapter:
    """One brand as a real C2 ``ConfigurationAdapter`` (assess/compile/verify)."""

    def __init__(self, brand: str) -> None:
        if brand not in common.BRANDS:
            raise ValueError(f"unknown brand {brand!r}")
        self.brand = brand
        self.descriptor = descriptor_for(brand)

    # -- C2 surface -----------------------------------------------------------

    def assess(self, context: Any, request: Mapping[str, Any]) -> Assessment:
        if not isinstance(request, Mapping) or "memory" not in request:
            # C4 inspect probes with an empty request; a probe carries no
            # binding facts, so the honest verdict is unknown, never supported.
            return Assessment("unknown", reason="probe request carries no memory binding")
        try:
            binding = _binding_of(request)
        except facet.FacetValueError as exc:
            return Assessment("unsupported", reason=exc.message)
        if not _mount_present(context):
            return Assessment(
                "unsupported",
                reason="memory injection mount absent on this baseline (AR-4 instruction-slot "
                       "facet merge pending); the binding is reported, never silently applied")
        if self.brand not in binding["boundBrands"]:
            return Assessment(
                "unsupported", reason=f"brand {self.brand} is not in the binding's boundBrands")
        if self.brand in common.NATIVE_MEMORY_BRANDS:
            return Assessment(
                "supported",
                reason="与原生记忆并存可能重复（可配置挂载）",
                evidence_ref=f"assets.memory:{self.brand}:spec-matrix")
        return Assessment("supported", evidence_ref=f"assets.memory:{self.brand}:spec-matrix")

    def compile(self, context: Any, before: Mapping[str, Any], desired: Mapping[str, Any]
                ) -> HarnessIntentSet | AdapterRefusal:
        try:
            _binding_of(desired)
        except facet.FacetValueError as exc:
            return AdapterRefusal(ErrorCode.INVALID_FRAGMENT, exc.message)
        # Honest refusal: memory has no harness-writable target on this
        # baseline; the validated binding is consumed in-domain through the
        # plugin's own binding store. Red line 5: report, never fake.
        return AdapterRefusal(
            ErrorCode.CAPABILITY_UNSUPPORTED,
            "memory binding has no harness-writable target on this baseline: injection rides "
            "the instruction-slot facet merge (AR-4, EXT pending); apply the binding in-domain "
            "via memory.binding.set")

    def verify(self, context: Any, observed: Mapping[str, Any]) -> Match | Mismatch | VerificationUnknown:
        desired = observed.get("desired")
        if not isinstance(desired, Mapping):
            return VerificationUnknown("no desired binding to compare against")
        projected = observed.get("projected")
        if not isinstance(projected, Mapping):
            return VerificationUnknown("no projected binding sample")
        try:
            want = _binding_of(desired)
            got = _binding_of(projected)
        except facet.FacetValueError as exc:
            return Mismatch(exc.message)
        if want == got:
            return Match("memory:binding:projected-match")
        return Mismatch("projected binding differs from the desired one")
