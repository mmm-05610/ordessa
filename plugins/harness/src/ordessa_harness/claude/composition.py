from __future__ import annotations
from pacthold_runtime_compat.runtime_composition import HarnessCommandSpec, TerminalRunHandle, assemble_runtime_composition, declare_source

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

def composition_from_resolved_inputs(request, command):
    """Hand the projector command and frozen resolved inputs to the one shared
    Root assembler.  There is no second assembly path."""
    if command is None:
        raise ValueError("Claude composition requires the projected command")
    return assemble_runtime_composition(request, command)

def compose(coordinator, binding, command, *, execution_id, dispatch_id) -> TerminalRunHandle:
    if coordinator is None or binding is None: raise RuntimeError("Claude requires injected RuntimeCompositionCoordinator and RuntimeBinding")
    return coordinator.start(binding, command, execution_id=execution_id, dispatch_id=dispatch_id)
