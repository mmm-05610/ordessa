"""T01 red/green: brand-native mode names stay per-brand (FR-03)."""
from __future__ import annotations

import pytest

from ordessa_permissions_api import (
    BRAND_NATIVE_MODES,
    BrandMode,
    PolicyRefusal,
    RuleAction,
    declared_native_modes,
)


def test_declared_brands_keep_their_own_mode_vocabulary() -> None:
    assert set(BRAND_NATIVE_MODES) >= {"claude-code", "codex", "pi"}
    assert "bypassPermissions" in declared_native_modes("claude-code")
    assert "untrusted" in declared_native_modes("codex")


def test_pi_has_no_declared_native_permission_mode_and_is_never_given_one() -> None:
    # An absent vocabulary is `unsupported`, not an empty-but-working mode set.
    assert declared_native_modes("pi") == ()
    with pytest.raises(PolicyRefusal) as exc:
        BrandMode.declare("pi", "yolo")
    assert exc.value.code == "PERMISSION_MODE_UNSUPPORTED"


def test_an_undeclared_brand_is_refused_rather_than_guessed() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        BrandMode.declare("hermes", "default")
    assert exc.value.code == "PERMISSION_BRAND_UNSUPPORTED"


def test_mode_identity_carries_its_brand_so_no_two_brands_can_share_one() -> None:
    claude_plan = BrandMode.declare("claude-code", "plan")
    assert (claude_plan.brand, claude_plan.name) == ("claude-code", "plan")
    assert str(claude_plan) == "claude-code:plan"
    assert claude_plan != BrandMode.declare("claude-code", "auto")
    # The same spelling in another brand is not even constructible: FR-03 cannot
    # be violated by accident because the vocabulary is per brand and disjoint.
    with pytest.raises(PolicyRefusal) as exc:
        BrandMode.declare("codex", "plan")
    assert exc.value.code == "PERMISSION_MODE_UNSUPPORTED"


def test_declared_vocabularies_are_disjoint_across_brands() -> None:
    names = {brand: set(modes) for brand, modes in BRAND_NATIVE_MODES.items()}
    assert not names["claude-code"] & names["codex"]
    assert not names["claude-code"] & names["pi"]
    assert not names["codex"] & names["pi"]


def test_a_mode_is_validated_against_its_own_brand_only() -> None:
    BrandMode.declare("claude-code", "bypassPermissions")
    with pytest.raises(PolicyRefusal) as exc:
        BrandMode.declare("codex", "bypassPermissions")
    assert exc.value.code == "PERMISSION_MODE_UNSUPPORTED"


def test_brand_modes_are_never_interpretation_results() -> None:
    mode = BrandMode.declare("claude-code", "auto")
    assert not isinstance(mode, RuleAction)
    assert not any(getattr(mode, name, None) is RuleAction.ALLOW
                   for name in dir(mode) if not name.startswith("_"))
    brand_names = {m for modes in BRAND_NATIVE_MODES.values() for m in modes}
    assert {action.value for action in RuleAction}.isdisjoint(brand_names | {"yolo"})


def test_a_mode_is_an_immutable_value_and_rejects_an_undeclared_name() -> None:
    with pytest.raises(PolicyRefusal):
        BrandMode.declare("claude-code", "")
    with pytest.raises(PolicyRefusal):
        BrandMode(brand="claude-code", name="not-declared")  # bypasses declare()
