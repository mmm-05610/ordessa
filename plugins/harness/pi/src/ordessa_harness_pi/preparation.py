"""The pi harness's single launch-plan producer.

Every brand-specific launch decision lives here: the argv flags, the isolated
environment keys and the session bootstrap. The channel factory consumes the
finished :class:`~ordessa_execution_agents.preparation.PreparedHarness` and
assembles nothing itself — it never adds, removes or reorders an argument and
never merges another environment key.

Pure with respect to effects: nothing here starts a process, writes a record or
touches configuration content. The unit-private directories are still
provisioned by the launcher, and :attr:`ConfigurationResources.applied` records
that honestly (``False`` — preparation points at the location, it does not
populate it).
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.preparation import (
    ConfigurationResources,
    PreparedHarness,
    SessionBootstrap,
)
from ordessa_harness_pi.client import FAMILY_ID, describe, rpc_launch_argv
from ordessa_harness_pi.launch_validation import (
    PiChannelRefused,
    verified_executable,
    verified_unit_private_roots,
)

#: The unit-private Pi agent directory the launch reads its configuration from.
AGENT_DIR_KEY = "PI_CODING_AGENT_DIR"

#: Re-asserted in the child environment so a launch can never reach a network
#: model service.
OFFLINE_KEY = "PI_OFFLINE"

#: Configuration resource kind reported by this harness.
RESOURCE_KIND = "pi-agent-dir"


class PiHarnessPreparation:
    """The pi family's ``HarnessPreparation`` implementation."""

    harness_id = FAMILY_ID

    def __init__(
        self,
        executable: str,
        *,
        session_dir: str | None = None,
        offline: bool = True,
        minimal: bool = True,
    ):
        self.executable = verified_executable(executable)
        if session_dir is not None and (not isinstance(session_dir, str) or not session_dir):
            raise PiChannelRefused("session directory must be a non-empty path")
        if type(offline) is not bool or type(minimal) is not bool:
            raise PiChannelRefused("offline and minimal must be explicit booleans")
        self.session_dir = session_dir
        self.offline = offline
        self.minimal = minimal

    def prepare(self, private_root_facts: Mapping[str, str]) -> PreparedHarness:
        """Produce the one finished launch plan for these unit-private roots."""
        roots = verified_unit_private_roots(private_root_facts)
        plan = rpc_launch_argv(
            session_dir=self.session_dir, offline=self.offline, minimal=self.minimal
        )
        spec = LaunchSpec.build(
            [self.executable, *plan[1:]],
            home=roots["home"],
            cwd=roots["cwd"],
            extra_env={AGENT_DIR_KEY: roots["profile"], OFFLINE_KEY: "1", "TMPDIR": roots["tmp"]},
        )
        session = (
            SessionBootstrap(mode="none")
            if self.session_dir is None
            else SessionBootstrap(mode="fresh", location=self.session_dir)
        )
        resources = ConfigurationResources(
            kind=RESOURCE_KIND, location=roots["profile"], applied=False
        )
        return PreparedHarness(
            harness_id=FAMILY_ID,
            launch_spec=spec,
            session=session,
            resources=resources,
            descriptor=describe(),
        )

    def describe(self) -> dict[str, Any]:
        """Static harness facts. No runtime readiness claim."""
        return describe()


__all__ = [
    "AGENT_DIR_KEY",
    "OFFLINE_KEY",
    "RESOURCE_KIND",
    "PiHarnessPreparation",
]
