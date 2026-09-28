from types import SimpleNamespace

from pacthold_runtime_compat.runtime_composition import HarnessCommandSpec
from pacthold_runtime_compat.runtime_composition import (
    FakeCompositionCoordinator, FakeHost, FakeSandbox, FakeTerminal,
    RuntimeBinding, RuntimeHostRef, SandboxRef, TargetCreationSentinel,
    TerminalSessionRef,
)
from ordessa_harness.codex.composition import command_from_plan, compose


def test_codex_harness_only_generates_command_and_execution_overlay_token(tmp_path):
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = command_from_plan(
        SimpleNamespace(
            argv=(str(executable), "app-server", "--stdio"),
            env={"CODEX_HOME": "/private/overlay", "LANG": "C.UTF-8"},
            cwd=workspace,
        ),
        execution_id="execution-1",
        io_mode="stdio",
    )
    assert isinstance(command, HarnessCommandSpec)
    assert command.cwd_token == "/workspace"
    assert command.environment["CODEX_HOME"] == "/runtime/home"
    assert "/private/overlay" not in repr(command)
    # The Codex projector owns the guest layout declaration, including the
    # workspace source; the assembler never invents it.
    workspace_source = next(s for s in command.runtime_sources if s.kind == "workspace")
    assert workspace_source.guest_target == "/workspace"
    assert workspace_source.access == "rw"
    assert command.projector_id == "codex"


def test_fake_composition_is_the_only_start_edge_and_new_execution_resumes():
    affinity = "fake:linux:amd64"
    host_ref = RuntimeHostRef("fake-host", "host", "host-digest", affinity)
    sandbox_ref = SandboxRef("fake-sandbox", "sandbox", "policy-digest", affinity)
    terminal_ref = TerminalSessionRef("direct-stdio", "stdio", "terminal-digest", affinity)
    sentinel = TargetCreationSentinel()
    coordinator = FakeCompositionCoordinator(
        FakeHost(host_ref, sentinel), FakeSandbox(sandbox_ref),
        FakeTerminal(terminal_ref, None),
    )
    # The Harness may build a command without invoking the Coordinator.
    command = HarnessCommandSpec(("codex", "resume", "thread-old"), "workspace:digest")
    assert sentinel.count == 0
    first = compose(coordinator, RuntimeBinding(host_ref, sandbox_ref, terminal_ref),
                    command, execution_id="execution-new", dispatch_id="dispatch-new")
    assert sentinel.count == 1
    # A continuation is a new Core Execution and therefore a new composition
    # attempt; the terminal is never resumed by the Harness itself.
    second = compose(coordinator, RuntimeBinding(host_ref, sandbox_ref, terminal_ref),
                     command, execution_id="execution-newer", dispatch_id="dispatch-newer")
    assert first.attempt_key != second.attempt_key
    assert sentinel.count == 2
