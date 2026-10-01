"""Codex ACP 1.1.14 model-only C4 runtime; restoration is a separate operation."""
from ...configuration.model.live_runtime import NativeLiveModelRuntime


class CodexLiveModelRuntime(NativeLiveModelRuntime):
    harness_id = 'codex'
    native_version = (1, 1, 14)
