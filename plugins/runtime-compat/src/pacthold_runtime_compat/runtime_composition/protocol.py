"""Provider-neutral execution runtime composition protocol (P0).

This module is intentionally a closed, typed boundary.  Providers may attach
opaque values to their own implementations, but the public DTOs never carry
shell text, host paths, secrets, or provider-specific configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol, Sequence, runtime_checkable
from ..credentials import PreparedSecretMount

CONTRACT_ID = "agent-box.runtime-composition@1"
RUNTIME_HOST_CONTRACT_ID = "agent-box.runtime-host@1"
SANDBOX_CONTRACT_ID = "agent-box.sandbox@1"
TERMINAL_SESSION_CONTRACT_ID = "agent-box.terminal-session@1"

#: C-RUNTIME@v1 §1. A provider that does not list this capability in its
#: `CapabilitySet` stays fully valid and need not implement the compensation
#: verbs; consumers must then treat those components as side-effecting and
#: must not duck-dispatch unannounced verbs.
COMPENSATION_CAPABILITY = "composition.compensation@1"
#: Closed expression of `RuntimeHost.terminate` over the existing
#: `HostTransport.submit` channel (C-RUNTIME@v1 §1; no new process SPI).
TERMINATE_TRANSPORT_KIND = "terminate@1"


@dataclass(frozen=True)
class RuntimeHostV1:
    """Registry value for one exact, already-resolved RuntimeHost port."""
    contract_id = RUNTIME_HOST_CONTRACT_ID
    ref: "RuntimeHostRef"
    port: object = field(compare=False, repr=False)

    def __getattr__(self, name: str) -> object:
        return getattr(self.port, name)


@dataclass(frozen=True)
class SandboxV1:
    """Registry value for one exact, already-resolved Sandbox port."""
    contract_id = SANDBOX_CONTRACT_ID
    ref: "SandboxRef"
    port: object = field(compare=False, repr=False)

    def __getattr__(self, name: str) -> object:
        return getattr(self.port, name)


@dataclass(frozen=True)
class TerminalSessionV1:
    """Registry value for one exact, already-resolved TerminalSession port."""
    contract_id = TERMINAL_SESSION_CONTRACT_ID
    ref: "TerminalSessionRef"
    port: object = field(compare=False, repr=False)

    def __getattr__(self, name: str) -> object:
        return getattr(self.port, name)


class CompositionError(RuntimeError):
    """Base class for protocol failures."""


class CompositionErrorCode(str, Enum):
    INVALID_BINDING = "INVALID_BINDING"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    AFFINITY_MISMATCH = "AFFINITY_MISMATCH"
    ATTEMPT_REPLAY = "ATTEMPT_REPLAY"
    SPAWN_TOKEN_INVALID = "SPAWN_TOKEN_INVALID"
    START_AMBIGUOUS = "START_AMBIGUOUS"


class CompositionRejected(CompositionError):
    def __init__(self, code: CompositionErrorCode, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


class StartAmbiguous(CompositionError):
    code = CompositionErrorCode.START_AMBIGUOUS


def _text(value: str, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\0" in value:
        raise ValueError(f"invalid {name}")
    return value


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def digest_json(value: object) -> str:
    """Legacy-name alias of :func:`digest`.

    bwrap template digests were computed with this name; keeping it as an
    exact alias guarantees template identity/digest stability across the
    retired standalone sandbox protocol module.
    """
    return digest(value)


def content_digest(path: object) -> str:
    """The single formal source-integrity digest; strict and fail closed.

    Regular files hash by content; directories hash as a canonical sorted
    tree listing.  Missing sources, symlinked sources, symlinks or special
    files inside a tree, and any other filesystem shape are rejected — a
    Harness that needs a sanitized snapshot must prepare an execution-local
    source before declaring it; the assembler never rewrites sources.
    """
    path = Path(path)
    if not path.exists() or path.is_symlink():
        raise ValueError("runtime source is unavailable or symlinked")
    if path.is_file():
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.is_dir():
        raise ValueError("runtime source must be a regular file or directory")
    rows = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ValueError("runtime source contains symlink or special file")
        rows.append((item.relative_to(path).as_posix(), "dir" if item.is_dir() else "file",
                     "" if item.is_dir() else hashlib.sha256(item.read_bytes()).hexdigest()))
    return "sha256:" + hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SandboxError(RuntimeError):
    """Base class for sandbox policy failures."""


class SandboxUnsupported(SandboxError):
    pass


class SandboxUnavailable(SandboxError):
    pass


class SandboxAmbiguous(SandboxError):
    pass


class ProjectionRejected(SandboxError):
    pass


_CAPABILITY = re.compile(r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$")


def guest_path(value: str) -> str:
    value = _text(value, "guest path", 256)
    if not value.startswith("/") or value.endswith("/") or any(p in {"", ".", ".."} for p in value[1:].split("/")):
        raise ProjectionRejected("guest path must be normalized and absolute")
    if str(PurePosixPath(value)) != value:
        raise ProjectionRejected("guest path is not canonical")
    return value


@dataclass(frozen=True)
class SandboxRequirements:
    required: tuple[str, ...] = ()
    assurance: str = "provider_self_report"
    network: str = "none"

    def __post_init__(self) -> None:
        if len(self.required) > 32 or len(set(self.required)) != len(self.required) or any(not _CAPABILITY.fullmatch(x) for x in self.required):
            raise ValueError("invalid capability requirements")
        _text(self.assurance, "assurance", 64)
        if self.network not in {"none", "inherit"}:
            raise ValueError("network must be none or inherit")

    @property
    def digest(self) -> str:
        return digest_json({"required": self.required, "assurance": self.assurance, "network": self.network})


@dataclass(frozen=True)
class RuntimeHostRef:
    provider: str
    native_id: str
    identity_digest: str
    affinity: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _text(self.provider, "RuntimeHostRef.provider", 128)
        _text(self.native_id, "RuntimeHostRef.native_id", 256)
        _text(self.identity_digest, "RuntimeHostRef.identity_digest", 128)
        _text(self.affinity, "RuntimeHostRef.affinity", 256)
        if self.schema_version != 1:
            raise ValueError("unsupported RuntimeHostRef schema")


@dataclass(frozen=True)
class SandboxRef:
    provider: str
    native_id: str
    policy_digest: str
    affinity: str
    schema_version: int = 1
    network_mode: str = "none"

    def __post_init__(self) -> None:
        for name, value in (("provider", self.provider), ("native_id", self.native_id), ("policy_digest", self.policy_digest), ("affinity", self.affinity)):
            _text(value, f"SandboxRef.{name}", 256)
        if self.schema_version != 1:
            raise ValueError("unsupported SandboxRef schema")
        if self.network_mode not in {"none", "inherit"}:
            raise ValueError("unsupported sandbox network mode")


@dataclass(frozen=True)
class TerminalSessionRef:
    provider: str
    native_id: str
    session_digest: str
    affinity: str
    schema_version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("provider", self.provider), ("native_id", self.native_id), ("session_digest", self.session_digest), ("affinity", self.affinity)):
            _text(value, f"TerminalSessionRef.{name}", 256)
        if self.schema_version != 1:
            raise ValueError("unsupported TerminalSessionRef schema")
        if len(self.metadata) > 32 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in self.metadata.items()):
            raise ValueError("invalid TerminalSessionRef metadata")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class RuntimeBinding:
    """Frozen exact composition inputs; all three refs are mandatory."""

    runtime_host_ref: RuntimeHostRef
    sandbox_ref: SandboxRef
    terminal_session_ref: TerminalSessionRef

    def __post_init__(self) -> None:
        if not all((self.runtime_host_ref, self.sandbox_ref, self.terminal_session_ref)):
            raise CompositionRejected(CompositionErrorCode.INVALID_BINDING, "three exact refs are required")


class CapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilitySet:
    values: Mapping[str, CapabilityStatus] = field(default_factory=dict)
    assurance: str = "provider_self_report"
    affinity: str = ""

    def __post_init__(self) -> None:
        values = dict(self.values)
        if len(values) > 128 or any(not isinstance(k, str) or not isinstance(v, CapabilityStatus) for k, v in values.items()):
            raise ValueError("invalid capability set")
        object.__setattr__(self, "values", values)
        _text(self.assurance, "assurance", 64)
        _text(self.affinity, "affinity", 256)

    @property
    def digest(self) -> str:
        return digest({"values": {k: v.value for k, v in sorted(self.values.items())}, "assurance": self.assurance, "affinity": self.affinity})


@dataclass(frozen=True)
class RuntimeSourceDeclaration:
    """Dispatch-local source declaration; never persisted in Core inputs.

    ``kind`` describes the projector's intent only — it is never a provider
    or contract branch key.  The declaring Harness projector owns the guest
    layout; the generic assembler consumes these declarations verbatim.
    """

    kind: str
    source_path: str
    guest_target: str
    access: str
    expected_digest: str
    provenance: str = ""
    authorized_scope: str = "execution"

    def __post_init__(self) -> None:
        for value in (self.kind, self.source_path, self.guest_target, self.access, self.expected_digest):
            _text(value, "runtime source field", 512)
        if self.access not in {"ro", "rw"}:
            raise ValueError("runtime source access must be ro or rw")
        if self.provenance:
            _text(self.provenance, "runtime source provenance", 256)
        _text(self.authorized_scope, "runtime source authorized scope", 128)


def declare_source(kind: str, source_path: object, guest_target: str, *, access: str = "ro",
                   provenance: str = "", authorized_scope: str = "execution") -> RuntimeSourceDeclaration:
    """Shared projector helper: declare one source with its content digest.

    Handles only generic paths, digests and declarations.  It knows nothing
    about any contract, provider, or guest path convention — the guest target
    is always the calling projector's decision.
    """
    return RuntimeSourceDeclaration(
        kind, str(Path(source_path)), guest_target, access,
        content_digest(source_path), provenance=provenance,
        authorized_scope=authorized_scope,
    )


@dataclass(frozen=True)
class HarnessCommandSpec:
    argv: tuple[str, ...]
    cwd_token: str
    environment: Mapping[str, str] = field(default_factory=dict)
    io_mode: str = "stdio"
    command_digest: str = ""
    runtime_sources: tuple[RuntimeSourceDeclaration, ...] = field(default_factory=tuple, compare=False, repr=False)
    requires_control_plane_network: bool = False
    tool_network_requirement: str = "unspecified"
    # Declaring projector identity (harness-owned); carried for honest
    # projection receipts, never used as a Root branch key.
    projector_id: str = ""

    def __post_init__(self) -> None:
        if not self.argv or len(self.argv) > 64 or any(not isinstance(x, str) or not x or "\0" in x for x in self.argv):
            raise ValueError("argv must be bounded and non-empty")
        _text(self.cwd_token, "cwd_token")
        if self.io_mode not in {"stdio", "pty"}:
            raise ValueError("unsupported io_mode")
        if not isinstance(self.requires_control_plane_network, bool):
            raise ValueError("requires_control_plane_network must be bool")
        if self.tool_network_requirement not in {"unspecified", "none", "inherit"}:
            raise ValueError("unsupported tool network requirement")
        if self.projector_id:
            _text(self.projector_id, "projector_id", 128)
        if len(self.environment) > 64:
            raise ValueError("environment is too large")
        if len(self.runtime_sources) > 16 or any(not isinstance(item, RuntimeSourceDeclaration) for item in self.runtime_sources):
            raise ValueError("invalid runtime source declarations")
        object.__setattr__(self, "environment", dict(self.environment))

    @property
    def digest(self) -> str:
        return self.command_digest or digest({"argv": self.argv, "cwd": self.cwd_token, "environment": self.environment, "io": self.io_mode, "control_plane_network": self.requires_control_plane_network, "tool_network": self.tool_network_requirement})


@dataclass(frozen=True)
class PreparedMountSource:
    source_token: str
    content_digest: str
    provenance_digest: str
    authorized_scope: str


@dataclass(frozen=True)
class MountPlan:
    mounts: tuple[tuple[PreparedMountSource, str, str], ...] = ()
    tmpfs_targets: tuple[str, ...] = ()
    plan_digest: str = ""
    secret_mounts: tuple[PreparedSecretMount, ...] = ()

    @property
    def digest(self) -> str:
        if self.plan_digest:
            return self.plan_digest
        return digest({"mounts": self.mounts, "tmpfs_targets": self.tmpfs_targets,
                       "secret_mounts": tuple((m.credential_ref.provider, m.credential_ref.native_locator,
                                                m.execution_scope, m.guest_target, m.access,
                                                m.materialization_method) for m in self.secret_mounts)})


@dataclass(frozen=True)
class RuntimeBundle:
    host_ref: RuntimeHostRef
    mount_plan: MountPlan
    bundle_digest: str
    staging_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostTransportOperation:
    """Closed operation handed to HostTransport; never a shell command."""

    attempt_key: str
    spawn_token: str
    spec_digest: str
    transport_kind: str = "typed"
    sealed_payload: str | None = None


@dataclass(frozen=True)
class IsolatedProcessSpec:
    spawn_token: str
    attempt_key: str
    spec_digest: str
    io_mode: str = "stdio"
    local_argv: tuple[str, ...] | None = None
    provider_transport: str | None = None
    # Carrier-only argv is consumed by the installed TerminalSession plugin;
    # public diagnostics and Core receipts use the redacted local_argv.
    carrier_argv: tuple[str, ...] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if (self.local_argv is None) == (self.provider_transport is None):
            raise ValueError("exactly one typed launch representation is required")
        for name, value in (("spawn_token", self.spawn_token), ("attempt_key", self.attempt_key), ("spec_digest", self.spec_digest)):
            _text(value, name, 256)


@dataclass(frozen=True)
class TerminalAllocation:
    allocation_id: str
    terminal_ref: TerminalSessionRef
    allocation_digest: str


@dataclass(frozen=True)
class TerminalRunHandle:
    attempt_key: str
    native_correlation: str
    state: str
    allocation_id: str
    attach_descriptor: "AttachDescriptor | None" = None
    # Ephemeral carrier object for Harness control (for example a Popen
    # stream). Core persists only native_correlation.
    transport: object | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class AttachDescriptor:
    kind: str
    terminal_identity: str
    locator: str
    display_label: str
    expires_at: str


@dataclass(frozen=True)
class NativeCorrelationSet:
    runtime_host_identity: str
    sandbox_identity: str
    terminal_identity: str
    harness_identity: str | None = None


@dataclass(frozen=True)
class CompositionPreflightReceipt:
    binding_digest: str
    capability_digest: str
    accepted: bool
    affinity: str
    rejection_code: str | None = None
    #: The semantic capability the refusal is about (`isolation.wrap@1`, ...),
    #: so a rejection says *which* requirement failed, not only that one did.
    rejection_capability: str | None = None


@dataclass(frozen=True)
class CompositionAttemptRecord:
    attempt_key: str
    state: str
    token_consumed: bool = False
    target_creation_count: int = 0
    native_correlation: str | None = None


def attempt_key(*, execution_id: str, dispatch_id: str, ref_digests: Sequence[str], preflight_digest: str, bundle_digest: str, command_digest: str, mount_plan_digest: str) -> str:
    return digest({"execution_id": execution_id, "dispatch_id": dispatch_id, "refs": tuple(ref_digests), "preflight": preflight_digest, "bundle": bundle_digest, "command": command_digest, "mount_plan": mount_plan_digest})


class RuntimeHost(Protocol):
    ref: RuntimeHostRef
    capabilities: CapabilitySet
    transport: "HostTransport"
    def resolve(self, ref: RuntimeHostRef) -> "RuntimeHost": ...
    def stage(self, bundle: RuntimeBundle) -> RuntimeBundle: ...
    # C-RUNTIME@v1 §1 additive declarations (composition.compensation@1).
    # A host that does not declare the capability need not grow these verbs;
    # consumers then treat it as side-effecting (no duck-dispatch guessing).
    # The host-side cleanup verb is named `cleanup` per the INC2-A note —
    # terminal `release` is a different verb of a different family, not
    # renamed into this one. Terminate travels the closed transport:
    # `submit(HostTransportOperation(..., transport_kind="terminate@1"))`.
    def terminate(self, op: HostTransportOperation) -> object: ...
    # Observed host shapes: the composition host cleans up by its own
    # attempt state (zero args); the execution-keyed form carries
    # `execution_id`. Both satisfy this declaration; neither is renamed.
    def cleanup(self, execution_id: str | None = None) -> Mapping[str, object]: ...


class Sandbox(Protocol):
    ref: SandboxRef
    capabilities: CapabilitySet
    def resolve(self, ref: SandboxRef) -> "Sandbox": ...
    def wrap(self, mount_plan: MountPlan, command: HarnessCommandSpec, *, attempt_key: str) -> IsolatedProcessSpec: ...
    # C-RUNTIME@v1 §1 additive: cleanup family receipt
    # (`{"status": "cleaned"|"already_cleaned"|{"error": ...}}`, §2).
    def cleanup(self, spec: IsolatedProcessSpec) -> Mapping[str, object]: ...


class TerminalSession(Protocol):
    ref: TerminalSessionRef
    capabilities: CapabilitySet
    def resolve(self, ref: TerminalSessionRef) -> "TerminalSession": ...
    def allocate(self) -> TerminalAllocation: ...
    def run(self, host_transport: "HostTransport", spec: IsolatedProcessSpec, attempt_key: str) -> TerminalRunHandle: ...
    # C-RUNTIME@v1 §1 additive: tristate release family
    # (`{"released": bool, "destroyed": bool, "managed": bool}`, §2).
    def release(self, request: object | None = None) -> Mapping[str, object]: ...


class HostTransport(Protocol):
    def submit(self, operation: HostTransportOperation) -> str: ...


_TRANSPORT_OPERATION_TYPE = re.compile(r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$")


@dataclass(frozen=True)
class TransportOperationDescriptor:
    """Typed description of one restricted native transport operation.

    ``operation_type`` is the stable, versioned Catalog key (for example
    ``tmux-respawn@1``).  Replay and response-loss policies are fixed by the
    Root SPI — submissions are single-use-token guarded and a lost response
    escalates to START_AMBIGUOUS; handlers cannot opt out of either.
    """

    operation_type: str
    version: int = 1
    display_name: str = ""
    supported_runtime_host_capabilities: tuple[str, ...] = ()
    replay_policy: str = "single_use_token"
    response_loss_policy: str = "start_ambiguous"

    def __post_init__(self) -> None:
        _text(self.operation_type, "transport operation type", 128)
        if not _TRANSPORT_OPERATION_TYPE.fullmatch(self.operation_type):
            raise ValueError("transport operation_type must be a versioned identifier like vendor.kind@1")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("transport operation descriptor version must be a positive integer")
        if self.display_name:
            _text(self.display_name, "transport operation display name", 256)
        capabilities = self.supported_runtime_host_capabilities
        if len(capabilities) > 32 or any(not isinstance(c, str) or not _TRANSPORT_OPERATION_TYPE.fullmatch(c) for c in capabilities):
            raise ValueError("invalid runtime host capability requirement")
        if self.replay_policy != "single_use_token":
            raise ValueError("unsupported transport operation replay policy")
        if self.response_loss_policy != "start_ambiguous":
            raise ValueError("unsupported transport operation response loss policy")


@runtime_checkable
class TransportOperationHandler(Protocol):
    """One restricted native carrier operation; never an execution authority.

    A handler validates its sealed, typed payload and performs exactly the
    native transport action it declares.  It must not complete Executions,
    bypass the RuntimeHost, accept arbitrary shell strings, or replace any
    RuntimeHost/TerminalSession/Harness composition role.
    """

    def descriptor(self) -> TransportOperationDescriptor: ...
    def validate(self, operation: "HostTransportOperation") -> None: ...
    def execute(self, transport: "HostTransport", operation: "HostTransportOperation") -> object: ...


@dataclass(frozen=True)
class TransportOperationContribution:
    """Registration unit: descriptor + handler pair.

    Plugin provenance is recorded by the loader/Catalog, never self-declared
    by the handler.
    """

    descriptor: TransportOperationDescriptor
    handler: TransportOperationHandler = field(repr=False, compare=False)


class RuntimeHostProvider(RuntimeHost, Protocol):
    """Provider-facing RuntimeHost contract."""


class SandboxProvider(Sandbox, Protocol):
    """Provider-facing Sandbox contract."""


class TerminalSessionProvider(TerminalSession, Protocol):
    """Provider-facing TerminalSession contract."""


class CompositionCoordinator(Protocol):
    def start(self, binding: RuntimeBinding, command: HarnessCommandSpec, *, execution_id: str, dispatch_id: str) -> TerminalRunHandle: ...
