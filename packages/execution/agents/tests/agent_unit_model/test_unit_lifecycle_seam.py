"""The provider lifecycle mechanism is brand-independent; brands supply identity.

P1b extracted the run/session/termination mechanism out of the pi plugin into
``ordessa_units.lifecycle.unit_lifecycle``. These tests pin the
seam so it cannot silently become pi-shaped again:

- the common base names no brand;
- the brand hooks are unset by default;
- a different brand can drive the same mechanism;
- the pi module supplies identity only and forwards nothing.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from ordessa_units.lifecycle import unit_lifecycle
from ordessa_units.lifecycle.unit_lifecycle import (
    UnitLifecycle,
    UnitLifecycleRefused,
    plain,
    records_ready,
    same_reference,
)

COMMON_BASE = pathlib.Path(unit_lifecycle.__file__)

#: Brand literals that must never appear in the common base.
BRAND_LITERALS = ("pi-rpc/1", "pi-rpc", "claude-code", "codex", "grok-build")


def _string_literals(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_the_common_lifecycle_names_no_brand():
    """A brand literal in the base means the mechanism is not general."""
    literals = _string_literals(COMMON_BASE)
    for brand in BRAND_LITERALS:
        assert brand not in literals, f"the common lifecycle hardcodes {brand!r}"


def test_the_common_lifecycle_hardcodes_no_provider_id():
    """The provider-id comparison must go through the ``provider_id`` hook."""
    source = COMMON_BASE.read_text(encoding="utf-8")
    assert "self.provider_id" in source, "the provider id is not parameterized"
    assert "self.protocol_id" in source, "the protocol name is not parameterized"
    # Every refusal in the base goes through the refusal hook.
    assert "PiLifecycleRefused" not in source


def test_the_brand_hooks_are_unset_by_default():
    assert UnitLifecycle.provider_id == ""
    assert UnitLifecycle.protocol_id == ""
    assert UnitLifecycle.refusal_type is UnitLifecycleRefused


def test_a_second_brand_can_drive_the_same_mechanism():
    """The mechanism runs for a brand that has nothing to do with pi."""

    class _Descriptor:
        supported_methods = ("plan_preparation",)

    class _OtherBrand(UnitLifecycle):
        provider_id = "other"
        protocol_id = "other/1"
        descriptor = _Descriptor()

        def _unsupported(self, *args, **kwargs):
            raise AssertionError("the other brand's plan must be supported")

    lifecycle = _OtherBrand()
    plan = lifecycle.plan_preparation(
        {"manifest": {}}, {"privateRootFacts": {"cwd": "/unit/cwd"}}, {"correlation": "c-1"}
    )
    assert plan["context"]["privateRootFacts"] == {"cwd": "/unit/cwd"}
    assert plan["correlation"] == {"correlation": "c-1"}


def test_the_other_brand_refusal_is_its_own_type():
    class _OtherRefused(UnitLifecycleRefused):
        code = "OTHER_REFUSED"

    class _OtherBrand(UnitLifecycle):
        provider_id = "other"
        refusal_type = _OtherRefused

    with pytest.raises(_OtherRefused):
        _OtherBrand()._refuse("nope")


def test_the_pi_has_no_separate_lifecycle_authority():
    import importlib.util
    import ordessa_harness_pi
    from ordessa_harness_pi import PiAcpHarnessPreparation
    assert PiAcpHarnessPreparation.harness_id == 'pi'
    for name in ('lifecycle','provider','runtime_channel','projection','termination'):
        assert importlib.util.find_spec('ordessa_harness_pi.'+name) is None
    for name in ('PiUnitLifecycle','PiRuntimeProvider','PiRpcChannelFactory','PiUnitProjection'):
        assert not hasattr(ordessa_harness_pi,name)


def test_the_generic_helpers_are_owned_by_the_common_base():
    assert plain({"a": 1}) == {"a": 1}
    assert same_reference({"a": 1}, {"a": 1}) is True
    assert same_reference({"a": 1}, {"a": 2}) is False
    assert same_reference({"a": 1}, {"a": "1"}) is False, "JSON scalar types must be retained"
    assert records_ready(None, None, None) is False
