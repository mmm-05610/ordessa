"""Existing wire version and typed access refusal at the injected boundary.

This module owns no authenticator, credential store, grants or business state.
Server transport catches this failure from its injected access port.
"""

WIRE_VERSION = "wire/1"


class AccessError(RuntimeError):
    """Stable access failure without credential material in its message."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
