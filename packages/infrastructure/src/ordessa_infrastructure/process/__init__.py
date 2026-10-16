"""Neutral process/framing primitives.

Pure technical framing/failure contracts plus one generic process-spawn
primitive. No Agent/provider/environment/lease/admission semantics. Importing
this package opens nothing: ``spawn_process`` is the only thing that starts a
process, and it must be called explicitly.

The concrete base class is defined **once** here (``ChannelFailure``); Agent-side
transport subclasses it, so there is no duplicate base identity.
"""
from .framing import MAX_FRAME_BYTES, ChannelFailure, FrameReader, FramingError, Message
from .spawn import SubprocessHandle, spawn_process

__all__ = [
    "MAX_FRAME_BYTES",
    "ChannelFailure",
    "FramingError",
    "Message",
    "FrameReader",
    "SubprocessHandle",
    "spawn_process",
]
