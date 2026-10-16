"""dsh-only provider: importing this package starts no native process.

Assembly remains explicit: the deployment composes
:class:`DshRuntimeProvider` with its real ports
(:class:`DshUnitProjection`, :class:`DshAcpChannelFactory`,
:class:`DshConnectionLeasePort`). Only an authorized, effect-verified start
opens a native process; reads never consume an invocation. The production
``implementation_digest`` is injected by the deployment fingerprint gate —
never generated here — and until that gate is backfilled this provider must
not appear in any production assembly.
"""
from .provider import (DshRuntimeProvider, DshProviderRefused, DshCapabilityUnsupported,
                       termination_ready)
from .projection import DshUnitProjection, DshProjectionRefused
from .runtime_channel import (
    DshAcpChannelFactory, DshChannelRefused, ChannelRecord, dsh_acp_argv,
    verified_private_roots, PRIVATE_ROOT_FIELDS,
)
from .termination import DshTerminationEvidencePort, DshTerminationRefused
from .lease import DshConnectionLeasePort, DshLeaseRefused, DshGrant, LeasedConnection
from .client import DshAcpClient, DshRpcError, PromptTurnFailed, PROTOCOL, describe

__all__ = [
    "DshRuntimeProvider", "DshProviderRefused", "DshCapabilityUnsupported",
    "DshUnitProjection", "DshProjectionRefused",
    "DshAcpChannelFactory", "DshChannelRefused", "ChannelRecord", "dsh_acp_argv",
    "verified_private_roots", "PRIVATE_ROOT_FIELDS",
    "DshTerminationEvidencePort", "DshTerminationRefused", "termination_ready",
    "DshConnectionLeasePort", "DshLeaseRefused", "DshGrant", "LeasedConnection",
    "DshAcpClient", "DshRpcError", "PromptTurnFailed", "PROTOCOL", "describe",
]
