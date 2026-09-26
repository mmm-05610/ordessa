"""Order 85: the posture write lands in pinned native keys or refuses typed.

Each family gets the positive case (the posture lands where stage 1 measured a
read point), the merge case (the reviewed file survives), and the two refusals
that matter: a loosening the writer could have made, and a key it was never
given a basis for. The real-config comparison against the pinned artifacts is
evidence in `posture-config-keys-085.md`; these tests stay hermetic.
"""
from __future__ import annotations

import json

import pytest

from ordessa_server_compat.profiles.permissions import resolve_all
from ordessa_server_compat.profiles.posture_config import (
    PINNED_FAMILIES,
    RENDERERS,
    PostureConfigError,
    render_posture_config,
    write_posture_config,
)
from ordessa_server_compat.profiles.posture_translation import _CLAUDE_TOOLS

CLAUDE_BASE = json.dumps({
    "env": {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"},
    "model": "deepseek-flash",
}, indent=2) + "\n"

CODEX_BASE = """\
# reviewed template
model = "deepseek-chat"
model_provider = "deepseek"

[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com"
"""


def _posture(rules, preset="default"):
    return resolve_all(rules, preset=preset)


# ------------------------------------------------------------ claude-code G1

def test_posture_write_claude_lands_only_the_pinned_permission_rules():
    posture = _posture([
        {"key": "edit", "action": "deny"},
        {"key": "read", "action": "allow"},
        {"key": "external_directory", "action": "allow"},
    ])
    rendered = render_posture_config(posture, harness="claude-code", base=CLAUDE_BASE)
    document = json.loads(rendered["text"])

    assert "Edit" in document["permissions"]["deny"]
    assert "Write" in document["permissions"]["deny"]
    assert "NotebookEdit" in document["permissions"]["deny"]
    # The default preset leaves bash at `ask`, and `ask` has a real landing
    # site at the settings layer (unlike 60's flag-level vocabulary).
    assert "Bash" in document["permissions"]["ask"]
    # Every key of the reviewed file survives the write untouched.
    assert document["env"] == {"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"}
    assert document["model"] == "deepseek-flash"
    # G1's snapshot comparison is stated, not hoped for.
    paths = {change["path"] for change in rendered["changes"]}
    assert paths == {"permissions.ask", "permissions.deny"}


def test_posture_write_claude_never_emits_a_key_stage_one_found_no_read_point_for():
    fully_permissive = _posture(
        [{"key": key, "action": "allow"} for key in
         ("read", "edit", "bash", "task", "external_directory", "webfetch", "skill")],
        preset="full-access")
    rendered = render_posture_config(
        fully_permissive, harness="claude-code", base=CLAUDE_BASE)
    assert rendered["changes"] == []
    document = json.loads(rendered["text"])
    for absent in ("allowedTools", "disallowedTools", "allow", "defaultMode",
                   "permissions"):
        assert absent not in document
    assert document["model"] == "deepseek-flash"  # the file is not rewritten either


def test_posture_write_claude_keeps_the_rules_the_file_already_declares():
    base = json.dumps({"permissions": {"deny": ["WebFetch", "Task"]}}, indent=2)
    rendered = render_posture_config(
        _posture([{"key": "edit", "action": "deny"},
                  {"key": "external_directory", "action": "allow"}]),
        harness="claude-code", base=base)
    deny = json.loads(rendered["text"])["permissions"]["deny"]
    assert "WebFetch" in deny and "Task" in deny and "Edit" in deny
    change = next(c for c in rendered["changes"] if c["path"] == "permissions.deny")
    assert change["before"] == ["WebFetch", "Task"]


def test_posture_write_claude_reports_one_change_per_path_from_the_file_as_it_stood():
    # Two keys can land in the same rule list. The snapshot is the write's
    # receipt, so it states the path once, against the base as it stood — not
    # one row per key, which would hide that a later key overwrote an earlier
    # one.
    base = json.dumps({"permissions": {"deny": ["WebSearch"]}}, indent=2)
    rendered = render_posture_config(
        _posture([{"key": "edit", "action": "deny"},
                  {"key": "webfetch", "action": "deny"},
                  {"key": "bash", "action": "ask"},
                  {"key": "task", "action": "ask"},
                  {"key": "external_directory", "action": "allow"}]),
        harness="claude-code", base=base)
    deny = json.loads(rendered["text"])["permissions"]["deny"]
    assert deny == sorted({"WebSearch", "Edit", "Write", "NotebookEdit",
                           "WebFetch"})
    assert [c["path"] for c in rendered["changes"]] == [
        "permissions.ask", "permissions.deny"]
    change = next(c for c in rendered["changes"] if c["path"] == "permissions.deny")
    assert change["before"] == ["WebSearch"]
    assert change["after"] == deny


def test_posture_write_claude_does_not_report_a_rule_it_did_not_add():
    # The posture asks for nothing the reviewed file does not already deny. The
    # write is a no-op there, and a snapshot that called it a change - or that
    # took the opportunity to reformat the file's own rule order - would read
    # as if something had been tightened.
    base = json.dumps({"permissions": {"deny": ["NotebookEdit", "Edit", "Write"]}},
                      indent=2) + "\n"
    posture = _posture([{"key": key, "action": "allow"} for key in
                        ("read", "bash", "task", "webfetch", "skill",
                         "external_directory")]
                       + [{"key": "edit", "action": "deny"}])
    rendered = render_posture_config(posture, harness="claude-code", base=base)
    assert rendered["changes"] == []
    assert rendered["text"] == base  # byte for byte, order and all


# ------------------------------------------------------------ claude-code G3

def test_posture_write_claude_refuses_a_key_it_has_no_rule_name_for(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(CLAUDE_BASE, encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(PostureConfigError) as refused:
        write_posture_config(
            _posture([{"key": "external_directory", "action": "deny"}]),
            harness="claude-code", destination=target)
    assert refused.value.code == "POSTURE_CONFIG_UNEXPRESSIBLE"
    assert refused.value.key == "external_directory"
    assert target.read_bytes() == before  # refusal, not a partial write


@pytest.mark.parametrize("base", [
    "{not json",
    "[]",
    '{"permissions": "nope"}',
    '{"permissions": {"deny": [123]}}',
])
def test_posture_write_claude_refuses_a_base_shape_it_cannot_vouch_for(base):
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(
            _posture([{"key": "edit", "action": "deny"},
                      {"key": "external_directory", "action": "allow"}]),
            harness="claude-code", base=base)
    assert refused.value.code in {
        "POSTURE_CONFIG_BASE_UNPARSEABLE", "POSTURE_CONFIG_BASE_SHAPE"}


# ------------------------------------------------------------------- codex G1

def test_posture_write_codex_tightens_the_two_pinned_scalars():
    posture = _posture([{"key": "edit", "action": "deny"}], preset="plan")
    rendered = render_posture_config(posture, harness="codex", base=CODEX_BASE)
    text = rendered["text"]

    assert 'sandbox_mode = "read-only"' in text
    assert 'approval_policy = "untrusted"' in text  # bash is gated -> untrusted
    # Text surgery: everything the order is not about stays verbatim.
    assert "# reviewed template" in text
    assert '[model_providers.deepseek]' in text
    assert 'base_url = "https://api.deepseek.com"' in text
    # Both scalars sit above the first table header, where they belong.
    assert text.index("sandbox_mode") < text.index("[model_providers.deepseek]")
    assert {c["path"] for c in rendered["changes"]} == {
        "sandbox_mode", "approval_policy"}


def test_posture_write_codex_never_loosens_a_file_that_is_already_stricter():
    # The posture asks for `on-request` (only `edit` is gated), while the
    # reviewed file already says `untrusted`. G2 is exactly this direction:
    # the writer keeps the strict value, and does not "helpfully" match posture.
    base = ('sandbox_mode = "read-only"\napproval_policy = "untrusted"\n' + CODEX_BASE)
    posture = _posture([{"key": key, "action": "allow"} for key in
                        ("read", "bash", "task", "external_directory", "webfetch", "skill")])
    rendered = render_posture_config(posture, harness="codex", base=base)
    assert rendered["changes"] == []
    assert rendered["text"] == base  # byte for byte: nothing is loosened
    assert any("approval_policy kept at 'untrusted'" in note for note in rendered["notes"])


def test_posture_write_codex_writes_nothing_at_all_for_a_permissive_posture():
    base = 'sandbox_mode = "workspace-write"\napproval_policy = "on-request"\n'
    posture = _posture(
        [{"key": key, "action": "allow"} for key in
         ("read", "edit", "bash", "task", "external_directory", "webfetch", "skill")],
        preset="full-access")
    rendered = render_posture_config(posture, harness="codex", base=base)
    assert rendered["changes"] == [] and rendered["text"] == base


def test_posture_write_codex_tightens_only_the_looser_of_the_two():
    base = 'sandbox_mode = "workspace-write"\nweb_search = "disabled"\n'
    rendered = render_posture_config(
        _posture([{"key": "edit", "action": "deny"}], preset="plan"),
        harness="codex", base=base)
    changes = {c["path"]: (c["before"], c["after"]) for c in rendered["changes"]}
    assert changes["sandbox_mode"] == ("workspace-write", "read-only")
    assert 'web_search = "disabled"' in rendered["text"]


# ------------------------------------------------------------------- codex G3

@pytest.mark.parametrize("key", ["bash", "webfetch", "skill", "task"])
def test_posture_write_codex_refuses_a_per_tool_deny_it_cannot_express(key):
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(
            _posture([{"key": key, "action": "deny"}]),
            harness="codex", base=CODEX_BASE)
    assert refused.value.code == "POSTURE_CONFIG_UNEXPRESSIBLE"
    assert refused.value.key == key


def test_posture_write_codex_refuses_a_legacy_inline_profile_table():
    base = CODEX_BASE + '\n[profiles.tight]\nsandbox_mode = "read-only"\n'
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(
            _posture([{"key": "edit", "action": "deny"}], preset="plan"),
            harness="codex", base=base)
    # Measured on 0.147.0: -p hard-errors while such a table is present.
    assert refused.value.code == "POSTURE_CONFIG_BASE_LEGACY_PROFILE"


def test_posture_write_codex_refuses_a_base_value_outside_the_pinned_vocabulary():
    base = 'sandbox_mode = "sometimes-write"\n' + CODEX_BASE
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(
            _posture([{"key": "edit", "action": "deny"}], preset="plan"),
            harness="codex", base=base)
    assert refused.value.code == "POSTURE_CONFIG_BASE_VALUE"


# ------------------------------------------------------- refusals both families

def _registered_families():
    from ordessa_harness.registry.loader import load_builtin_registry
    return {d.harness_type: tuple(d.capabilities)
            for d in load_builtin_registry().all()}


#: Stage 4: the refusal list comes from the harness registry, not from a copy
#: of the family names, so a family added to the registry is refused (or has to
#: pin its keys) on the day it lands rather than after someone remembers.
UNPINNED_FAMILIES = sorted(
    set(_registered_families()) - set(PINNED_FAMILIES))


@pytest.mark.parametrize("harness", UNPINNED_FAMILIES)
def test_posture_write_refuses_every_family_with_no_pinned_key(harness, tmp_path):
    target = tmp_path / "config"
    target.write_text("unchanged", encoding="utf-8")
    with pytest.raises(PostureConfigError) as refused:
        write_posture_config(_posture([{"key": "edit", "action": "deny"}]),
                             harness=harness, destination=target)
    assert refused.value.code == "POSTURE_CONFIG_UNPINNED_HARNESS"
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_posture_write_refuses_a_harness_that_is_not_in_the_registry_at_all(tmp_path):
    target = tmp_path / "config"
    target.write_text("unchanged", encoding="utf-8")
    with pytest.raises(PostureConfigError) as refused:
        write_posture_config(_posture([{"key": "edit", "action": "deny"}]),
                             harness="not-a-harness", destination=target)
    assert refused.value.code == "POSTURE_CONFIG_UNPINNED_HARNESS"


def test_posture_write_pinned_families_are_all_registered_harnesses():
    registered = set(_registered_families())
    assert set(PINNED_FAMILIES) <= registered
    assert set(RENDERERS) == set(PINNED_FAMILIES)


def test_posture_write_pinning_is_not_the_same_axis_as_the_runtime_permission_capability():
    # `permissions` in the registry means "this family answers a permission
    # request at runtime", and measured on the built registry claude-code does
    # not claim it while codex does. Neither fact bears on whether a posture
    # can be *materialised into the reviewed settings file*, which stage 1
    # pinned first-hand for both families. This test exists to stop a later
    # reader from deriving the write vocabulary from the capability list.
    capabilities = _registered_families()
    assert "permissions" in capabilities["codex"]
    assert "permissions" not in capabilities["claude-code"]
    assert set(PINNED_FAMILIES) <= set(capabilities)


def test_posture_write_refuses_an_unknown_key_or_action_rather_than_reading_it_as_absent():
    bad = {"preset": "default", "keys": {"edit": "deny", "bosh": "deny"}}
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(bad, harness="codex", base=CODEX_BASE)
    assert refused.value.code == "POSTURE_CONFIG_UNKNOWN_KEY"

    bad_action = {"preset": "default", "keys": {"edit": "maybe"}}
    with pytest.raises(PostureConfigError) as refused:
        render_posture_config(bad_action, harness="codex", base=CODEX_BASE)
    assert refused.value.code == "POSTURE_CONFIG_UNKNOWN_ACTION"


def test_posture_write_pinned_families_are_the_only_reachable_writers():
    assert set(PINNED_FAMILIES) == {"claude-code", "codex"}


# ------------------------------------------------------------- drift and atomicity

def test_posture_write_claude_rule_names_agree_with_order_60_flag_names():
    # 60 translates for the flag vocabulary; this writer lands in the settings
    # vocabulary. The two must name the same tools per key, or one of them is
    # quietly gating a different set.
    from ordessa_server_compat.profiles.posture_config import _CLAUDE_SETTINGS_TOOLS
    assert _CLAUDE_SETTINGS_TOOLS.keys() == _CLAUDE_TOOLS.keys()
    for key in _CLAUDE_SETTINGS_TOOLS:
        assert set(_CLAUDE_SETTINGS_TOOLS[key]) == set(_CLAUDE_TOOLS[key])


def test_posture_write_lands_atomically_and_is_idempotent(tmp_path):
    target = tmp_path / "nested" / "settings.json"
    posture = _posture([{"key": "edit", "action": "deny"},
                        {"key": "external_directory", "action": "allow"}])
    first = write_posture_config(posture, harness="claude-code", destination=target)
    assert first["written"] is True
    written = target.read_bytes()
    assert list(target.parent.iterdir()) == [target]  # no temp file left behind

    second = write_posture_config(posture, harness="claude-code", destination=target)
    assert second["changes"] == [] and second["written"] is False
    assert target.read_bytes() == written


def test_posture_write_creates_a_missing_file_from_the_posture_alone(tmp_path):
    target = tmp_path / "config.toml"
    written = write_posture_config(
        _posture([{"key": "edit", "action": "deny"}], preset="plan"),
        harness="codex", destination=target)
    assert written["written"] is True
    assert 'sandbox_mode = "read-only"' in target.read_text(encoding="utf-8")
