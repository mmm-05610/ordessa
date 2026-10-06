"""Codex-only provider: importing this package starts no native process.

Assembly remains explicit: the deployment composes
:class:`CodexRuntimeProvider` with its real ports
(:class:`CodexUnitProjection`, :class:`CodexAppServerChannelFactory`,
:class:`CodexConnectionLeasePort`). Only an authorized, effect-verified start
opens a native process; reads never consume an invocation.
"""
from .provider import (CodexRuntimeProvider, CodexProviderRefused, CodexCapabilityUnsupported,
                       termination_ready)
from .projection import CodexUnitProjection, CodexProjectionRefused
from .runtime_channel import (
    CodexAppServerChannelFactory, CodexChannelRefused, ChannelRecord, app_server_argv,
    verified_private_roots, PRIVATE_ROOT_FIELDS,
)
from .termination import CodexTerminationEvidencePort, CodexTerminationRefused
from .lease import CodexConnectionLeasePort, CodexLeaseRefused, CodexGrant, LeasedConnection

__all__ = [
    "CodexRuntimeProvider", "CodexProviderRefused", "CodexCapabilityUnsupported",
    "CodexUnitProjection", "CodexProjectionRefused",
    "CodexAppServerChannelFactory", "CodexChannelRefused", "ChannelRecord", "app_server_argv",
    "verified_private_roots", "PRIVATE_ROOT_FIELDS",
    "CodexTerminationEvidencePort", "CodexTerminationRefused", "termination_ready",
    "CodexConnectionLeasePort", "CodexLeaseRefused", "CodexGrant", "LeasedConnection",
]
