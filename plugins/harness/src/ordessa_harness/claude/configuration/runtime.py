"""Claude ACP 0.81.2 model-only C4 runtime; restoration is a separate operation."""
from ...configuration.model.live_runtime import NativeLiveModelRuntime


class ClaudeLiveModelRuntime(NativeLiveModelRuntime):
    harness_id = 'claude-code'
    native_version = (0, 81, 2)
