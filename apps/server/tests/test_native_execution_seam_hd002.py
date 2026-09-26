"""Native composition guards; these tests never spawn an Agent."""

from pathlib import Path

import pytest

from ordessa_server_compat.execution.sidecar import NativeHarnessPort, NativeProcessLauncher
from ordessa_server_compat.execution.sidecar_backend import (
    CapabilityGateRefusal, NativeProjectRefusal, NativeSessionUnavailable,
    SidecarExecutionBackend,
    _capability_gate, _resumable,
)


def _port(project: Path) -> NativeHarnessPort:
    return NativeHarnessPort(
        NativeProcessLauncher(["/not-launched"], cwd=str(project)),
        environment={}, directory=str(project), profile="pi",
    )


def test_native_gate_rechecks_selected_project_before_spawn(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    port = _port(project)
    _capability_gate(port, "turn")
    project.rmdir()
    with pytest.raises(CapabilityGateRefusal, match="selected project") as refused:
        _capability_gate(port, "turn")
    assert refused.value.code == "LOCAL_PATH_MISSING"


def test_native_gate_rejects_isolated_material_and_wrong_launcher(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    port = _port(project)
    port.capability_binding = "injected-room"
    with pytest.raises(CapabilityGateRefusal, match="isolated material"):
        _capability_gate(port, "turn")
    port.capability_binding = None
    port.launcher = object()
    with pytest.raises(CapabilityGateRefusal, match="native launcher"):
        _capability_gate(port, "turn")


def test_native_capture_records_id_without_home_audit(tmp_path):
    class Envelope:
        def __init__(self):
            self.ops = []

        def request(self, request, **_kwargs):
            self.ops.append(request["op"])
            return {}

        def audit_state(self):
            raise AssertionError("native home must not be inspected")

    port = _port(tmp_path)
    envelope = Envelope()
    port._sessions["turn"] = envelope
    port._effective_supported = lambda *_args: True
    audit, supported = port.capture_execution("turn")
    assert envelope.ops == []  # ending a Turn must not close its ACP session
    assert audit == {
        "nativePlatform": "local", "homeLocator": "agent-native",
        "audited": False, "truncated": False, "files": [],
    }
    assert _resumable(port, supported, audit) is True


def test_native_second_turn_reuses_live_acp_channel(tmp_path):
    class Envelope:
        def __init__(self):
            import threading
            self._closed = threading.Event()

        @property
        def closed(self):
            return self._closed.is_set()

        def close(self):
            self._closed.set()

    port = _port(tmp_path)
    envelope = Envelope()
    port._live_envelope = envelope
    port._live_native_id = "opaque-native-id"
    port._sessions["first"] = envelope
    port._native_sessions["first"] = "opaque-native-id"
    port.close_execution("first")
    assert not envelope.closed
    assert port.open_execution("second") == "opaque-native-id"
    assert port._sessions["second"] is envelope
    port.close_execution("second")
    assert not envelope.closed
    port.stop()
    assert envelope.closed


def test_nonresumable_native_checkpoint_never_opens_a_new_session(tmp_path):
    class Objects:
        def read(self, _digest):
            return b'{"resumable":false}'

    port = _port(tmp_path)
    backend = SidecarExecutionBackend(
        None, Objects(), None, port_factory=lambda _context, _on_event: port,
    )
    backend._turn_by_core["core"] = "turn"
    backend._contexts["turn"] = {
        "session_id": "server-session", "checkpoint_object_digest": "digest",
        "checkpoint_native_id": "old-process-local-id",
    }
    with pytest.raises(NativeSessionUnavailable):
        backend._start_run("core", "dispatch", None, None, None)
    assert not port._sessions


def test_live_native_session_refuses_project_retargeting(tmp_path):
    port = _port(tmp_path)
    backend = SidecarExecutionBackend(
        None, None, None, port_factory=lambda _context, _on_event: port,
    )
    backend._native_ports["server-session"] = port
    backend._turn_by_core["core"] = "turn"
    backend._contexts["turn"] = {
        "session_id": "server-session", "normalized_path": str(tmp_path / "different"),
    }
    with pytest.raises(NativeProjectRefusal) as refused:
        backend._start_run("core", "dispatch", None, None, None)
    assert refused.value.code == "NATIVE_PROJECT_CHANGED"
