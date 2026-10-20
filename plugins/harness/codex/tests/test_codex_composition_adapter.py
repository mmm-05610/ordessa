"""Codex guest-layout declaration (032 §5d-2).

Retired with the second coordinator: the companion test
``test_fake_composition_is_the_only_start_edge_and_new_execution_resumes``
covered ``CodexComposition.compose`` plus the fake composition coordinator from
``pacthold_runtime_compat.runtime_composition`` (host/sandbox/terminal fakes and
``TargetCreationSentinel``). That whole assembly/coordination path is deleted —
no second coordinator exists and no successor seam is kept — so the test went
with its subject rather than being re-pointed at nothing. The declaration half
(the projector command) is still brand knowledge and stays under test here.
"""
from types import SimpleNamespace

from ordessa_execution_agents.harness.definitions.command_projection import HarnessCommandSpec

from ordessa_harness_codex.composition import command_from_plan


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
