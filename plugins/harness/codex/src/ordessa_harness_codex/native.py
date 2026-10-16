"""codex's native-config dialect facts (P-A② split: approvals/PA2-dialect-release.md).

This family module holds **only this family's facts** - no logic, no imports of
siblings. The shared engine in ``pacthold.harness_kit.native_materialization``
consumes the table and refuses any family/protocol pair that is not pinned here.
"""
from __future__ import annotations

#: native field + dialect value per canonical protocol; first-hand source:
#:   deployment/config.toml [model_providers.deepseek] wire_api="responses";
#:   wire/handlers.py accepts wireApi {chat_completions, responses}.
from ordessa_harness_codex.acp_model_facts import DIALECT as DIALECTS
from ordessa_harness_codex.acp_model_facts import NATIVE_TARGET as _TARGETS

#: First-hand-pinned native config target path (relative to the guest home).
NATIVE_TARGET = _TARGETS["codex"]
