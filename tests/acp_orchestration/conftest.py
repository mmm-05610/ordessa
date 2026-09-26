"""Shared harnesses for the ACP orchestration target tests.

Every drive here goes through a production seam: the real `create_app` wire/1
stack over a loopback TestClient, the managed channel over the plugin's real
access entry (`runtime/access-entry.mjs`), the real `NativeHarnessPort` /
`NativeProcessLauncher` for the old-chain port diagnostics, and the controlled
fixture peer.  No real model, no credential, no user Agent.
"""
from __future__ import annotations

import glob as _glob
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "harness"
# The old chain's `worker-entry.mjs` is retired by the plugin (see its
# REMOVALS.md).  The `ports` fixture below still names it, so those
# diagnostics fail honestly at spawn; a retired file must not gate
# collection of the channel targets.
WORKER_ENTRY = PLUGIN / "runtime" / "worker-entry.mjs"
ACCESS_ENTRY = PLUGIN / "runtime" / "access-entry.mjs"
PEER = Path(__file__).with_name("fixtures") / "bidirectional_acp_peer.mjs"
NODE = shutil.which("node")
HELLO = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

assert NODE, "node is required to drive the plugin access entry and the peer fixture"
assert ACCESS_ENTRY.is_file() and PEER.is_file()


# -- peer evidence ----------------------------------------------------------


