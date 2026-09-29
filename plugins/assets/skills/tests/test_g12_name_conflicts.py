"""G12 — name collisions refuse assembly; no winner by order/case/last-write.

data-model.md §原生发现项与命名冲突: different assetIds colliding on
nativeName → refuse; comparisons follow the brand's REAL name rules, and
where those rules are `unknown` (all three brands today) evaluation is the
conservative superset (exact ∪ casefold ∪ NFC ∪ NFD ∪ NFK*), which
over-refuses on purpose. Collisions with native-discovered items may only
be resolved by a brand-VERIFIED native namespacing — the Claude plugin
namespace is vendor-doc, i.e. `unknown`, so it cannot save a collision.
"""
from __future__ import annotations

import pytest

from ordessa_skills.harness_adapters import claude, codex, pi
from ordessa_skills.harness_adapters.capabilities import statement_for
from ordessa_skills.harness_adapters.conflict import (
    CASE_SENSITIVE, COLLISION_CODE, NameConflictError,
    evaluate_against_native_discovery, evaluate_managed_set, name_rules_for,
    NativeNameRules,
)
from ordessa_skills.harness_adapters.intent import ManagedContentRef

DIGEST = "sha256:" + "a" * 64
NAMESPACING_AXIS = "native_namespacing"


def _ref(asset_id: str, name: str) -> ManagedContentRef:
    return ManagedContentRef(asset_id=asset_id, revision=1,
                             tree_digest=DIGEST, native_name=name)


def _rules_strictly_case_sensitive() -> NativeNameRules:
    return NativeNameRules(
        harness_id="pi", case_sensitivity=CASE_SENSITIVE,
        unicode_normalization="none",
        evidence="specs/011-q1-skills/research/brand-matrix.md:40")


# -- managed vs managed --------------------------------------------------------

def test_different_assets_with_the_same_native_name_refuse():
    refs = [_ref("alpha-skill", "shared"), _ref("beta-skill", "shared")]
    with pytest.raises(NameConflictError) as exc:
        evaluate_managed_set(refs, name_rules_for("pi"))
    assert exc.value.code == COLLISION_CODE
    # No winner is returned — the ONLY outcomes are "raise" or "None".
    assert exc.value.detail is not None


def test_refusal_is_not_last_one_wins():
    # A third distinct name must not turn the collision into a "winner".
    refs = [_ref("a-skill", "dup"), _ref("b-skill", "dup"), _ref("c-skill", "solo")]
    for ordering in (refs, list(reversed(refs))):
        with pytest.raises(NameConflictError):
            evaluate_managed_set(ordering, name_rules_for("pi"))


def test_same_asset_twice_refuses_without_choosing_a_revision():
    refs = [ManagedContentRef("one-skill", 1, DIGEST, "one-skill"),
            ManagedContentRef("one-skill", 2, DIGEST, "one-skill")]
    with pytest.raises(NameConflictError) as exc:
        evaluate_managed_set(refs, name_rules_for("pi"))
    assert exc.value.code == COLLISION_CODE


def test_compile_refuses_a_colliding_collection_before_any_intent():
    from ordessa_skills.harness_adapters.base import AdapterTarget
    from ordessa_skills.harness_adapters.intent import GenerationBounds
    bounds = GenerationBounds("gen-1", "proj-1", 0, 0)
    with pytest.raises(NameConflictError):
        pi.compile([_ref("a-skill", "clash"), _ref("b-skill", "clash")],
                   AdapterTarget("pi", "0.84.2", "0.5.0", "acp"), bounds=bounds)


# -- native rules drive the comparison -----------------------------------------

def test_unknown_rules_take_the_conservative_case_path():
    rules = name_rules_for("pi")
    assert rules.case_sensitivity == "unknown"
    # native-discovered "Demo" vs managed "demo" — under UNKNOWN rules this
    # must refuse (the native side may be case-insensitive).
    with pytest.raises(NameConflictError):
        evaluate_against_native_discovery(
            [_ref("a-skill", "demo")], ["Demo"], rules, "unknown")


def test_evidenced_case_sensitive_rules_allow_names_unknown_rules_would_block():
    # Proves the decision is DRIVEN by the rule object, not hardcoded: with
    # a (hypothetical, evidence-cited) case-sensitive rule, "Demo" and
    # "demo" are different names.
    strict = _rules_strictly_case_sensitive()
    evaluate_against_native_discovery(
        [_ref("a-skill", "demo")], ["Demo"], strict, "unknown")  # no raise


def test_unicode_variants_refuse_under_unknown_rules():
    rules = name_rules_for("codex")
    # Fullwidth uppercase ＤＥＭＯ folds to "demo" under NFKC+casefold.
    with pytest.raises(NameConflictError):
        evaluate_against_native_discovery(
            [_ref("a-skill", "demo")], ["ＤＥＭＯ"], rules, "unknown")
    # Fullwidth lowercase ｄｅｍｏ equals "demo" once NFKC-normalized.
    with pytest.raises(NameConflictError):
        evaluate_against_native_discovery(
            [_ref("b-skill", "demo")], ["ｄｅｍｏ"], rules, "unknown")


def test_rules_default_to_unknown_for_any_brand():
    for harness_id in ("pi", "codex", "claude-code", "brand-new"):
        rules = name_rules_for(harness_id)
        assert rules.case_sensitivity == "unknown"
        assert rules.unicode_normalization == "unknown"


# -- managed vs native-discovered ----------------------------------------------

@pytest.mark.parametrize("module,harness_id", [
    (pi, "pi"), (codex, "codex"), (claude, "claude-code")])
def test_no_controlled_brand_may_use_namespacing_to_escape_a_collision(module, harness_id):
    statement = statement_for(harness_id)
    assert statement.value(NAMESPACING_AXIS) == "unknown"
    with pytest.raises(NameConflictError):
        module.refuse_native_collisions([_ref("a-skill", "alpha")], ["alpha"])


def test_claude_plugin_namespace_is_vendor_doc_and_therefore_refused():
    # harness-adapters.md:12 documents plugin namespacing for Claude; the
    # registry keeps it `unknown` and conflict evaluation refuses — a
    # documented-but-unobserved mechanism cannot license a name clash.
    with pytest.raises(NameConflictError):
        claude.refuse_native_collisions([_ref("a-skill", "pdf-tools")],
                                        ["pdf-tools"])


def test_clean_collections_pass():
    evaluate_managed_set([_ref("a-skill", "alpha"), _ref("b-skill", "beta")],
                         name_rules_for("claude-code"))
    evaluate_against_native_discovery(
        [_ref("a-skill", "alpha")], ["other-native"], name_rules_for("claude-code"),
        "unknown")
