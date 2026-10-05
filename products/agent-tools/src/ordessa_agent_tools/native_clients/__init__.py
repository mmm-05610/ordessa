"""Staged, unenabled clients for the seven remaining migration families.

Codex, Pi and Claude Code protocol implementations belong exclusively to
plugins/harness/{codex,pi,claude-code}; no compatibility re-export is provided.
This source-only staging package and its shared transports are excluded from
the independent CLI wheel. They do not publish runtime readiness or a registry.
The public executable-discovery catalog remains owned by Harness.
"""

from ._transport import (
    ChannelClosed,
    ChannelFailure,
    FrameReader,
    FramingError,
    LaunchSpec,
    LostReceipt,
    Message,
    ProcessChannel,
    RemoteFailure,
    RequestTimeout,
    isolated_env,
)
from ._http import (
    HttpChannelFailure,
    LoopbackHttpChannel,
    NonLoopbackRefused,
    SseEvent,
)

__all__ = [
    "ChannelClosed",
    "ChannelFailure",
    "FrameReader",
    "FramingError",
    "HttpChannelFailure",
    "LaunchSpec",
    "LoopbackHttpChannel",
    "LostReceipt",
    "Message",
    "NonLoopbackRefused",
    "ProcessChannel",
    "RemoteFailure",
    "RequestTimeout",
    "SseEvent",
    "isolated_env",
]
