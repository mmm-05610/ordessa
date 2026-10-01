"""Pinned Pi live dialect over the shared C4 runtime."""
from ...configuration.model.live_runtime import NativeLiveModelRuntime
from .context import PiLiveModelContext


class PiLiveModelRuntime(NativeLiveModelRuntime):
    harness_id = 'pi'
    native_version = (0, 5, 0)
    context_class = PiLiveModelContext
