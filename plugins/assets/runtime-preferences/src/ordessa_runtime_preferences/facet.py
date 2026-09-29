"""The ``assets.runtime-preferences`` Profile facet (RA-5): four atomic items
(compaction / memory / shell / retry) with documented defaults and whole-item
override semantics.

Authored against the profile-v2 target contract
(``docs/design/profile-v2/contracts.md``): the facet is registered with the
Profile side through its public contribution API — the actual
``ProfileContributions.forScope(scope).addEditor(...)`` call is the Profile
side's move (the profile-api v2 surface is not on this package's baseline;
the registration payload below is what that call consumes). What this module
owns is the facet's own typed definition and the whole-item discipline:

* four atomic items — a profile carries each item whole or not at all; there
  is no per-key merge across profiles (two profiles cannot each contribute
  half of a compaction policy);
* the value binds nothing secret: model/backend references are reference
  strings; the memory item is pure typed parameters (switch / budget /
  extraction-model reference) — a memory-service provisioning request is
  structurally impossible (AR-5 contract, consumed by P-B as facets only);
* unknown keys and unknown groups are refusals, never silent passthrough;
* admin-only native keys (RA-4) are not item values at all — they appear in
  the editor declaration as disabled entries with their recorded reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from . import keys

FACET_ID = "assets.runtime-preferences"
API_MAJOR = 1
SCHEMA_VERSION = 1

ITEM_IDS = keys.GROUPS
MEMORY_ITEM_ID = "memory"


@dataclass(frozen=True)
class FacetItem:
    item_id: str
    title: str
    value_type: str  # 'atomic' — whole-item override only (no per-key merge)
    value_keys: tuple[str, ...]
    default: dict[str, Any]
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


def _empty_default(group: str) -> dict[str, Any]:
    """The item default: the empty parameter object = follow the harness's
    native defaults. Presence of the item with empty params is distinct from
    absence only in editor display; neither compiles anything."""
    return {}


def facet_descriptor() -> FacetDescriptor:
    titles = {"compaction": "压缩/上下文策略", "memory": "记忆策略（纯参数）",
              "shell": "shell/执行环境", "retry": "重试/传输"}
    return FacetDescriptor(
        facet_id=FACET_ID, api_major=API_MAJOR, schema_version=SCHEMA_VERSION,
        items=tuple(
            FacetItem(
                item_id=group,
                title=titles[group],
                value_type="atomic",
                value_keys=keys.CANONICAL_PARAMS[group],
                default=_empty_default(group),
            )
            for group in keys.GROUPS
        )
    )


def facet_registration_manifest() -> dict[str, Any]:
    """The registration payload the Profile side's facet API consumes. The
    registration itself is the Profile side's move (profile-api v2 is not on
    this baseline); this package never invents a registry of its own."""
    descriptor = facet_descriptor()
    return {
        "facetId": descriptor.facet_id,
        "apiMajor": descriptor.api_major,
        "schemaVersion": descriptor.schema_version,
        "items": [
            {
                "id": item.item_id, "title": item.title,
                "valueType": item.value_type, "valueKeys": list(item.value_keys),
                "default": dict(item.default), "sensitive": item.sensitive,
            }
            for item in descriptor.items
        ],
    }


def editor_registration_manifest() -> dict[str, Any]:
    """The ``ProfileEditorContribution``-shaped declaration for
    ``ProfileContributions.forScope(scope).addEditor(...)`` (profile-v2
    contract §2): one editor for the facet, generic schema editors cover the
    four items. ``disabledItems`` carries the RA-4 admin-only entries per
    brand so the editor can render them disabled with their reason — the
    enforcement is server-side regardless."""
    descriptor = facet_descriptor()
    disabled: dict[str, list[dict[str, Any]]] = {}
    for brand in keys.BRANDS:
        for group in keys.GROUPS:
            for key in keys.admin_only_keys(brand, group):
                disabled.setdefault(group, []).append({
                    "brand": brand,
                    "nativeKey": ".".join(part for part in key.path) or "(env/config entries)",
                    "reason": key.note or key.evidence,
                })
    return {
        "kind": "profile-editor",
        "facetId": FACET_ID,
        "supportedSchemaRange": f"1.x (apiMajor {API_MAJOR})",
        "componentKey": "ordessa.runtime-preferences/preferences-editor",
        "category": "behavior",
        "order": 40,
        "items": [item.item_id for item in descriptor.items],
        "disabledItems": disabled,
    }


_PARAM_TYPES: dict[str, tuple[type, ...]] = {
    "enabled": (bool,), "persistent": (bool,),
    "mode": (str,), "summaryModelRef": (str,), "extractionModelRef": (str,),
    "shellPath": (str,), "commandPrefix": (str,), "backend": (str,),
    "transport": (str,), "proxyRef": (str,),
    "thresholdPercent": (int,), "thresholdTokens": (int,), "reserveTokens": (int,),
    "keepRecentTokens": (int,), "budgetTokens": (int,), "timeoutMs": (int,),
    "maxRetries": (int,), "baseDelayMs": (int,), "maxDelayMs": (int,),
    "streamIdleTimeoutMs": (int,),
}


def validate_item_value(group: str, value: Any) -> None:
    """One atomic item value: exactly canonical keys, faithfully typed,
    references as strings, ``envRefs`` as reference mappings. Absent item /
    empty object are the documented default (native defaults follow)."""
    if group not in keys.CANONICAL_PARAMS:
        raise FacetValueError("PROFILE_FACET_ITEM_UNKNOWN",
                              f"unknown facet item {group!r}; this facet owns "
                              f"{sorted(keys.CANONICAL_PARAMS)}")
    if not isinstance(value, Mapping):
        raise FacetValueError("PROFILE_FACET_VALUE_INVALID",
                              f"{group} value must be an object")
    vocabulary = keys.CANONICAL_PARAMS[group]
    unknown = sorted(set(value) - set(vocabulary))
    if unknown:
        raise FacetValueError(
            "PROFILE_FACET_VALUE_INVALID",
            f"{group} carries unknown key(s) {unknown}; the v1 vocabulary is "
            f"{list(vocabulary)}")
    for name, item in value.items():
        if name == "envRefs":
            if not isinstance(item, Mapping) or not all(
                    isinstance(k, str) and isinstance(v, str) and v.startswith("ref://")
                    for k, v in item.items()):
                raise FacetValueError(
                    "PROFILE_FACET_VALUE_INVALID",
                    "shell.envRefs must map names to ref:// references")
            continue
        expected = _PARAM_TYPES[name]
        if not isinstance(item, expected) or isinstance(item, bool) != (bool in expected):
            raise FacetValueError(
                "PROFILE_FACET_VALUE_INVALID",
                f"{group}.{name} has the wrong value type")
        if name in ("summaryModelRef", "extractionModelRef", "proxyRef"):
            if not isinstance(item, str) or not item.strip():
                raise FacetValueError(
                    "PROFILE_FACET_VALUE_INVALID",
                    f"{group}.{name} must be a non-empty model/backend reference")
        if isinstance(item, int) and not isinstance(item, bool) and item < 0:
            raise FacetValueError(
                "PROFILE_FACET_VALUE_INVALID",
                f"{group}.{name} must be non-negative")
        if name == "thresholdPercent" and not 1 <= item <= 99:
            raise FacetValueError("PROFILE_FACET_VALUE_INVALID",
                                  "compaction.thresholdPercent must be 1-99")


def validate_items(items: Mapping[str, Any]) -> tuple[FacetValueError, ...]:
    """Whole-item validation of a stored facet value set; returns all
    violations (the profile side renders them; apply refuses independently)."""
    violations = []
    descriptor = facet_descriptor()
    known = {item.item_id for item in descriptor.items}
    for item_id, value in items.items():
        if item_id not in known:
            violations.append(FacetValueError(
                "PROFILE_FACET_ITEM_UNKNOWN",
                f"unknown facet item {item_id!r}; this facet owns {sorted(known)}"))
            continue
        try:
            validate_item_value(item_id, value)
        except FacetValueError as error:
            violations.append(error)
    return tuple(violations)


def memory_facet_contract() -> dict[str, Any]:
    """The AR-5 contract surface: the exact keys and semantics P-B consumes
    from this facet (as a contract, never as an import). P-B renders its own
    settings from these keys and falls back to its own defaults when P-A is
    absent — the failure mode the api-requests ledger pins."""
    return {
        "facetId": FACET_ID,
        "itemId": MEMORY_ITEM_ID,
        "keys": {
            "enabled": "boolean — 记忆功能开关（纯参数；不含任何服务置备语义）",
            "budgetTokens": "integer|null — token 预算上限",
            "extractionModelRef": "string|null — 抽取模型引用（provider/model 引用，非凭据）",
        },
        "semantics": "开关/预算/抽取模型引用；缺省=跟随品牌原生默认；整项覆盖。",
        "provisioning": "结构上不存在：本 facet 无端点/凭据/服务生命周期键（P-B 的置备归 assets.memory facet）。",
    }
