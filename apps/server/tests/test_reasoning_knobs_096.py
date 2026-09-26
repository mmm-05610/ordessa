"""Work Order 096: the reasoning-knob domain and its validation.

Two invariants the whole order rests on, asserted here so they cannot drift:
the domain is model-facts ∪ pinned enum (translated, de-duplicated, stable),
and an *undeclared* domain never accepts a value (no invented options). The
default is the middle, never the highest.
"""
from __future__ import annotations

import pytest

from ordessa_server.errors import ServerError
from ordessa_server_compat.model_configs.reasoning_knobs import (
    default_effort, effective_domain, validate_reasoning_value,
)


def test_codex_effective_domain_is_the_pinned_enum_in_order():
    assert effective_domain("codex") == ("low", "medium", "high")


def test_model_facts_widen_the_domain_via_dialect_translation():
    # opencode's pinned set + a model that reports an extra `xhigh`-beyond fact
    # mapped through the family's dialect (here identity). de-duped, stable.
    dom = effective_domain("opencode", model_effort_values=["medium", "ultramax"],
                           dialect_map={"ultramax": "ultramax"})
    assert dom == ("low", "medium", "high", "xhigh", "ultramax")
    # translation renames a canonical value into the family's spelling
    assert "ultramax" in effective_domain("codex", model_effort_values=["max"],
                                          dialect_map={"max": "ultramax"})


def test_undeclared_family_has_no_domain_and_refuses_any_value():
    # qwen/dsh effort enums are NOT pinned and there are no model facts -> no
    # domain; the knob is "未声明" and a submitted value is refused, not accepted.
    assert effective_domain("qwen") is None
    with pytest.raises(ServerError) as exc:
        validate_reasoning_value("qwen", "high")
    assert exc.value.code == "CONTROL_VALUE_UNSUPPORTED"


def test_value_outside_domain_is_typed_refusal_naming_control_and_value():
    with pytest.raises(ServerError) as exc:
        validate_reasoning_value("codex", "xhigh")   # codex pins low/medium/high
    assert exc.value.code == "CONTROL_VALUE_UNSUPPORTED"
    assert "xhigh" in str(exc.value.message)
    # a legal value passes through unchanged
    assert validate_reasoning_value("codex", "medium") == "medium"


def test_model_facts_alone_give_a_domain_even_when_family_enum_unpinned():
    # dsh has no pinned enum, but a model fact still yields a domain (translated).
    dom = effective_domain("dsh", model_effort_values=["low", "medium"],
                           dialect_map={"low": "low", "medium": "medium"})
    assert dom == ("low", "medium")
    assert validate_reasoning_value("dsh", "medium", model_effort_values=["low", "medium"]) == "medium"


def test_default_is_middle_never_highest():
    assert default_effort(("low", "medium", "high")) == "medium"
    assert default_effort(("low", "medium", "high", "xhigh")) == "medium"
    assert default_effort(("low", "high")) == "low"    # lower middle of an even set
    assert default_effort(None) is None                 # undeclared -> no invented default
