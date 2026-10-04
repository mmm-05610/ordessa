"""Consumer-side native protocol clients for harness families.

Family clients live as sibling modules and speak their family's documented
native channel (JSON-RPC / JSONL / HTTP) through the frozen transport seam in
``_transport``. They are consumers: they never import harness internals, never
own instance or task state, and never publish runtime readiness
(specs/030-native-harness-expansion/design.md §3).

This package deliberately keeps no family registry: the authoritative family
catalog is published by the Harness side
(``ordessa_harness_api.command_discovery``) and mirrored at build time.
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
