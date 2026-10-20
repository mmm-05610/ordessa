"""Owner surface for the runtime-composition values and v1 ports.

``ordessa_environments`` owns the composition inputs, attempt facts, provider
ports and protocol failures that Units orchestrate; this module is the surface
consumers import. The v1 provider seam is :class:`RuntimeHost` plus
:class:`Sandbox` (with ``wrap``/``launch``/``cleanup``).
"""
from ..definitions.composition_values import (
    CONTRACT_ID,
    CompositionAttemptRecord,
    CompositionError,
    CompositionErrorCode,
    CompositionPreflightReceipt,
    CompositionRejected,
    MountPlan,
    NativeCorrelationSet,
    PreparedMountSource,
    RuntimeBinding,
    RuntimeBundle,
    RuntimePreparationRejected,
    StartAmbiguous,
    attempt_key,
)
from ..definitions.contracts import ProcessHandle
from ..definitions.runtime_ports import (
    COMPENSATION_CAPABILITY,
    TERMINATE_TRANSPORT_KIND,
    CommandInput,
    HostTransportInput,
    MountPlanInput,
    RuntimeBundleInput,
    RuntimeHost,
    Sandbox,
    TransportOperationInput,
)
from ..definitions.runtime_resources import (
    CapabilitySet,
    CapabilityStatus,
    IsolatedProcessSpec,
    ProjectionRejected,
    RuntimeHostRef,
    SandboxAmbiguous,
    SandboxError,
    SandboxRef,
    SandboxUnavailable,
    SandboxUnsupported,
    guest_path,
)

__all__ = [
    # Composition values and attempt facts.
    "CONTRACT_ID",
    "CompositionAttemptRecord",
    "CompositionError",
    "CompositionErrorCode",
    "CompositionPreflightReceipt",
    "CompositionRejected",
    "MountPlan",
    "NativeCorrelationSet",
    "PreparedMountSource",
    "RuntimeBinding",
    "RuntimeBundle",
    "RuntimePreparationRejected",
    "StartAmbiguous",
    "attempt_key",
    # v1 provider protocols and their cross-owner read-only inputs.
    "RuntimeHost",
    "Sandbox",
    "CommandInput",
    "MountPlanInput",
    "RuntimeBundleInput",
    "HostTransportInput",
    "TransportOperationInput",
    "COMPENSATION_CAPABILITY",
    "TERMINATE_TRANSPORT_KIND",
    # Provider-neutral runtime identity and result resources.
    "ProcessHandle",
    "IsolatedProcessSpec",
    "RuntimeHostRef",
    "SandboxRef",
    "CapabilitySet",
    "CapabilityStatus",
    "guest_path",
    "ProjectionRejected",
    "SandboxError",
    "SandboxUnsupported",
    "SandboxUnavailable",
    "SandboxAmbiguous",
]
