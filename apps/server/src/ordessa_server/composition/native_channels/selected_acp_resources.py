"""Explicit public resource selection for this Host bundle."""
from ordessa_harness_codex.acp_resources import acp_resources as p0
from ordessa_harness_claude_code.acp_resources import acp_resources as p2
from ordessa_harness_opencode.acp_resources import acp_resources as p3
from ordessa_harness_hermes.acp_resources import acp_resources as p4
from ordessa_harness_dsh.acp_resources import acp_resources as p5
from ordessa_harness_kilo.acp_resources import acp_resources as p6
from ordessa_harness_qwen.acp_resources import acp_resources as p7

from ordessa_harness_grok_build.acp_resources import acp_resources as p8

def selected_acp_resources():
    return (
        ('plugins/harness/codex/src/ordessa_harness_codex', p0()),
        ('plugins/harness/claude-code/src/ordessa_harness_claude_code', p2()),
        ('plugins/harness/opencode/src/ordessa_harness_opencode', p3()),
        ('plugins/harness/hermes/src/ordessa_harness_hermes', p4()),
        ('plugins/harness/dsh/src/ordessa_harness_dsh', p5()),
        ('plugins/harness/kilo/src/ordessa_harness_kilo', p6()),
        ('plugins/harness/qwen/src/ordessa_harness_qwen', p7()),
        ('plugins/harness/grok-build/src/ordessa_harness_grok_build', p8()),
    )
