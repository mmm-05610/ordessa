"""Provider-neutral runtime identity and result resources.

Provider settings and allocation policy stay with concrete provider packages;
these frozen values carry only the stable identity and result fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import PurePosixPath
from typing import Mapping

from ordessa_infrastructure.encoding.content_identity import digest

from .capabilities import CapabilityStatus


RUNTIME_COMPOSITION_CONTRACT_ID = "agent-box.runtime-composition@1"
RUNTIME_HOST_CONTRACT_ID = "agent-box.runtime-host@1"
SANDBOX_CONTRACT_ID = "agent-box.sandbox@1"


def _text(value: str, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\0" in value:
        raise ValueError(f"invalid {name}")
    return value


class SandboxError(RuntimeError):
    """Base class for sandbox policy failures."""


class SandboxUnsupported(SandboxError):
    """The selected sandbox cannot provide a requested invariant."""


class SandboxUnavailable(SandboxError):
    """No usable sandbox provider or instance is available."""


class SandboxAmbiguous(SandboxError):
    """The sandbox effect may have happened but cannot be confirmed."""


class ProjectionRejected(SandboxError):
    """A requested guest projection is malformed or disallowed."""


_CAPABILITY = re.compile(r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$")


def guest_path(value: str) -> str:
    value = _text(value, "guest path", 256)
    if not value.startswith("/") or value.endswith("/") or any(
        part in {"", ".", ".."} for part in value[1:].split("/")
    ):
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
        if len(self.required) > 32 or len(set(self.required)) != len(self.required) or any(
            not _CAPABILITY.fullmatch(value) for value in self.required
        ):
            raise ValueError("invalid capability requirements")
        _text(self.assurance, "assurance", 64)
        if self.network not in {"none", "inherit"}:
            raise ValueError("network must be none or inherit")

    @property
    def digest(self) -> str:
        return digest({"required": self.required, "assurance": self.assurance, "network": self.network})


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
        for name, value in (("provider", self.provider), ("native_id", self.native_id),
                            ("policy_digest", self.policy_digest), ("affinity", self.affinity)):
            _text(value, f"SandboxRef.{name}", 256)
        if self.schema_version != 1:
            raise ValueError("unsupported SandboxRef schema")
        if self.network_mode not in {"none", "inherit"}:
            raise ValueError("unsupported sandbox network mode")


@dataclass(frozen=True)
class CapabilitySet:
    values: Mapping[str, CapabilityStatus] = field(default_factory=dict)
    assurance: str = "provider_self_report"
    affinity: str = ""

    def __post_init__(self) -> None:
        values = dict(self.values)
        if len(values) > 128 or any(
            not isinstance(key, str) or not isinstance(value, CapabilityStatus)
            for key, value in values.items()
        ):
            raise ValueError("invalid capability set")
        object.__setattr__(self, "values", values)
        _text(self.assurance, "assurance", 64)
        _text(self.affinity, "affinity", 256)

    @property
    def digest(self) -> str:
        return digest({"values": {key: value.value for key, value in sorted(self.values.items())},
                       "assurance": self.assurance, "affinity": self.affinity})


@dataclass(frozen=True)
class RuntimeHostV1:
    """Registry entry for one exact, already-resolved RuntimeHost port."""

    contract_id = RUNTIME_HOST_CONTRACT_ID
    ref: RuntimeHostRef
    port: object = field(compare=False, repr=False)

    def __getattr__(self, name: str) -> object:
        return getattr(self.port, name)


@dataclass(frozen=True)
class SandboxV1:
    """Registry entry for one exact, already-resolved Sandbox port."""

    contract_id = SANDBOX_CONTRACT_ID
    ref: SandboxRef
    port: object = field(compare=False, repr=False)

    def __getattr__(self, name: str) -> object:
        return getattr(self.port, name)


@dataclass(frozen=True)
class IsolatedProcessSpec:
    """The frozen public projection of one wrapped process request.

    It carries only the provider-neutral launch identity and representation.
    Provider-private launch facts (a local working directory, a built
    environment mapping, a provider transport payload) stay with the provider
    that wrapped the request; they must never cross into this projection.
    """

    spawn_token: str
    attempt_key: str
    spec_digest: str
    io_mode: str = "stdio"
    local_argv: tuple[str, ...] | None = None
    provider_transport: str | None = None
    carrier_argv: tuple[str, ...] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if (self.local_argv is None) == (self.provider_transport is None):
            raise ValueError("exactly one typed launch representation is required")
        for name, value in (("spawn_token", self.spawn_token), ("attempt_key", self.attempt_key),
                            ("spec_digest", self.spec_digest)):
            _text(value, name, 256)
