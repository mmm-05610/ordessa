"""The ``assets.memory`` Profile facet: one atomic item (the memory binding)
with documented defaults and whole-item override semantics.

Form mirrors the sibling ``assets.runtime-preferences`` facet (same batch,
same profile-v2 target contract — ``docs/design/profile-v2/contracts.md``):
the registration payload below is what the Profile side's
``ProfileContributions.forScope(scope).addEditor(...)`` call consumes; the
actual registration is the Profile side's move (profile-api v2 is not on
this package's baseline). This module owns the facet's typed definition:

* one atomic item — a profile carries the binding whole or not at all;
* the three shared keys (``enabled``/``budgetTokens``/``extractionModelRef``)
  mirror the P-A memory item exactly (AR-5 facet contract; key names pinned
  on both sides by tests), plus this facet's own ``boundBrands``;
* values bind nothing secret: the extraction model reference is a reference
  string; a provisioning request or a credential is structurally absent;
* unknown keys are refusals, never silent passthrough.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import common


class FacetValueError(Exception):
    """A typed refusal of a malformed or non-atomic facet value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def facet_descriptor() -> dict[str, Any]:
    """The facet's typed definition (one item, atomic)."""
    return {
        "facetId": common.FACET_ID,
        "apiMajor": 1,
        "schemaVersion": int(common.FACET_SCHEMA_VERSION),
        "items": [{
            "id": "memory",
            "title": "记忆绑定（mem0 自托管）",
            "valueType": "atomic",
            "valueKeys": list(common.VALUE_KEYS),
            "default": common.default_binding(),
            "sensitive": False,
            "note": common.ATTRIBUTION,
        }],
    }


def facet_registration_manifest() -> dict[str, Any]:
    """The registration payload the Profile side's facet API consumes."""
    return facet_descriptor()


def editor_registration_manifest() -> dict[str, Any]:
    """The ``ProfileEditorContribution``-shaped declaration for
    ``ProfileContributions.forScope(scope).addEditor(...)``: one editor for
    the memory binding; the settings page and memory viewer carry the
    attribution (spec red line 4) via the ``note`` field."""
    descriptor = facet_descriptor()
    return {
        "facetId": descriptor["facetId"],
        "supportedSchemaRange": f"1.{descriptor['schemaVersion']}",
        "componentKey": "memory.binding-editor.v1",
        "category": "capabilities",
        "order": 40,
        "items": descriptor["items"],
        "attribution": common.ATTRIBUTION,
    }


def validate_binding(value: Any) -> dict[str, Any]:
    """Validate one binding value against the facet schema; returns the
    normalized value. Unknown keys, wrong types and out-of-vocabulary brands
    are typed refusals — never silent passthrough."""
    if not isinstance(value, Mapping):
        raise FacetValueError("invalid-binding", "the binding must be an object")
    unknown = sorted(set(value) - set(common.VALUE_KEYS))
    if unknown:
        raise FacetValueError(
            "unknown-key", f"unknown binding keys: {', '.join(unknown)}")
    missing = [key for key in common.VALUE_KEYS if key not in value]
    if missing:
        raise FacetValueError(
            "incomplete-binding", f"missing binding keys: {', '.join(missing)}")
    normalized = dict(value)
    if not isinstance(normalized["enabled"], bool):
        raise FacetValueError("invalid-binding", "enabled must be a boolean")
    budget = normalized["budgetTokens"]
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int)
                               or budget < 1 or budget > 100_000):
        raise FacetValueError(
            "invalid-binding", "budgetTokens must be a positive integer (≤ 100000) or null")
    ref = normalized["extractionModelRef"]
    if ref is not None and (not isinstance(ref, str) or not ref.strip()):
        raise FacetValueError(
            "invalid-binding", "extractionModelRef must be a non-empty reference string or null")
    brands = normalized["boundBrands"]
    if (not isinstance(brands, list) or not brands
            or any(not isinstance(b, str) or b not in common.BRANDS for b in brands)):
        raise FacetValueError(
            "invalid-binding",
            "boundBrands must be a non-empty list drawn from: " + ", ".join(common.BRANDS))
    normalized["boundBrands"] = list(dict.fromkeys(brands))
    return normalized
