"""Name-collision evaluation before assembly (FR10, FR11, G12).

Authoritative rules:

* data-model.md §原生发现项与命名冲突: 不同 assetId 的重名 → 拒绝装配,
  "不以大小写、目录顺序或'最后覆盖'私自选胜者"; collisions with observed
  native-discovery items → refuse unless a brand-verified native
  namespacing exists.
* harness-adapters.md: the Claude plugin namespace is a vendor-doc fact
  ("插件 Skill 可带命名空间") — no in-repo observation — so per
  capabilities.py semantics it is `unknown`, and unknown namespacing may
  not be relied on: refuse.

Comparison semantics are driven by the per-brand `NativeNameRules` object.
Where the repo has no evidence for a brand's case or Unicode behaviour the
rule value is ``unknown`` and evaluation goes *conservative-superset*: a
collision is declared if the names agree under ANY of exact, casefold, NFC
or NFD comparison, because an unknown native rule could pick either. This
over-refuses on purpose (G12 counter-example: "Unicode/大小写规则与原生
不符"); it gets relaxed only when a rule cell gains in-repo evidence.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from .capabilities import NO_EVIDENCE, SUPPORTED, UNKNOWN
from .intent import ManagedContentRef
from ..api.errors import AssetDomainError

#: Refusal code — stable identifier for wire/diagnostics (errors.py policy).
COLLISION_CODE = "SKILL_NAME_COLLISION"

CASE_SENSITIVE = "case_sensitive"
CASE_INSENSITIVE = "case_insensitive"

#: Comparison-rule axes. Value domain per axis:
#: case_sensitivity: CASE_SENSITIVE | CASE_INSENSITIVE | UNKNOWN
#: unicode_normalization: "nfc" | "nfd" | "none" | UNKNOWN
NAME_RULE_AXES = ("case_sensitivity", "unicode_normalization")


class NameConflictError(AssetDomainError):
    """Assembly refused because names would not resolve uniquely."""


@dataclass(frozen=True)
class NativeNameRules:
    harness_id: str
    case_sensitivity: str
    unicode_normalization: str
    #: Evidence for the known values; NO_EVIDENCE when everything is unknown.
    evidence: str

    def __post_init__(self) -> None:
        if self.case_sensitivity not in (CASE_SENSITIVE, CASE_INSENSITIVE, UNKNOWN):
            raise ValueError("case_sensitivity must be sensitive/insensitive/unknown")
        if self.unicode_normalization not in ("nfc", "nfd", "none", UNKNOWN):
            raise ValueError("unicode_normalization must be nfc/nfd/none/unknown")
        known = (self.case_sensitivity != UNKNOWN
                 or self.unicode_normalization != UNKNOWN)
        if known and (not isinstance(self.evidence, str) or ":" not in self.evidence):
            raise ValueError("a known name rule must cite repo evidence")


#: The repo has NO first-hand evidence of any brand's native name-comparison
#: behaviour (brand-matrix.md §2 records discovery/loading cells only), so
#: every rule starts `unknown` and the default is the conservative superset.
NAME_RULES: Mapping[str, NativeNameRules] = MappingProxyType({
    brand: NativeNameRules(
        harness_id=brand,
        case_sensitivity=UNKNOWN,
        unicode_normalization=UNKNOWN,
        evidence=NO_EVIDENCE,
    )
    for brand in ("pi", "codex", "claude-code")
})


def name_rules_for(harness_id: str) -> NativeNameRules:
    return NAME_RULES.get(harness_id) or NativeNameRules(
        harness_id=harness_id,
        case_sensitivity=UNKNOWN,
        unicode_normalization=UNKNOWN,
        evidence=NO_EVIDENCE,
    )


def _comparison_keys(name: str, rules: NativeNameRules) -> tuple[str, ...]:
    """The set of keys under which two names must DIFFER to be safe.

    A fully evidenced rule narrows the key set to the brand's actual
    comparison; ANY unknown axis widens it to the union of all plausible
    transforms (conservative-superset — see module docstring).
    """
    if rules.case_sensitivity == UNKNOWN or rules.unicode_normalization == UNKNOWN:
        variants = {name, name.casefold()}
        for form in ("NFC", "NFD", "NFKC", "NFKD"):
            normalized = unicodedata.normalize(form, name)
            variants.add(normalized)
            variants.add(normalized.casefold())
        return tuple(sorted(variants))
    base = name
    if rules.unicode_normalization in ("nfc", "nfd"):
        base = unicodedata.normalize(rules.unicode_normalization.upper(), name)
    if rules.case_sensitivity == CASE_INSENSITIVE:
        return (base.casefold(),)
    return (base,)


def _collide(left: str, right: str, rules: NativeNameRules) -> bool:
    return bool(set(_comparison_keys(left, rules))
                & set(_comparison_keys(right, rules)))


def evaluate_managed_set(refs: Sequence[ManagedContentRef],
                         rules: NativeNameRules) -> None:
    """Refuse assembly when the managed set itself names a nativeName twice.

    * two different assetIds with a colliding nativeName → refuse;
    * the same assetId appearing twice (any revisions) → refuse: one asset
      is one entry in a resolved set (data-model.md).
    There is no winner selection — no directory order, no case trick, no
    "last one wins": this function only returns or raises.
    """
    by_asset: dict[str, list[ManagedContentRef]] = {}
    for ref in refs:
        by_asset.setdefault(ref.asset_id, []).append(ref)
    for asset_id, group in sorted(by_asset.items()):
        if len(group) > 1:
            raise NameConflictError(
                COLLISION_CODE,
                f"assetId {asset_id!r} appears {len(group)} times in one "
                "resolved set; refusing instead of picking a revision",
                detail=f"revisions={[item.revision for item in group]}")
    ordered = sorted(refs, key=lambda item: (item.native_name, item.asset_id))
    for index, left in enumerate(ordered):
        for right in ordered[index + 1:]:
            if left.asset_id == right.asset_id:
                continue
            if _collide(left.native_name, right.native_name, rules):
                raise NameConflictError(
                    COLLISION_CODE,
                    f"nativeName {left.native_name!r} of asset "
                    f"{left.asset_id!r} collides with asset {right.asset_id!r}"
                    " under the brand comparison rules; assembly refused — "
                    "no winner is selected by order, case or last-write",
                    detail=f"brand={rules.harness_id}")


def evaluate_against_native_discovery(
    refs: Sequence[ManagedContentRef],
    native_names: Sequence[str],
    rules: NativeNameRules,
    namespacing_value: str,
) -> None:
    """Refuse when a managed nativeName collides with a native-discovery item.

    `namespacing_value` is the brand's `native_namespacing` capability
    value. Only a brand-verified ``supported`` namespacing (NONE today —
    the Claude plugin namespace is vendor-doc, therefore ``unknown``) may
    turn a collision into a namespaced co-existence; anything else refuses
    (data-model.md: 不能只藏起原生项再记为"受管项已装载").
    """
    if namespacing_value == SUPPORTED:
        # Reserved for a future brand with a VERIFIED native namespace.
        # No such evidence exists in this repo at any pinned version, and
        # the brand modules never pass `supported` (capabilities guard).
        return
    for ref in refs:
        for observed in native_names:
            if _collide(ref.native_name, observed, rules):
                raise NameConflictError(
                    COLLISION_CODE,
                    f"managed asset {ref.asset_id!r} nativeName "
                    f"{ref.native_name!r} collides with native-discovered "
                    f"{observed!r}; no brand-verified native namespacing "
                    "exists, assembly refused",
                    detail=f"brand={rules.harness_id} namespacing={namespacing_value}")
