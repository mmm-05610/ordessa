"""pi's native-config dialect facts (P-A② split: approvals/PA2-dialect-release.md).

Only this family's facts; the shared engine consumes the table and refuses
whatever is not pinned here.
"""
from __future__ import annotations

#: first-hand source: deployment/models.json providers.deepseek.api = "openai-completions".
from ordessa_harness_pi.acp_model_facts import DIALECT as DIALECTS
from ordessa_harness_pi.acp_model_facts import NATIVE_TARGET as _TARGETS
NATIVE_TARGET = _TARGETS["pi"]
