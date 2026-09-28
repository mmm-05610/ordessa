"""Shared adapter contracts and the single internal brand adapter map."""
from .base import HarnessAdapter
from .codex import CodexAdapter
from .claude import ClaudeAdapter
from .opencode import OpenCodeAdapter
from .hermes import HermesAdapter
from .pi import PiAdapter
from .dsh import DshAdapter
from .kilo import KiloAdapter
from .generic_cli import GenericCliAdapter
ADAPTERS={"codex":CodexAdapter("codex"),"claude":ClaudeAdapter("claude"),"opencode":OpenCodeAdapter("opencode"),"hermes":HermesAdapter("hermes"),"pi":PiAdapter("pi"),"dsh":DshAdapter("dsh"),"kilo":KiloAdapter("kilo")}

__all__ = ["HarnessAdapter", "GenericCliAdapter", "ADAPTERS", "CodexAdapter",
           "ClaudeAdapter", "OpenCodeAdapter", "HermesAdapter", "PiAdapter",
           "DshAdapter", "KiloAdapter"]
