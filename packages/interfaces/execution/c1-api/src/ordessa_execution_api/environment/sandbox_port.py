"""Pure sandbox demands, provider protocol and stable discovery identifiers."""
from __future__ import annotations


from dataclasses import dataclass, field


from typing import Any, Mapping, Protocol, Sequence


SANDBOX_PORT_FACTORY = "create_sidecar_room_port"


SANDBOX_PORT_MODULE_VARIABLE = "AGENT_BOX_SANDBOX_MODULE"


class SandboxPortError(RuntimeError):
    """Base class for sandbox seam refusals."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class SandboxPortUnavailable(SandboxPortError):
    """No resolved provider can serve this execution's sandbox demand."""


class SandboxInvariantUnsupported(SandboxPortError):
    """A resolved provider cannot keep an invariant the caller requires.

    A provider that would satisfy the demand by *redirecting* it (for example a
    home that is a mapped or emulated directory instead of a real one) must
    raise this instead of pretending the demand is met.
    """


@dataclass(frozen=True)
class RoomInvariants:
    """What any provider must keep for this execution, stated by the caller."""

    #: The profile home must be a real writable directory on the machine that
    #: runs the turn; a redirection layer must refuse rather than emulate it.
    home_real_directory: bool = True
    #: Read-only inputs must be immutable inside the room.
    ro_inputs_immutable: bool = True
    #: Attempt-ephemeral paths must leave no residue after the attempt.
    temp_no_residue: bool = True
    #: The credential must never appear in argv.
    credential_not_in_argv: bool = True
    #: Network posture, in neutral terms: "inherit" (the guest keeps the
    #: machine's connectivity) or "none" (the guest must not reach out).
    network_mode: str = "inherit"


@dataclass(frozen=True)
class SidecarRoomRequest:
    """One execution's sandbox demand, as the channel observed it."""

    workspace: str
    staged_view: str
    secret: str | None
    base_environment: Mapping[str, str]
    executable_mounts: tuple[tuple[str, str], ...] = ()
    projection_mounts: tuple[tuple[str, str], ...] = ()
    runtime_artifact_mounts: tuple[tuple[str, str], ...] = ()
    state_home_source: str | None = None
    state_target: str | None = None
    #: The profile's native home *relative* name inside the role directory
    #: (`.pi/agent`, `.codex`, ...). The Linux shape binds
    #: `state_home_source` at `/runtime/home/<native_home>` and needs no
    #: further mapping; a platform without binds (Windows) needs it to rewrite
    #: guest targets back onto the real role directory.
    native_home: str = ""
    state_window_source: str | None = None
    state_window_target: str | None = None
    #: Order 66's whole-db stores: extra read-write binds layered over the
    #: state home *after* it, each entry (host_source, guest_target). The
    #: family library owns the live session files/directories; everything the
    #: deployment did not name stays in the profile home. Later binds win on
    #: the providers that implement the ordering rule.
    state_overlays: tuple[tuple[str, str], ...] = ()
    state_ephemeral_paths: tuple[str, ...] = ()
    #: The guest executable entrypoint the room will run. It must be the
    #: template's own fixed entry (the view supplies its bytes), so callers
    #: that probe the room stage their script at that path instead of
    #: inventing a new one.
    entrypoint: str = "/runtime/view/agentbox-sidecar/runtime/worker-entry.mjs"
    invariants: RoomInvariants = field(default_factory=RoomInvariants)


@dataclass(frozen=True)
class RoomProcessSpec:
    """A provider's translation of one request."""

    argv: tuple[str, ...]
    environment: Mapping[str, str]


IsolatedProcessSpec = RoomProcessSpec


class SandboxPort(Protocol):
    """What the channel needs from whichever sandbox was resolved."""

    provider_id: str

    def compose_sidecar_room(self, request: SidecarRoomRequest) -> RoomProcessSpec:
        """Translate the demand into a runnable, isolated process spec."""

    def declaration_document(self, *, readonly_targets: Sequence[str],
                             writable_targets: Sequence[str],
                             environment_binding: str, observed_at: int) -> Any:
        """This execution's capability declaration as the provider states it.

        Returned as the provider's own document object (the assembly boundary
        consumes it through the capability package); the seam itself stays
        vocabulary-free.
        """

    def descriptor_id(self) -> str:
        """The provider's installed identity, for independent cross-checking."""

    def probe(self) -> Mapping[str, Any]:
        """Whether this provider can actually run a room on this host.

        The provider performs its own probe (its binary, its production root);
        the caller only reports the answer. Unavailability is a value here,
        not an exception: "this host cannot run the room" is not a refusal."""


__all__ = ['IsolatedProcessSpec', 'RoomInvariants', 'RoomProcessSpec', 'SANDBOX_PORT_FACTORY', 'SANDBOX_PORT_MODULE_VARIABLE', 'SandboxInvariantUnsupported', 'SandboxPort', 'SandboxPortError', 'SandboxPortUnavailable', 'SidecarRoomRequest', 'ENTRY_POINT_GROUP']

ENTRY_POINT_GROUP = "agent_box.plugins"
