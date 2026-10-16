"""grok-build-only provider: importing this package starts no native process.

Assembly remains explicit: the deployment composes
:class:`GrokBuildRuntimeProvider` with its real ports
(:class:`GrokBuildUnitProjection`, :class:`GrokBuildAcpChannelFactory`,
:class:`GrokBuildConnectionLeasePort`). Only an authorized, effect-verified
start opens a native process; reads never consume an invocation. The production
``implementation_digest`` is injected by the deployment fingerprint gate —
never generated here — and until that gate is backfilled this provider must
not appear in any production assembly.
"""
from .provider import (GrokBuildRuntimeProvider, GrokBuildProviderRefused, GrokBuildCapabilityUnsupported,
                       termination_ready)
from .projection import GrokBuildUnitProjection, GrokBuildProjectionRefused
from .runtime_channel import (
    GrokBuildAcpChannelFactory, GrokBuildChannelRefused, ChannelRecord, grok_acp_argv,
    verified_private_roots, PRIVATE_ROOT_FIELDS,
)
from .termination import GrokBuildTerminationEvidencePort, GrokBuildTerminationRefused
from .lease import GrokBuildConnectionLeasePort, GrokBuildLeaseRefused, GrokBuildGrant, LeasedConnection
from .client import (GrokBuildAcpClient, GrokBuildRpcError, GrokBuildAuthenticationRefused,
                     PromptTurnFailed, PROTOCOL, describe)

__all__ = [
    "GrokBuildRuntimeProvider", "GrokBuildProviderRefused", "GrokBuildCapabilityUnsupported",
    "GrokBuildUnitProjection", "GrokBuildProjectionRefused",
    "GrokBuildAcpChannelFactory", "GrokBuildChannelRefused", "ChannelRecord", "grok_acp_argv",
    "verified_private_roots", "PRIVATE_ROOT_FIELDS",
    "GrokBuildTerminationEvidencePort", "GrokBuildTerminationRefused", "termination_ready",
    "GrokBuildConnectionLeasePort", "GrokBuildLeaseRefused", "GrokBuildGrant", "LeasedConnection",
    "GrokBuildAcpClient", "GrokBuildRpcError", "GrokBuildAuthenticationRefused",
    "PromptTurnFailed", "PROTOCOL", "describe",
]
