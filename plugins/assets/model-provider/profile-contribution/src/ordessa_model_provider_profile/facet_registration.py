"""Z3 T04 increments: the ``assets.model-provider`` Profile facet descriptor.

Authored in this line against the profile-v2 target contract
(``docs/design/profile-v2/contracts.md``): the facet is registered with the
Profile side (Z1) through its public contribution API — the actual
``ProfileContributions.forScope(scope).addEditor(...)`` call is REQ-Z3-3 and
stays OPEN; what this module owns is the facet's own typed definition and the
atomic-value discipline (MP-01/US-3):

* exactly ONE atomic item ``choice`` — provider and model are never split into
  two inheritable items;
* the value binds the profile's harness; a value for another harness refuses;
* sensitive material is not a facet value (secret lives behind a reference).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

FACET_ID = "assets.model-provider"
API_MAJOR = 1
SCHEMA_VERSION = 1

#: The single atomic item; its value shape is the frozen ModelChoice triple.
CHOICE_ITEM_ID = "choice"
CHOICE_VALUE_KEYS = ("harnessId", "providerConfigId", "modelId")


@dataclass(frozen=True)
class FacetItem:
    item_id: str
    title: str
    value_type: str  # 'atomic' — provider+model never split (MP-01)
    value_keys: tuple[str, ...]
    sensitive: bool = False


@dataclass(frozen=True)
class FacetDescriptor:
    facet_id: str
    api_major: int
    schema_version: int
    items: tuple[FacetItem, ...]


class FacetValueError(Exception):
    """A typed refusal of a malformed or non-atomic facet value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def facet_descriptor() -> FacetDescriptor:
    return FacetDescriptor(
        facet_id=FACET_ID, api_major=API_MAJOR, schema_version=SCHEMA_VERSION,
        items=(FacetItem(
            item_id=CHOICE_ITEM_ID, title="默认模型",
            value_type="atomic", value_keys=CHOICE_VALUE_KEYS,
        ),),
    )


def facet_registration_manifest() -> dict[str, Any]:
    """The registration payload the Z1 contribution API will consume. The
    registration itself is the Profile side's move (REQ-Z3-3, OPEN); this
    package never invents a registry of its own."""
    descriptor = facet_descriptor()
    return {
        "facetId": descriptor.facet_id,
        "apiMajor": descriptor.api_major,
        "schemaVersion": descriptor.schema_version,
        "items": [
            {
                "id": item.item_id, "title": item.title,
                "valueType": item.value_type, "valueKeys": list(item.value_keys),
                "sensitive": item.sensitive,
            }
            for item in descriptor.items
        ],
    }


def validate_choice_value(value: Mapping[str, Any], *, harness_id: str) -> None:
    """One atomic ModelChoice, bound to this profile's harness; nothing else.

    Refusals: a value that does not carry exactly the frozen key set, a
    secret-shaped key, a provider/model split into separate items (they would
    inherit independently, MP-01), or a harness mismatch (a profile belongs to
    one harness; its choices follow it)."""
    if not isinstance(value, Mapping):
        raise FacetValueError("PROFILE_FACET_VALUE_INVALID", "choice value must be an object")
    keys = set(value)
    if keys != set(CHOICE_VALUE_KEYS):
        raise FacetValueError(
            "PROFILE_FACET_VALUE_INVALID",
            "the choice item is atomic: it carries exactly "
            f"{CHOICE_VALUE_KEYS} (got {sorted(keys)})")
    for key in CHOICE_VALUE_KEYS:
        if not isinstance(value[key], str) or not value[key]:
            raise FacetValueError(
                "PROFILE_FACET_VALUE_INVALID", f"{key} must be a non-empty string")
    if value["harnessId"] != harness_id:
        raise FacetValueError(
            "PROFILE_HARNESS_MISMATCH",
            f"choice binds harness {value['harnessId']!r}, "
            f"but this profile belongs to {harness_id!r}")
