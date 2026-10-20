"""External sample #1 — fourth controlled agent (sample-agent/1).

Public surface: :class:`SampleFourthAgentPlugin` and its frozen declaration
constants. Nothing here imports Agent, Profile, Harness or the environment.
"""
from .plugin import (
    CAPABILITIES,
    INTERACTION_SCHEMA,
    METHOD_CAPABILITIES,
    METHOD_ECHO,
    METHOD_STATUS,
    PLUGIN_ID,
    SampleFourthAgentPlugin,
)

__all__ = [
    "CAPABILITIES",
    "INTERACTION_SCHEMA",
    "METHOD_CAPABILITIES",
    "METHOD_ECHO",
    "METHOD_STATUS",
    "PLUGIN_ID",
    "SampleFourthAgentPlugin",
]
