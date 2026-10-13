"""Pi-native guest-layout declaration (no assembly path).

This module projects a Pi request into a typed ``HarnessCommandSpec``
(guest argv, cwd token, runtime sources).  It starts or coordinates no
runtime: the legacy assembly seam (``assemble_runtime_composition``) is
retired with no successor in this round, so this declaration currently
has no consumer.  Contract types come from the neutral port
``ordessa_execution_api.environment.runtime_composition``.
"""
from __future__ import annotations
from typing import Any
from ordessa_execution_api.environment.runtime_composition import HarnessCommandSpec, declare_source
from ordessa_execution_api.resources.profiles import AgentBoxProfileV1
from ordessa_execution_api.resources.prompts import PromptFragmentV1
from ordessa_execution_api.resources.workspace import WorkspaceV1
from .profile import PiProfile
from .continuation import PiContinuationV1

def _one(request: Any, contract: str, required: bool = True):
    values = [x.value for x in request.resolved_inputs if x.contract_id == contract]
    if required and len(values) != 1: raise ValueError(f"Pi requires exactly one {contract}")
    if not required and len(values) > 1: raise ValueError(f"Pi allows at most one {contract}")
    return values[0] if values else None

class PiProjection:
    """Projects only typed, dispatch-local sources; it never reads credentials.

    The Pi projector owns the guest layout and declares it as typed runtime
    sources; the single Root generic assembler consumes that plan verbatim.
    """
    def command(self, request: Any, profile: PiProfile) -> HarnessCommandSpec:
        workspace = _one(request, WorkspaceV1.contract_id)
        fragments = [x.value for x in request.resolved_inputs if x.contract_id == PromptFragmentV1.contract_id]
        if not fragments: raise ValueError("Pi requires at least one prompt fragment")
        prompt = "\n\n".join(f"# {x.title}\n\n{x.content}" for x in fragments if isinstance(x, PromptFragmentV1))
        argv = ["/runtime/bin/pi", "--provider", profile.provider, "--model", profile.model,
                "--thinking", profile.thinking, "--agent-dir", "/runtime/home",
                "--session-dir", "/runtime/home/sessions", "--print", prompt]
        continuation = _one(request, PiContinuationV1.contract_id, False)
        if continuation is not None:
            argv[argv.index("--print"):argv.index("--print")] = ["--session", continuation.session_file or continuation.session_id]
        else:
            argv[argv.index("--print"):argv.index("--print")] = ["--session-id", request.execution_id]
        if profile.instructions: argv[argv.index("--print"):argv.index("--print")] = ["--system-prompt", "/runtime/home/instructions.md"]
        for _ in profile.skill_dirs: argv[argv.index("--print"):argv.index("--print")] = ["--skill-dir", "/runtime/home/skills"]
        if profile.mcp_config: argv[argv.index("--print"):argv.index("--print")] = ["--mcp-config", "/runtime/home/mcp.json"]
        sources = [declare_source("workspace", workspace.path, "/workspace", access="rw", provenance="workspace"),
                   declare_source("pi-profile-home", profile.agent_dir, "/runtime/home", access="rw", provenance="profile"),
                   declare_source("pi-executable", profile.binary, "/runtime/bin/pi", access="ro", provenance="executable")]
        if profile.helper: sources.append(declare_source("helper", profile.helper, "/runtime/hooks", access="ro", provenance="helper"))
        if profile.instructions: sources.append(declare_source("pi-instructions", profile.instructions, "/runtime/home/instructions.md", access="ro", provenance="instructions"))
        if profile.mcp_config: sources.append(declare_source("pi-mcp", profile.mcp_config, "/runtime/home/mcp.json", access="ro", provenance="mcp"))
        return HarnessCommandSpec(tuple(argv), "/workspace", {"AGENT_BOX_EXECUTION_ID": request.execution_id}, profile.io_mode, runtime_sources=tuple(sources), projector_id="pi")

def command_from_request(request: Any, profile: PiProfile) -> HarnessCommandSpec:
    return PiProjection().command(request, profile)
