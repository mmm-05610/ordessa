"""T03 red/green: cross-brand non-equivalence (FR-03).

`allow/ask/deny` (Ordessa's interpretation layer, `RuleAction`) is the ONLY
shared vocabulary. Brand mode names are names, not capabilities:
`yolo`/`auto`/`plan`/`bypassPermissions` belong to claude-code,
`untrusted`/`on-request`/`on-failure`/`never` to codex, and pi declares no
native mode set at all (`BRAND_NATIVE_MODES["pi"] == ()`). Nothing may map
one brand's spelling onto another's, and no adapter output may carry another
brand's mode name.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import BRAND_NATIVE_MODES, BrandMode, PolicyRefusal

from _permissions_adapters_helpers import make_intent
from ordessa_permissions_adapters import (
    ClaudeAdapter,
    CodexAdapter,
    CompiledIntentSet,
    CompileRefusal,
    PiAdapter,
    PolicyCompileSnapshot,
    SupportEvidence,
    SupportOutcome,
)

ALL_MODE_NAMES = {brand: set(modes) for brand, modes in BRAND_NATIVE_MODES.items()}

ADAPTERS = {
    "claude-code": (ClaudeAdapter, "0.81.2"),
    "codex": (CodexAdapter, "2.0"),
    "pi": (PiAdapter, "2.0"),
}


def test_mode_vocabularies_are_pairwise_disjoint() -> None:
    brands = list(BRAND_NATIVE_MODES)
    for i, a in enumerate(brands):
        for b in brands[i + 1:]:
            shared = ALL_MODE_NAMES[a] & ALL_MODE_NAMES[b]
            assert not shared, f"{a} and {b} share mode names {shared}"


def test_yolo_is_nobody_s_name() -> None:
    # The word exists in product folklore, not in any pinned vocabulary;
    # constructing it as a mode must fail for every brand.
    for brand in BRAND_NATIVE_MODES:
        with pytest.raises(PolicyRefusal):
            BrandMode.declare(brand, "yolo")


def test_a_mode_name_is_rejected_on_the_wrong_brand() -> None:
    # `untrusted` is codex's word; declaring it for claude-code or pi refuses
    # at the API boundary, so no adapter can even be asked to translate it.
    for wrong_brand in ("claude-code", "pi"):
        with pytest.raises(PolicyRefusal):
            BrandMode.declare(wrong_brand, "untrusted")
    with pytest.raises(PolicyRefusal):
        BrandMode.declare("pi", "bypassPermissions")


def test_no_adapter_compiles_for_another_brand() -> None:
    for harness, (cls, version) in ADAPTERS.items():
        adapter = cls()
        other = next(h for h in ADAPTERS if h != harness)
        result = adapter.compilePolicy(PolicyCompileSnapshot.of(
            harness_id=other, native_version=ADAPTERS[other][1],
            intent=make_intent(other)))
        assert isinstance(result, CompileRefusal)
        assert adapter.supports(SupportEvidence.of(harness_id=other,
                                                   native_version=version)).outcome \
            is SupportOutcome.UNSUPPORTED


def test_successful_outputs_never_carry_another_brand_s_mode_name() -> None:
    # Every successfully compiled field value, across a small sweep, is free
    # of other brands' vocabulary: a shared result is only ever the Ordessa
    # allow/ask/deny layer, never a brand name smuggled across.
    cases = {
        "claude-code": [None, make_intent("claude-code", [
            {"key": "external_directory", "action": "allow"},
            {"key": "bash", "action": "deny"}])],
        "codex": [None, make_intent("codex", [{"key": "edit", "action": "deny"}])],
    }
    foreign = {
        "claude-code": ALL_MODE_NAMES["codex"],
        "codex": ALL_MODE_NAMES["claude-code"] | {"yolo"},
        "pi": ALL_MODE_NAMES["claude-code"] | ALL_MODE_NAMES["codex"],
    }
    for harness, intents in cases.items():
        cls, version = ADAPTERS[harness]
        adapter = cls()
        for intent in intents:
            result = adapter.compilePolicy(PolicyCompileSnapshot.of(
                harness_id=harness, native_version=version, intent=intent))
            if isinstance(result, CompiledIntentSet):
                values = {v for field in result.as_record().values()
                          for v in (field if isinstance(field, (list, tuple)) else [field])}
                assert not (values & foreign[harness]), (harness, values)
            else:
                assert isinstance(result, CompileRefusal)


def test_rule_actions_are_the_only_common_vocabulary() -> None:
    from ordessa_permissions_api import RuleAction
    assert {action.value for action in RuleAction} == {"allow", "ask", "deny"}
    # and no brand mode name collides with the interpretation layer: a brand
    # name that happened to be spelled like an action would be caught here.
    union = set().union(*ALL_MODE_NAMES.values())
    assert not (union & {"allow", "ask", "deny"})
