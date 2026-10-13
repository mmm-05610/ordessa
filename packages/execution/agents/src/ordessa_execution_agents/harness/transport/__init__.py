"""Protocol-neutral Harness-owned framing and process transport."""
from .channel import (
 ChannelClosed,LaunchSpec,LostReceipt,
 ProcessChannel,LeaseBoundChannel,RemoteFailure,RequestTimeout,isolated_env,
)
from ordessa_infrastructure.process.framing import (
 ChannelFailure,FrameReader,FramingError,Message,
)
from .ndjson import NDJSONTransport,TransportClosed,WriterLease,WriterLeaseRefused
from .prepared import PreparedFrame, PreparedFramePool, PreparedFrameRefused, native_frame_bytes
from .effect_guard import EffectWriteGuard, EffectWriteRefused