def peer_events(base: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    directory, stem = os.path.split(base)
    for path in sorted(Path(directory).glob(_glob.escape(stem) + ".*")):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def peer_pids(base: str) -> set[int]:
    directory, stem = os.path.split(base)
    pids = set()
    for path in Path(directory).glob(_glob.escape(stem) + ".*"):
        parts = path.name.split(".")
        pids.add(int(parts[len(stem.split("."))]))
    return pids


def session_new_events(base: str) -> list[dict[str, Any]]:
    return [row for row in peer_events(base) if row.get("event") == "session-new"]


def wait_until(produce, *, timeout: float = 30.0, message: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = produce()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {message}")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def call_in_thread(fn, *args, **kwargs):
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


# -- full Server stack (wire/1, auth, orchestration) -------------------------


_UNSET = object()


@dataclass
class ServerHandle:
    client: Any
    runtime: Any
    token: str
    log_base: str
    _counter: int = 0

    def request_id(self, prefix: str) -> str:
        self._counter += 1
        return f"hd003-{prefix}-{self._counter}"

    def wire(self, method: str, params: dict | None = None, *,
             token: Any = _UNSET, status: int = 200) -> dict:
        response = self.client.post(
            f"/wire/v1/{method}",
            json={"jsonrpc": "2.0", "id": method, "method": method, "params": params or {}},
            headers={"authorization": "Bearer " + (self.token if token is _UNSET else token)},
        )
        assert response.status_code == status, response.text
        return response.json()

    def result(self, method: str, params: dict | None = None, **kwargs) -> dict:
        answer = self.wire(method, params, **kwargs)
        assert "result" in answer, answer
        return answer["result"]

    def native_profile_id(self) -> str:
        identity = self.result("server.hello", HELLO)["nativeExecution"]
        assert identity["mode"] == "native" and identity["harness"] == "pi"
        return identity["profileId"]

    def open_workspace(self, path: Path) -> str:
        opened = self.result("workspaces.open", {
            "requestId": self.request_id("open"),
            "environment": {"kind": "local", "host": None, "user": None},
            "path": str(path),
        })
        return opened["workspace"]["id"]

    def create_and_send(self, workspace_id: str, profile_id: str, text: str) -> dict:
        result = self.result("sessions.createAndSend", {
            "requestId": self.request_id("send"), "workspaceId": workspace_id,
            "profileId": profile_id,
            "message": {"text": text, "attachments": []},
            "overrides": [],
        })
        assert result["outcome"] == "accepted", result
        return result

    def send(self, session_id: str, text: str) -> dict:
        result = self.result("sessions.send", {
            "requestId": self.request_id("send"), "sessionId": session_id,
            "message": {"text": text, "attachments": []},
            "overrides": [],
        })
        assert result["outcome"] == "accepted", result
        return result

    def session_row(self, session_id: str) -> dict:
        response = self.client.get(
            f"/api/v1/sessions/{session_id}",
            headers={"authorization": "Bearer " + self.token})
        assert response.status_code == 200, response.text
        return response.json()

    def settled(self, session_id: str, turn_count: int, *, timeout: float = 40.0) -> dict:
        def produce():
            row = self.session_row(session_id)
            if len(row["turns"]) >= turn_count and row["turns"][-1]["state"] in {
                "completed", "failed", "cancelled", "unknown",
            }:
                return row
            return None
        return wait_until(produce, timeout=timeout, message=f"turn {turn_count} to settle")

    def frames(self, session_id: str) -> list[dict]:
        history = self.result("history.snapshot", {"sessionId": session_id})
        return [frame["event"] for frame in history["frames"]]


@pytest.fixture
def server(tmp_path, monkeypatch) -> ServerHandle:
    from ordessa_server_compat.composition import build_runtime_from_native_adapter
    from ordessa_server.transport.http.app import create_app
    from fastapi.testclient import TestClient

    log_base = str(tmp_path / "peer-log")
    monkeypatch.setenv("HD003_LOG", log_base)
    runtime = build_runtime_from_native_adapter(
        tmp_path / "data", plugin_root=PLUGIN, harness_id="pi",
        adapter_command=NODE, adapter_args=(str(PEER),), native_continuation=True,
    )
    client = TestClient(create_app(runtime), base_url="http://127.0.0.1")
    with client:  # runs the real lifespan: runtime.start() / runtime.stop()
        yield ServerHandle(client=client, runtime=runtime, token=runtime.token,
                           log_base=log_base)


# -- direct production port (channel/passthrough level) ----------------------


@dataclass
class PortHandle:
    port: Any
    events: list = field(default_factory=list)
    log_base: str = ""

    def open(self, execution_id: str = "execution-1") -> str:
        return self.port.open_execution(execution_id)

    def event_for(self, kind: str, payload_contains: Any = None):
        def produce():
            for _, event_kind, payload in self.events:
                if event_kind != kind:
                    continue
                if payload_contains is None or _contains(payload, payload_contains):
                    return (event_kind, payload)
            return None
        return wait_until(produce, timeout=30, message=f"event {kind}")

    def kinds(self) -> list[str]:
        return [kind for _, kind, _ in self.events]


def _contains(payload, wanted) -> bool:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if isinstance(wanted, str):
        return wanted in text
    return all(frag in text for frag in wanted)


@pytest.fixture
def ports(tmp_path, monkeypatch):
    """Factory for real NativeHarnessPort instances over the plugin worker entry."""
    from ordessa_server_compat.execution.sidecar import NativeHarnessPort, NativeProcessLauncher

    log_base = str(tmp_path / "peer-log")
    monkeypatch.setenv("HD003_LOG", log_base)
    created: list[PortHandle] = []

    def make(project: Path, *, environment: dict[str, str] | None = None) -> PortHandle:
        from ordessa_server_compat.execution import HarnessRegistry
        from ordessa_server_compat.execution import HarnessDescriptor
        env = dict(os.environ) if environment is None else dict(environment)
        env.pop("AGENTBOX_SIDECAR_ISOLATED", None)
        env["HD003_LOG"] = log_base
        # Mirror the production native bootstrap's declared upper bound.
        registry = HarnessRegistry()
        registry.register(HarnessDescriptor(
            "pi", capability_claims={"native_continuation": True}))
        handle: PortHandle = PortHandle(port=None, events=[], log_base=log_base)  # type: ignore[arg-type]
        port = NativeHarnessPort(
            NativeProcessLauncher((NODE, str(WORKER_ENTRY), "--native"), cwd=str(project)),
            environment=env, profile="pi",
            adapter={"command": NODE, "args": [str(PEER)]},
            directory=str(project),
            state_directory=str(tmp_path / f"bridge-state-{len(created)}"),
            declared_capabilities=registry.canonical_claims("pi"),
            on_event=lambda execution_id, kind, payload: handle.events.append(
                (execution_id, kind, payload)),
        )
        handle.port = port
        created.append(handle)
        return handle

    yield make
    for handle in created:
        try:
            handle.port.stop()
        except BaseException:  # noqa: BLE001 - cleanup must not mask the result
            pass


@pytest.fixture
def project(tmp_path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path
