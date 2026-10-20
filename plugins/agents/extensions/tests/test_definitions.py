"""EXT-2 — the hook definition model: shapes, bounds, honesty gates."""
from __future__ import annotations

import pytest

from ordessa_extensions.definitions import (
    KNOWN_EVENTS, ExtensionDefinitionError, HookDefinition,
    definition_fingerprint,
)


def make(**overrides):
    fields = dict(
        hook_id="notify-start", event="SessionStart", action_kind="command",
        command=("notify-send", "session started"), handler_ref=None,
        timeout_seconds=30, run_async=False, pin="0.147.0",
        content_sha256="sha256:" + "ab" * 32)
    fields.update(overrides)
    return HookDefinition(**fields)


def test_minimal_valid_definition_round_trips_payload():
    definition = make()
    payload = definition.payload()
    assert payload["hookId"] == "notify-start"
    assert payload["event"] == "SessionStart"
    assert payload["pin"] == "0.147.0"
    assert payload["contentSha256"] == "sha256:" + "ab" * 32


def test_event_vocabulary_is_exactly_the_evidenced_set():
    # SessionStart + PreToolUse + SubagentStop, each with an in-repo
    # citation — nothing smuggled in from vendor docs.
    assert sorted(KNOWN_EVENTS) == ["PreToolUse", "SessionStart",
                                    "SubagentStop"]
    for event, evidence in KNOWN_EVENTS.items():
        assert "plugins/harness" in evidence or "harnesses.toml" in evidence


@pytest.mark.parametrize("event", ["PostToolUse", "SessionEnd", "PreCompact",
                                   "UserPromptSubmit", "Stop", "sessionstart"])
def test_unevidenced_events_are_refused(event):
    with pytest.raises(ExtensionDefinitionError) as excinfo:
        make(event=event)
    assert excinfo.value.code == "EVENT_UNEVIDENCED"


def test_command_is_an_argv_tuple_not_a_shell_string():
    # the MODEL expresses commands as argv tuples only; a shell one-liner
    # passed as one argv element is expressible data but is graded HIGH
    # by the security scan and refused by approval/load (the construction
    # itself checks shape, not content — see test_security_scan.py)
    definition = make(command=("bash", "-lc", "echo hi && rm -rf /"))
    assert isinstance(definition.command, tuple)
    from ordessa_extensions.security import has_high, scan_definition
    assert has_high(scan_definition(definition))


def test_command_required_for_command_actions():
    with pytest.raises(ExtensionDefinitionError) as excinfo:
        make(command=None)
    assert excinfo.value.code == "COMMAND_REQUIRED"


def test_handler_action_needs_reference_and_no_command():
    with pytest.raises(ExtensionDefinitionError) as excinfo:
        make(action_kind="handler", handler_ref=None, command=None)
    assert excinfo.value.code == "HANDLER_REF_INVALID"
    with pytest.raises(ExtensionDefinitionError) as excinfo:
        make(action_kind="handler", handler_ref="recorder")
    assert excinfo.value.code == "ACTION_AMBIGUOUS"


def test_timeout_bounds():
    with pytest.raises(ExtensionDefinitionError):
        make(timeout_seconds=0)
    with pytest.raises(ExtensionDefinitionError):
        make(timeout_seconds=601)
    assert make(timeout_seconds=600).timeout_seconds == 600


def test_pin_and_hash_shapes_are_mechanism_d():
    with pytest.raises(ExtensionDefinitionError):
        make(pin="v0.147")
    with pytest.raises(ExtensionDefinitionError):
        make(content_sha256="deadbeef")
    assert make(content_sha256="sha256:" + "0" * 64).content_sha256


def test_fingerprint_is_stable_and_content_sensitive():
    base = make()
    assert definition_fingerprint(base) == definition_fingerprint(make())
    changed = make(command=("notify-send", "different"))
    assert definition_fingerprint(base) != definition_fingerprint(changed)
    repinned = make(pin="0.148.0")
    assert definition_fingerprint(base) != definition_fingerprint(repinned)
