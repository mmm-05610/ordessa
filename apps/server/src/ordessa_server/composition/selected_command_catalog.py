"""Selected historical command-name facts; no runtime activation or readiness claim."""
from .command_catalog import capture_command_catalog
from ordessa_harness_claude_code.command_declarations import command_candidates as claude_code
from ordessa_harness_codex.command_declarations import command_candidates as codex
from ordessa_harness_dsh.command_declarations import command_candidates as dsh
from ordessa_harness_hermes.command_declarations import command_candidates as hermes
from ordessa_harness_kilo.command_declarations import command_candidates as kilo
from ordessa_harness_opencode.command_declarations import command_candidates as opencode
from ordessa_harness_pi.command_declarations import command_candidates as pi
from ordessa_harness_qwen.command_declarations import command_candidates as qwen


def capture_selected_command_catalog():
    return capture_command_catalog((claude_code(), codex(), dsh(), hermes(), kilo(), opencode(), pi(), qwen(),))
