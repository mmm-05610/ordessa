from pathlib import Path

from types import SimpleNamespace
from pacthold_runtime_compat.resource_contracts import (
    AgentBoxProfileV1,
    PromptFragmentV1,
    WorkspaceV1,
)
from pacthold.work_core import ExecutionStartRequest, Ref, RefType, ResolvedExecutionInput
from pacthold.work_core.projection import Outcome, Phase
from pacthold_runtime_compat.runtime_composition import RuntimeBinding, RuntimeHostRef, SandboxRef, TerminalRunHandle, TerminalSessionRef
from ordessa_harness.codex.app_server import provider as module


class _Adapter:
    def __init__(self, binary: str):
        # The projector declares the executable as a dispatch-local source, so
        # the launch plan must carry a real host file.
        self.binary = binary

    def plan_app_server(self, **kwargs):
        return SimpleNamespace(argv=(self.binary, "app-server", "--stdio"), env={}, cwd=kwargs["workspace"].path)

    def cleanup(self, execution_id):
        pass


class _Process:
    returncode = None

    def poll(self):
        return self.returncode


class _Client:
    def __init__(self, plan, events_path):
        self.events_path = events_path
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text('{"method":"turn/completed"}\n', encoding="utf-8")
        self.process = _Process()
        self.calls = []

    def request(self, method, params, timeout=60):
        self.calls.append((method, params))
        if method == "initialize":
            return {"userAgent": "test"}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": f"turn-{len([c for c in self.calls if c[0] == 'turn/start'])}"}}
        raise AssertionError(method)

    def notify(self, method, params):
        self.calls.append((method, params))

    def wait_turn_completed(self, turn_id, timeout=300):
        return {"threadId": "thread-1", "turn": {"id": turn_id, "status": "completed"}}

    def close(self):
        self.process.returncode = 0


class _Coordinator:
    def start(self, binding, command, *, execution_id, dispatch_id):
        assert binding.runtime_host_ref and binding.sandbox_ref and binding.terminal_session_ref
        # No capability sniffing: the guest argv crosses the boundary verbatim.
        assert command.argv == ("/runtime/bin/codex", "app-server", "--stdio")
        return TerminalRunHandle("attempt:" + dispatch_id, "fake-native", "running", "direct:fixture")


def _binding():
    affinity = "fixture:local"
    return RuntimeBinding(RuntimeHostRef("host", "host", "host-digest", affinity), SandboxRef("sandbox", "safe", "policy-digest", affinity), TerminalSessionRef("direct-stdio", "direct-stdio", "terminal-digest", affinity))


def test_turn_completion_does_not_terminal_until_explicit_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "CodexAppServerClient", _Client)
    codex_binary = tmp_path / "codex"
    codex_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_binary.chmod(0o755)
    provider = module.CodexInteractiveExecutionProvider(
        tmp_path / "evidence", launch_adapter=_Adapter(str(codex_binary)), coordinator=_Coordinator(), runtime_binding=_binding()
    )
    request = ExecutionStartRequest(
        "exec-1",
        "dispatch-1",
        "digest-1",
        (
            ResolvedExecutionInput(WorkspaceV1.contract_id, Ref(RefType.WORKSPACE, "test", "workspace"), WorkspaceV1(tmp_path, "git:abc")),
            ResolvedExecutionInput(PromptFragmentV1.contract_id, Ref(RefType.ARTIFACT, "test", "prompt"), PromptFragmentV1("Responsibility", "make the change", "sha256:prompt")),
            ResolvedExecutionInput(AgentBoxProfileV1.contract_id, Ref(RefType.ARTIFACT, "test", "profile"), AgentBoxProfileV1("codex-main", "codex", "sha256:profile")),
        ),
    )

    handle = provider.start(request)
    calls = handle.client.calls
    initialize = next(params for method, params in calls if method == "initialize")
    assert initialize["capabilities"] == {}
    assert "experimentalApi" not in initialize["capabilities"]
    thread_start = next(params for method, params in calls if method == "thread/start")
    assert thread_start["approvalPolicy"] == "never"
    assert thread_start["cwd"] == "/workspace"
    assert thread_start["sandbox"] == "danger-full-access"
    assert "runtimeWorkspaceRoots" not in thread_start
    provider.wait_current_turn(handle)
    active = provider.observe(handle)
    assert active.projection.phase is Phase.ACTIVE

    terminal = provider.finish(handle)
    assert terminal.projection.phase is Phase.TERMINAL
    assert terminal.projection.outcome is Outcome.SUCCEEDED
    assert terminal.native_refs[0].native_id == "thread-1"
    assert terminal.output_refs[0].metadata["kind"] == "app-server-events"
    turn_start = next(params for method, params in calls if method == "turn/start")
    assert turn_start["approvalPolicy"] == "never"
    assert "runtimeWorkspaceRoots" not in turn_start
    assert turn_start["sandboxPolicy"] == {
        "type": "externalSandbox",
        "networkAccess": "enabled",
    }
    assert turn_start["cwd"] == "/workspace"


def test_codex_launch_has_no_mcp_feature_hack(tmp_path):
    codex_binary = tmp_path / "codex"
    codex_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_binary.chmod(0o755)
    plan = _Adapter(str(codex_binary)).plan_app_server(workspace=SimpleNamespace(path=tmp_path / "workspace"))
    assert plan.argv == (str(codex_binary), "app-server", "--stdio")


def test_failed_file_change_cannot_be_reported_as_success():
    handle = SimpleNamespace(
        turn_ids=["turn-1"],
        turn_results={"turn-1": {"turn": {"status": "completed"}}},
        client=SimpleNamespace(file_change_statuses=("failed",)),
    )
    assert not module.CodexInteractiveExecutionProvider._turn_succeeded(handle)
