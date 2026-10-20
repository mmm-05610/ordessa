from datetime import datetime, timezone
from openshell._proto import openshell_pb2 as pb
from ordessa_environments import (
    BackendObservation, CapabilityReport, CapabilityStatus,
    PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, STREAMING_STDERR_CAPABILITY,
    FILE_AREA_CAPABILITY, TERMINAL_CAPABILITY,
)


def observation(sandbox, *, files_verified=False):
    state = {pb.SANDBOX_PHASE_READY:'running', pb.SANDBOX_PHASE_STOPPED:'stopped',
        pb.SANDBOX_PHASE_COMPLETED:'stopped', pb.SANDBOX_PHASE_ERROR:'error'}.get(sandbox.status.phase, 'pending')
    # Facts only: no per-exec kill or reconnect claim, and the file area is
    # conditional until the helper probe actually verifies it. A sandbox has no
    # pty terminal. Outbound network is not claimed: it depends on the admitted
    # policy, which this mapping does not prove.
    values = {
        PROCESS_CAPABILITY: CapabilityStatus.SUPPORTED,
        BYTE_CHANNEL_CAPABILITY: CapabilityStatus.SUPPORTED,
        STREAMING_STDERR_CAPABILITY: CapabilityStatus.SUPPORTED,
        FILE_AREA_CAPABILITY: (
            CapabilityStatus.SUPPORTED if files_verified else CapabilityStatus.CONDITIONAL
        ),
        TERMINAL_CAPABILITY: CapabilityStatus.UNSUPPORTED,
    }
    capabilities = CapabilityReport(values, 'openshell', 'provider_self_report', '', {
        'backendVersion':'0.1.3', 'perProcessStop':'false', 'processReconnect':'false',
        'restartCount':str(sandbox.status.restart_count),
        'mainProcessStartedAtMs':str(sandbox.status.main_process_started_at_ms),
        'policyVersion':str(sandbox.status.current_policy_version),
        'useIsIsolationBoundary':'false',
    })
    runtime_identity = None
    if sandbox.status.main_process_started_at_ms is not None:
        runtime_identity = str(sandbox.status.restart_count) + '/' + str(sandbox.status.main_process_started_at_ms)
    return BackendObservation(sandbox.id, state, capabilities, datetime.now(timezone.utc).isoformat(),
        runtime_identity, endpoint_kind='outbound')
