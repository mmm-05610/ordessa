"""Claude Code guest-layout declaration (brand projector knowledge).

This module declares how a resolved Claude launch plan maps to guest argv,
environment and runtime sources. It performs no assembly and starts nothing:
the retired shared assembler/coordinator seam
(``pacthold_runtime_compat.runtime_composition``) this module once called into
is deleted, and there is no second runtime coordinator. The single composition
authority lives outside this brand package.
"""
from __future__ import annotations
from ordessa_execution_api.environment.runtime_composition import HarnessCommandSpec, declare_source

def command_from_plan(plan, *, execution_id: str, io_mode: str) -> HarnessCommandSpec:
    """Declare the Claude Code guest layout; the Root assembler consumes it verbatim."""
    raw = [str(x) for x in plan.argv]
    if not raw: raise ValueError("CLAUDE_EMPTY_COMMAND")
    executable = raw[0]; raw[0] = "/runtime/bin/claude"
    env = {str(k): str(v) for k, v in dict(getattr(plan, "env", {})).items()}
    env.update({"HOME": "/runtime/home", "CLAUDE_CONFIG_DIR": "/runtime/home/.claude", "AGENT_BOX_EXECUTION_ID": execution_id, "PATH": "/usr/bin:/bin"})
    sources = [
        declare_source("workspace", plan.cwd, "/workspace", access="rw", provenance="workspace"),
        declare_source("profile-home", plan.profile_home, "/runtime/home", access="rw", provenance="profile"),
        declare_source("executable", executable, "/runtime/bin/claude", access="ro", provenance="executable"),
        declare_source("helper", plan.helper_dir, "/runtime/hooks", access="ro", provenance="helper"),
    ]
    return HarnessCommandSpec(tuple(raw), "/workspace", env, io_mode, runtime_sources=tuple(sources), projector_id="claude-code")
