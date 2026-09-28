"""The neutral sandbox seam: a channel states the demand, a resolved provider
translates it.

It lives in the neutral layer because both sides depend on it: the Server
assembles through it and a sandbox plugin implements it, and a plugin must
not reach into the Server package.

The channel (the Worker-hosted sidecar room or the local room) knows *what* it
needs - one workspace bound read-write, a staged read-only view, a materialised
credential, the mount sets, the profile's real home directory and its audit
window, the attempt-ephemeral paths, and the invariants an execution must keep.
It does not know *who* provides the isolation. This module is the one vocabulary
both sides share:

* :class:`SidecarRoomRequest` - the demand, in neutral terms (all of the terms
  are facts the channel just obtained; none of them name a sandbox);
* :class:`RoomInvariants` - the properties the caller requires of any provider
  (a real writable home directory, immutable read-only inputs, no residue in
  temporary paths, no credential in argv, and the declared network posture);
* :class:`RoomProcessSpec` - the translation: argv plus the guest
  environment the provider decided for its own idiom (kept under this local
  name so the provider-private env face stays outside the frozen public
  projection; the legacy alias below keeps every existing import working);
* :class:`SandboxPort` - the interface a resolved provider implements;
* :func:`resolve_sandbox_port` - name-based resolution through the installed
  plugin entry points (`agent_box.plugins`), never a concrete import.

Refusals are typed: an unavailable provider, an unparseable name, or a
provider that cannot keep a requested invariant is refused by name rather than
silently executed somewhere else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

#: The plugin entry point that serves the sidecar room for one sandbox.
SANDBOX_PORT_FACTORY = "create_sidecar_room_port"

#: Explicit module escape hatch for runtimes where the plugin is importable but
#: not pip-installed (the PYTHONPATH development and gate environments). The
#: value is supplied by the environment, never guessed here: an unset variable
#: means the resolution fails as typed rather than trying some module name.
SANDBOX_PORT_MODULE_VARIABLE = "AGENT_BOX_SANDBOX_MODULE"

#: Process-local registrations, filled by an embedding process (a gate, a test
#: session) that already resolved the port it wants.
_REGISTERED_FACTORIES: dict[str, Any] = {}


def register_sandbox_port_factory(name: str, factory: Any) -> None:
    """Register one port factory by provider name for this process."""
    if not isinstance(name, str) or not name.strip():
        raise SandboxPortUnavailable("SANDBOX_PROVIDER_UNRESOLVED", "empty provider name")
    _REGISTERED_FACTORIES[name.strip().lower().replace("-", "_")] = factory


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


#: Backward-compatibility alias (INC2-A per E-015 pre-ruling): the re-export,
#: fake, bwrap and tests-integration reference surfaces keep importing the old
#: name untouched; retirement of the alias is a separate approved batch.
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


def _load_factory(name: str):
    from importlib import metadata

    from pacthold.extensions.loader import ENTRY_POINT_GROUP

    discovered = metadata.entry_points()
    group = (
        discovered.select(group=ENTRY_POINT_GROUP)
        if hasattr(discovered, "select") else discovered.get(ENTRY_POINT_GROUP, ())
    )
    wanted = name.strip().lower().replace("-", "_")
    matches = []
    for entry_point in group:
        entry_name = entry_point.name.lower().replace("-", "_")
        module_root = entry_point.value.split(":")[0].split(".")[0].lower().replace("-", "_")
        if entry_name == wanted or module_root == wanted:
            matches.append(entry_point)
    if not matches:
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"no installed plugin entry point matches sandbox provider {name!r}",
        )
    module = matches[0].load()
    factory = getattr(module, SANDBOX_PORT_FACTORY, None)
    if not callable(factory):
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"plugin {name!r} exposes no {SANDBOX_PORT_FACTORY}",
        )
    return factory


def _factory_from_configured_module(provider: str):
    """The explicit module escape hatch, used only when the variable is set.

    The module name comes from the environment (the embedding runtime states
    which importable package serves the room); this layer never guesses a
    module name from a provider id.
    """
    import importlib
    import os

    module_name = os.environ.get(SANDBOX_PORT_MODULE_VARIABLE, "").strip()
    if not module_name:
        return None
    module = importlib.import_module(module_name)
    factory = getattr(module, SANDBOX_PORT_FACTORY, None)
    if not callable(factory):
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"{SANDBOX_PORT_MODULE_VARIABLE} module {module_name!r} exposes no "
            f"{SANDBOX_PORT_FACTORY}",
        )
    declared = getattr(factory, "provider_ids", None)
    if declared is not None and provider.lower().replace("-", "_") not in {
        item.lower().replace("-", "_") for item in declared
    }:
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED",
            f"module {module_name!r} does not serve provider {provider!r}",
        )
    return factory


def resolve_sandbox_port(name: str) -> SandboxPort:
    """Resolve a provider name to its port, in declaration order.

    1. the process-local registry (an embedding process registered it);
    2. the installed plugin entry points (pip-installed deployments);
    3. the explicit ``AGENT_BOX_SANDBOX_MODULE`` module (PYTHONPATH runtimes).

    Every path is explicit; an unresolved name is a typed refusal rather than a
    silent fallback to some other sandbox.
    """
    if not isinstance(name, str) or not name.strip():
        raise SandboxPortUnavailable(
            "SANDBOX_PROVIDER_UNRESOLVED", "sandbox provider name is empty",
        )
    normalized = name.strip().lower().replace("-", "_")
    factory = _REGISTERED_FACTORIES.get(normalized)
    if factory is None:
        try:
            factory = _load_factory(name)
        except SandboxPortUnavailable:
            factory = _factory_from_configured_module(name)
        except ModuleNotFoundError:
            factory = _factory_from_configured_module(name)
        if factory is None:
            raise SandboxPortUnavailable(
                "SANDBOX_PROVIDER_UNRESOLVED",
                f"no registration, installed entry point or "
                f"{SANDBOX_PORT_MODULE_VARIABLE} module serves sandbox provider {name!r}",
            )
    return factory()


__all__ = [
    "IsolatedProcessSpec",
    "RoomInvariants",
    "RoomProcessSpec",
    "SANDBOX_PORT_FACTORY",
    "SANDBOX_PORT_MODULE_VARIABLE",
    "SandboxInvariantUnsupported",
    "SandboxPort",
    "SandboxPortError",
    "SandboxPortUnavailable",
    "SidecarRoomRequest",
    "register_sandbox_port_factory",
    "resolve_sandbox_port",
]
