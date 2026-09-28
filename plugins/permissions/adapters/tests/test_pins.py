"""T03 red/green: per-pin facts read from the real repository data.

The pinned families, their identity versions, capability lists, profile slots
and the dsh `request_permission` note are parsed straight from
`plugins/harness/src/ordessa_harness/harnesses.toml` with `tomllib` - no
version string is hardcoded here, so a pin bump moves these assertions with
the registry instead of silently drifting.

"已允许工具类型" per pinned family is asserted against each adapter's declared
tool-category expressibility: every tool key of the consumed domain vocabulary
must be explicitly classified (expressible actions), never left implied.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api.rules import TOOL_KEYS

from _permissions_adapters_helpers import DRIVER_TO_HARNESS_ID
from ordessa_permissions_adapters import (
    CAPABILITY_CELLS,
    ClaudeAdapter,
    CodexAdapter,
    NativeVersionRange,
    PiAdapter,
    configuration_descriptor,
    default_adapters,
    select_adapter,
)

ADAPTER_CLASSES = {"codex": CodexAdapter, "claude-code": ClaudeAdapter, "pi": PiAdapter}


def test_registry_covers_exactly_the_three_adapted_brands(families) -> None:
    assert set(families) >= {"codex", "claude-code", "pi"}
    assert set(ADAPTER_CLASSES) == {"codex", "claude-code", "pi"}
    # every other pinned family is NOT claimed by any policy adapter
    for harness_type, family in families.items():
        driver = family["driver"]
        adapted = driver in DRIVER_TO_HARNESS_ID
        selected = select_adapter(harness_type, family["identity"]["version"])
        if adapted:
            assert selected is not None, f"{harness_type} pin not covered by its range"
            assert selected.harness_id == harness_type
        else:
            assert selected is None, f"{harness_type} is claimed without an adapter"


def test_pinned_version_ranges_match_the_recorded_pins(pinned_versions) -> None:
    for harness, cls in ADAPTER_CLASSES.items():
        adapter = cls()
        assert adapter.version_range.contains(pinned_versions[harness]), harness
        # and a range is a real bounded range, not "everything"
        assert not adapter.version_range.contains("999999.0"), harness


def test_codex_declares_permissions_capability_and_slot(families) -> None:
    # harnesses.toml:13 (capabilities) and :31 (profile slots) - the measured
    # reason the codex gate cell has channel evidence while others do not.
    codex = families["codex"]
    assert "permissions" in codex["capabilities"]
    assert "permission" in codex["profile"]["slots"]


def test_claude_and_pi_declare_no_runtime_permissions_capability(families) -> None:
    # Honest negative: their harness rows do NOT declare `permissions`, so a
    # pre-effect gate cell can only be unknown/unsupported for them.
    for harness in ("claude-code", "pi"):
        assert "permissions" not in families[harness]["capabilities"]
        gate = [c for c in CAPABILITY_CELLS if c.harness_id == harness
                and c.capability == "pre-effect-gate"]
        assert gate and all(c.status != "supported" for c in gate)


def test_dsh_note_names_request_permission_but_declares_no_capability(families) -> None:
    # The line-~248 note: dsh's official ACP surface documents
    # `request_permission`, yet `permissions` is deliberately not declared.
    dsh = families["dsh"]
    assert "permissions" not in dsh["capabilities"]
    assert select_adapter("dsh", "0.1.5-rc.1") is None


def test_expressible_tool_categories_are_declared_per_pinned_family() -> None:
    # Every key of the consumed vocabulary is explicitly classified, so a new
    # tool key in `ordessa_permissions_api` forces a decision here (no silent
    # "unknown key reads as no rule").
    expected_claude = {
        "read": {"ask", "deny"}, "edit": {"ask", "deny"}, "bash": {"ask", "deny"},
        "task": {"ask", "deny"}, "webfetch": {"ask", "deny"}, "skill": {"ask", "deny"},
        # no pinned settings rule-name for external_directory (posture_config.py:56-63)
        "external_directory": set(),
    }
    expected_codex = {
        # sandbox expresses write denials; approval gates commands, never denies
        "edit": {"ask", "deny"}, "external_directory": {"ask", "deny"},
        "read": {"ask"}, "bash": {"ask"}, "task": {"ask"}, "webfetch": {"ask"},
        "skill": {"ask"},
    }
    expected_pi = {key: set() for key in TOOL_KEYS}  # nothing built-in is pinned
    for cls, expected in ((ClaudeAdapter, expected_claude), (CodexAdapter, expected_codex),
                          (PiAdapter, expected_pi)):
        table = cls().expressible_actions()
        assert set(table) == set(TOOL_KEYS), cls.__name__
        for key, actions in expected.items():
            assert set(table[key]) == actions, (cls.__name__, key)


def test_claude_native_tool_names_are_the_measured_map() -> None:
    adapter = ClaudeAdapter()
    assert adapter.native_tool_names("bash") == ("Bash",)
    assert set(adapter.native_tool_names("read")) == {"Read", "Glob", "Grep"}
    assert set(adapter.native_tool_names("webfetch")) == {"WebFetch", "WebSearch"}
    assert adapter.native_tool_names("external_directory") == ()


def test_codex_writable_vocabulary_is_the_measured_strictness_tables() -> None:
    adapter = CodexAdapter()
    assert set(adapter.writable_sandbox_values()) == {"read-only", "workspace-write"}
    assert set(adapter.writable_approval_values()) == {"untrusted", "on-request"}
    # strictness ordering is the measured one (posture_config.py:77-78)
    assert adapter.sandbox_strictness("read-only") > adapter.sandbox_strictness(
        "workspace-write") > adapter.sandbox_strictness("danger-full-access")
    assert adapter.approval_strictness("untrusted") > adapter.approval_strictness(
        "on-request") > adapter.approval_strictness("never")


def test_ranges_parse_the_pinned_version_spellings(families) -> None:
    # every identity version in the registry parses, including pre-release
    # spellings like dsh "0.1.5-rc.1".
    for family in families.values():
        version = family["identity"]["version"]
        bounds = NativeVersionRange(minimum=version, maximum="99999.0")
        assert bounds.contains(version), version


def test_descriptor_claims_recompile_from_current_pins(pinned_versions) -> None:
    # the claim compiled into each contribution descriptor must be exactly
    # the pin of record: if harnesses.toml moves, this test goes red until
    # the package's PINNED_NATIVE_VERSIONS claim is updated deliberately.
    for adapter in default_adapters():
        descriptor = configuration_descriptor(adapter)
        parts = [int(p) for p in pinned_versions[adapter.harness_id].split(".")]
        pin = tuple(parts + [0] * (3 - len(parts)))
        assert descriptor.native_versions.minimum == pin, adapter.harness_id
        assert descriptor.native_versions.maximum == pin, adapter.harness_id
