"""The Prompts facet adapters as published `ConfigurationAdapter`s.

Same registration seam as Skills/Extensions: point
`harness.configuration-adapters` (v1, multi-owner), published
`ordessa_harness_api` vocabulary only, no harness-plugin import
(AGENTS.md rule 3). The honest state of instruction projection tonight
is recorded in `contribution.py` and graded in `capabilities.py`:
three semantics × eight brands, three implemented brands, four families
sent to phase-2 design, qwen removed by ruling.
"""
from __future__ import annotations

from .contribution import (
    CONFIGURATION_POINT, ENTRY, POINT_API_VERSION, PromptsConfigurationAdapter,
    prompts_adapters,
)

FACET_ID = "assets.prompts"

__all__ = ["CONFIGURATION_POINT", "ENTRY", "FACET_ID", "POINT_API_VERSION",
           "PromptsConfigurationAdapter", "prompts_adapters"]
