"""Runtime-host and sandbox provider ports.

The protocol views here describe data received from upstream owners without
importing or re-declaring their concrete request and plan DTOs. Implementations
remain structurally typed and receive the original objects unchanged.
"""
from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from .contracts import ProcessHandle
from .runtime_resources import (
    CapabilitySet,
    IsolatedProcessSpec,
    RuntimeHostRef,
    SandboxRef,
)


# Stable provider capability and transport operation identifiers.
COMPENSATION_CAPABILITY = "composition.compensation@1"
TERMINATE_TRANSPORT_KIND = "terminate@1"


class MountSourceInput(Protocol):
    @property
    def source_token(self) -> str: ...

    @property
    def content_digest(self) -> str: ...

    @property
    def provenance_digest(self) -> str: ...

    @property
    def authorized_scope(self) -> str: ...


class SecretCredentialInput(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def native_locator(self) -> str: ...


class SecretMountInput(Protocol):
    @property
    def token(self) -> str: ...

    @property
    def credential_ref(self) -> SecretCredentialInput: ...

    @property
    def execution_scope(self) -> str: ...

    @property
    def guest_target(self) -> str: ...

    @property
    def access(self) -> str: ...

    @property
    def materialization_method(self) -> str: ...


class MountPlanInput(Protocol):
    """Read-only view of the mount plan passed intact to Sandbox.wrap."""

    @property
    def mounts(self) -> Sequence[tuple[MountSourceInput, str, str]]: ...

    @property
    def tmpfs_targets(self) -> Sequence[str]: ...

    @property
    def plan_digest(self) -> str: ...

    @property
    def secret_mounts(self) -> Sequence[SecretMountInput]: ...

    @property
    def digest(self) -> str: ...


class RuntimeBundleInput(Protocol):
    """Read-only view of the bundle passed intact to RuntimeHost.stage."""

    @property
    def host_ref(self) -> RuntimeHostRef: ...

    @property
    def mount_plan(self) -> MountPlanInput: ...

    @property
    def bundle_digest(self) -> str: ...

    @property
    def staging_tokens(self) -> Sequence[str]: ...


class RuntimeSourceInput(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def source_path(self) -> str: ...

    @property
    def guest_target(self) -> str: ...

    @property
    def access(self) -> str: ...

    @property
    def expected_digest(self) -> str: ...

    @property
    def provenance(self) -> str: ...

    @property
    def authorized_scope(self) -> str: ...


class CommandInput(Protocol):
    """Read-only view of the command projection passed intact to Sandbox."""

    @property
    def argv(self) -> Sequence[str]: ...

    @property
    def cwd_token(self) -> str: ...

    @property
    def environment(self) -> Mapping[str, str]: ...

    @property
    def io_mode(self) -> str: ...

    @property
    def command_digest(self) -> str: ...

    @property
    def runtime_sources(self) -> Sequence[RuntimeSourceInput]: ...

    @property
    def requires_control_plane_network(self) -> bool: ...

    @property
    def tool_network_requirement(self) -> str: ...

    @property
    def projector_id(self) -> str: ...

    @property
    def digest(self) -> str: ...


class TransportOperationInput(Protocol):
    """Typed transport request view; it is not a shell command."""

    @property
    def attempt_key(self) -> str: ...

    @property
    def spawn_token(self) -> str: ...

    @property
    def spec_digest(self) -> str: ...

    @property
    def transport_kind(self) -> str: ...

    @property
    def sealed_payload(self) -> str | None: ...


class HostTransportInput(Protocol):
    def submit(self, operation: TransportOperationInput) -> str: ...


class RuntimeHost(Protocol):
    @property
    def ref(self) -> RuntimeHostRef: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    @property
    def transport(self) -> HostTransportInput: ...

    def resolve(self, ref: RuntimeHostRef) -> RuntimeHost: ...

    def stage(self, bundle: RuntimeBundleInput) -> RuntimeBundleInput: ...

    # A host that does not advertise composition.compensation@1 need not
    # implement terminate/cleanup; consumers must not infer support by probing.
    # Terminate uses HostTransport.submit with transport_kind="terminate@1".
    def terminate(self, op: TransportOperationInput) -> object: ...

    # The host-side cleanup family is independent of sandbox cleanup.
    def cleanup(self, execution_id: str | None = None) -> Mapping[str, object]: ...


class Sandbox(Protocol):
    @property
    def ref(self) -> SandboxRef: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    def resolve(self, ref: SandboxRef) -> Sandbox: ...

    def wrap(
        self, mount_plan: MountPlanInput, command: CommandInput, *, attempt_key: str,
    ) -> IsolatedProcessSpec: ...

    # The v1 launch seam: the sandbox performs the real spawn for a spec it
    # wrapped and returns the single managed process/byte-IO owner. It is
    # additive to wrap; a sandbox that cannot launch refuses explicitly rather
    # than returning a handle it does not own.
    def launch(self, spec: IsolatedProcessSpec, *, attempt_key: str) -> ProcessHandle: ...

    # Cleanup reports the sandbox family receipt; it does not release a process.
    def cleanup(self, spec: IsolatedProcessSpec) -> Mapping[str, object]: ...


class RuntimeHostProvider(RuntimeHost, Protocol):
    """Provider-facing RuntimeHost contract."""


class SandboxProvider(Sandbox, Protocol):
    """Provider-facing Sandbox contract."""
