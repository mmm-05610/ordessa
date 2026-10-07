"""Pi provider. Import and registration never launch native processes."""
from .lease import LeasedConnection, PiConnectionLeasePort, PiGrant, PiLeaseRefused
from .lifecycle import PiLifecycleRefused
from .provider import PiProviderRefused, PiRuntimeProvider, configuration_ready, termination_ready
from .projection import PiProjectionRefused, PiUnitProjection
from .runtime_channel import (
    ChannelRecord, PiChannelRefused, PiRpcChannelFactory, rpc_argv, verified_private_roots,
)
from .termination import PiTerminationEvidencePort, PiTerminationRefused

__all__ = [
    "PiRuntimeProvider", "PiProviderRefused", "PiLifecycleRefused",
    "PiRpcChannelFactory", "PiChannelRefused", "ChannelRecord", "rpc_argv",
    "verified_private_roots", "PiUnitProjection", "PiProjectionRefused",
    "PiConnectionLeasePort", "PiGrant", "PiLeaseRefused", "LeasedConnection",
    "PiTerminationEvidencePort", "PiTerminationRefused",
    "configuration_ready", "termination_ready",
]

#: Legacy Pi knowledge (profile/continuation/command projection/session scan)
#: stays importable by module (``ordessa_harness_pi.profile`` etc.) but is not
#: re-exported here: the second execution provider retired with the 032 move
#: and only the independent provider stays as a runtime entry.
