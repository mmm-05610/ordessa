from datetime import datetime, timezone
from openshell._proto import openshell_pb2 as pb
from ordessa_environments import BackendObservation, Capabilities
from ordessa_environments import PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, STREAMING_STDERR_CAPABILITY, FILE_AREA_CAPABILITY


def observation(sandbox, *, files_verified=False):
    state = {pb.SANDBOX_PHASE_READY:'running', pb.SANDBOX_PHASE_STOPPED:'stopped',
        pb.SANDBOX_PHASE_COMPLETED:'stopped', pb.SANDBOX_PHASE_ERROR:'error'}.get(sandbox.status.phase, 'pending')
    provides = {PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, STREAMING_STDERR_CAPABILITY}
    if files_verified:
        provides.add(FILE_AREA_CAPABILITY)
    capabilities = Capabilities('openshell', frozenset(provides), {
        'backendVersion':'0.1.3', 'perProcessStop':False, 'processReconnect':False,
        'restartCount':sandbox.status.restart_count,
        'mainProcessStartedAtMs':sandbox.status.main_process_started_at_ms,
        'policyVersion':sandbox.status.current_policy_version,
        'useIsIsolationBoundary':False,
    })
    runtime_identity = None
    if sandbox.status.main_process_started_at_ms is not None:
        runtime_identity = str(sandbox.status.restart_count) + '/' + str(sandbox.status.main_process_started_at_ms)
    return BackendObservation(sandbox.id, state, capabilities, datetime.now(timezone.utc).isoformat(), runtime_identity)
