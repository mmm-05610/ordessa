"""Order 60 leftover: the per-family posture translation, stricter-or-refuse.

Each family gets a positive case (the posture lands in its own vocabulary) and
the refusal case that matters: a posture the family cannot express *narrowly*
must refuse, never silently default to permissive.
"""
from __future__ import annotations

import pytest

from ordessa_server_compat.profiles.permissions import resolve_all
from ordessa_server_compat.profiles.posture_translation import (
    PostureTranslationError,
    translate_posture,
)


def _posture(rules, preset="default"):
    return resolve_all(rules, preset=preset)


def test_claude_gets_the_tool_lists_and_only_the_unexpressible_refuses():
    posture = _posture([
        {"key": "edit", "action": "deny"},
        {"key": "webfetch", "action": "allow"},
        {"key": "bash", "action": "ask"},
        # No claude knob exists for this key, so it must be permissive for the
        # translation to be possible at all.
        {"key": "external_directory", "action": "allow"},
    ])
    translated = translate_posture(posture, harness="claude-code")
    assert "Edit" in translated["disallowedTools"]
    assert "Write" in translated["disallowedTools"]
    assert "WebFetch" in translated["allowedTools"]
    # Order 111 (R-0032): `ask` is claude's permissions.ask path, NOT an
    # auto-approved allowedTools entry. The old test asserted `"Bash" in
    # allowedTools` ("ask = its own approval"), which is the bug: putting the
    # tool in the pre-approval set means it never prompts. Tightened, not
    # relaxed: it must be in `ask` and demonstrably NOT in `allowedTools`.
    assert "Bash" in translated["ask"]
    assert "Bash" not in translated["allowedTools"]
    assert any("ask" in note for note in translated["notes"])

    # external_directory=deny has no tool name to hang on: refuse.
    with pytest.raises(PostureTranslationError) as refused:
        translate_posture(_posture([{"key": "external_directory", "action": "deny"}]),
                          harness="claude-code")
    assert refused.value.code == "PERMISSION_POSTURE_UNEXPRESSIBLE"
    assert refused.value.key == "external_directory"

    # `ask` on that key is just as unexpressible as `deny`: both are narrower
    # than the family's default, and dropping either would be a silent widening.
    with pytest.raises(PostureTranslationError):
        translate_posture(_posture([{"key": "external_directory", "action": "ask"}]),
                          harness="claude-code")

    # A permissive posture for that key is fine - the family default applies.
    permissive = translate_posture(
        _posture([{"key": "external_directory", "action": "allow"}]), harness="claude-code")
    assert any("no claude knob" in note for note in permissive["notes"])


def test_codex_gets_its_coarse_knobs_and_refuses_what_they_cannot_express():
    read_only = translate_posture(
        _posture([{"key": "edit", "action": "deny"}]), harness="codex")
    assert read_only["sandboxMode"] == "read-only"

    workspace = translate_posture(
        _posture([{"key": "edit", "action": "allow"},
                  {"key": "bash", "action": "allow"}]), harness="codex")
    assert workspace["sandboxMode"] == "workspace-write"
    assert workspace["approvalPolicy"] == "on-request"

    gated = translate_posture(
        _posture([{"key": "edit", "action": "allow"},
                  {"key": "bash", "action": "ask"}]), harness="codex")
    assert gated["approvalPolicy"] == "untrusted"
    assert any("approval" in note for note in gated["notes"])

    for key in ("bash", "webfetch", "skill", "task"):
        with pytest.raises(PostureTranslationError) as refused:
            translate_posture(_posture([{"key": key, "action": "deny"}]), harness="codex")
        assert refused.value.code == "PERMISSION_POSTURE_UNEXPRESSIBLE"
        assert refused.value.key == key

    # A family with no translator refuses by name.
    with pytest.raises(PostureTranslationError):
        translate_posture(_posture([]), harness="pi")
