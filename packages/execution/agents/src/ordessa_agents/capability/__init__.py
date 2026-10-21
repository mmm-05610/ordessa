"""Public capability adapters over the original Agent/Profile owner.

They bind only the existing public owner ports plus the frozen interface
contracts. Server and CLI publish the SAME implementation; no second owner,
store or effect path is created here.
"""
from .harness import build_harness_capability
from .instances import build_agent_capability
from .native import build_native_capability
from .profiles import build_profile_capability

__all__ = ["build_agent_capability", "build_harness_capability",
           "build_native_capability", "build_profile_capability"]
