"""Preparation contracts: the finished launch, and who produces it.

These are *facts about a launch that has not happened yet*. They carry no
authority: holding a :class:`PreparedAgent` never authorizes starting anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ..harness.transport import LaunchSpec


class PreparationRefused(RuntimeError):
    """Preparation could not produce a usable launch. Nothing was started."""

    code = "PREPARATION_REFUSED"


@dataclass(frozen=True)
class ConfigurationResources:
    """The prepared configuration a launch will read.

    ``location`` is where the harness reads its configuration from. ``applied``
    records whether preparation already materialized content there — preparation
    points at resources, it never grants authority over them.
    """

    kind: str
    location: str
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "location": self.location, "applied": self.applied}


@dataclass(frozen=True)
class SessionBootstrap:
    """How the launch establishes, resumes, or refuses a native session.

    ``mode`` is ``"fresh"``, ``"resume"`` or ``"none"``. ``"none"`` means the
    launch deliberately has no native session; it is not a missing value.
    """

    mode: str
    location: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("fresh", "resume", "none"):
            raise PreparationRefused(f"unknown session bootstrap mode {self.mode!r}")
        if self.mode == "none" and self.location is not None:
            raise PreparationRefused("a session-less bootstrap must not carry a location")
        if self.mode != "none" and not self.location:
            raise PreparationRefused("a session bootstrap requires a location")

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "location": self.location}


@dataclass(frozen=True)
class PreparedHarness:
    """One harness's finished preparation for exactly one launch.

    The launcher consumes :attr:`launch_spec` verbatim: it must not add, remove
    or reorder an argument, and must not merge further environment keys. Every
    brand-specific decision is already made here.
    """

    harness_id: str
    launch_spec: LaunchSpec
    session: SessionBootstrap
    resources: ConfigurationResources
    descriptor: Mapping[str, Any]

    @property
    def argv(self) -> tuple[str, ...]:
        return self.launch_spec.argv

    def to_dict(self) -> dict[str, Any]:
        return {
            "harnessId": self.harness_id,
            "argv": list(self.launch_spec.argv),
            "cwd": self.launch_spec.cwd,
            "session": self.session.to_dict(),
            "resources": self.resources.to_dict(),
            "descriptor": dict(self.descriptor),
        }


@dataclass(frozen=True)
class PreparedAgent:
    """One Agent: a harness preparation pinned to one Profile revision.

    The profile revision is fixed at preparation time, so a later profile edit
    cannot silently change what an already-prepared launch will run.
    """

    agent_id: str
    profile_revision: str
    harness: PreparedHarness

    def to_dict(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "profileRevision": self.profile_revision,
            "harness": self.harness.to_dict(),
        }


@runtime_checkable
class HarnessPreparation(Protocol):
    """A harness's single launch-plan producer.

    Implemented by each harness brand plugin. ``prepare`` is pure with respect to
    effects: it may validate and plan, but it must not start a process, write a
    record or mutate configuration.
    """

    harness_id: str

    def prepare(self, private_root_facts: Mapping[str, str]) -> PreparedHarness: ...


__all__ = [
    "ConfigurationResources",
    "HarnessPreparation",
    "PreparedAgent",
    "PreparedHarness",
    "PreparationRefused",
    "SessionBootstrap",
]
