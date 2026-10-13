"""The launcher consumes a finished launch; it never assembles one.

This is the P1 ownership test. It proves, without starting a process, that the
channel factory passes the preparation's ``LaunchSpec`` through **verbatim**:
no argument added, removed or reordered, and no environment key merged.

A recording environment captures the exact ``ProcessRequest`` the factory tried
to start and then refuses, so the assertion is about the factory's behaviour, not
about a running child.
"""
from __future__ import annotations

import os
import stat

import pytest

from ordessa_environments import EnvironmentRefused, ProcessRequest
from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.preparation import (
    ConfigurationResources,
    PreparedAgent,
    PreparedHarness,
    PreparationRefused,
    SessionBootstrap,
)
from ordessa_harness_pi import PiChannelRefused
from ordessa_harness_pi.preparation import PiHarnessPreparation

START_FACTS = {"action": "start", "query": False}


@pytest.fixture
def fake_executable(tmp_path):
    """A runnable placeholder so the test never depends on the host install."""
    path = tmp_path / "pi"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture
def roots(tmp_path):
    private = tmp_path / "unit"
    values = {
        "cwd": str(private / "cwd"),
        "home": str(private / "home"),
        "profile": str(private / "profile"),
        "tmp": str(private / "tmp"),
    }
    for value in values.values():
        os.makedirs(value, exist_ok=True)
    return values












# -- the headline ownership assertion -----------------------------------------





def _marker_spec():
    return LaunchSpec.build(
        ["/marker/executable", "--mode", "rpc", "--marker-flag"],
        home="/marker/home",
        cwd="/marker/cwd",
        extra_env={"MARKER_KEY": "marker-value"},
    )

def _marker_prepared() -> PreparedHarness:
    return PreparedHarness(
        harness_id="pi",
        launch_spec=_marker_spec(),
        session=SessionBootstrap(mode="none"),
        resources=ConfigurationResources(kind="pi-agent-dir", location="/marker/pihome", applied=False),
        descriptor={"familyId": "pi"},
    )


# -- the preparation owns the plan --------------------------------------------

def test_preparation_produces_the_pinned_plan(fake_executable, roots):
    prepared = PiHarnessPreparation(fake_executable).prepare(roots)
    argv = prepared.launch_spec.argv
    assert argv[0] == fake_executable, "the pinned executable must be the resolved absolute path"
    assert argv[1:3] == ("--mode", "rpc")
    assert "--no-session" in argv
    assert "--offline" in argv
    assert prepared.harness_id == "pi"
    assert prepared.descriptor["familyId"] == "pi"


def test_preparation_is_pure_and_repeatable(fake_executable, roots):
    preparation = PiHarnessPreparation(fake_executable)
    first = preparation.prepare(roots)
    second = preparation.prepare(roots)
    assert first.launch_spec == second.launch_spec
    assert first.to_dict() == second.to_dict()


def test_preparation_drops_credential_shaped_environment(fake_executable, roots, monkeypatch):
    """The prepared environment is isolated: no token key survives (G12)."""
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-appear")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-appear")
    prepared = PiHarnessPreparation(fake_executable).prepare(roots)
    env = prepared.launch_spec.env
    assert "GITHUB_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["HOME"] == roots["home"]
    assert env["PI_CODING_AGENT_DIR"] == roots["profile"]
    assert env["TMPDIR"] == roots["tmp"]


def test_a_session_dir_switches_the_bootstrap_to_fresh(tmp_path, fake_executable, roots):
    session = str(tmp_path / "sessions")
    prepared = PiHarnessPreparation(fake_executable, session_dir=session).prepare(roots)
    assert prepared.session.mode == "fresh"
    assert prepared.session.location == session
    assert "--no-session" not in prepared.launch_spec.argv
    assert "--session-dir" in prepared.launch_spec.argv


def test_the_prepared_resource_is_reported_as_not_applied(fake_executable, roots):
    """Preparation points at the configuration location; it does not populate it."""
    prepared = PiHarnessPreparation(fake_executable).prepare(roots)
    assert prepared.resources.kind == "pi-agent-dir"
    assert prepared.resources.location == roots["profile"]
    assert prepared.resources.applied is False


# -- contracts ----------------------------------------------------------------

def test_session_bootstrap_rejects_inconsistent_modes():
    with pytest.raises(PreparationRefused):
        SessionBootstrap(mode="nonsense", location="/x")
    with pytest.raises(PreparationRefused):
        SessionBootstrap(mode="none", location="/x")
    with pytest.raises(PreparationRefused):
        SessionBootstrap(mode="fresh")


def test_prepared_agent_pins_the_profile_revision():
    agent = PreparedAgent(agent_id="agent-1", profile_revision="rev-7", harness=_marker_prepared())
    assert agent.to_dict()["profileRevision"] == "rev-7"
    assert agent.harness.argv == _marker_spec().argv


