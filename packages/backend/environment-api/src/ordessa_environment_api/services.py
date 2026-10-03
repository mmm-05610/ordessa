"""Platform-service DTOs (E4/F4): data areas, host interaction, secrets.

These are *contracts*, not implementations: the platform-services adapters
(order 005) and Workbench/native-bridge (order 009) implement them. The
namespace rules are frozen here — a namespace comes from a stable
domain/release identity, never a window id, an activation generation or a
physical path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_NAMESPACE = re.compile(r"^[a-z][a-z0-9._-]{0,95}$")
_OPERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SecretAvailability(Enum):
    AVAILABLE = "available"
    LOCKED = "locked"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SecretRef:
    """An opaque secret reference — knowing the ref grants no read.

    The ref never contains secret material or a native locator that would
    bypass permission. Rotation mints a new ``revision``; the old MAC
    comparison capability for spent requests is preserved per C2.
    """

    ref: str
    revision: str
    owner_namespace: str
    access_purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$", self.ref):
            raise ValueError("SecretRef.ref is malformed")
        if not isinstance(self.revision, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$", self.revision):
            raise ValueError("SecretRef.revision is malformed")
        for name in ("owner_namespace", "access_purpose"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _NAMESPACE.match(v):
                raise ValueError(f"SecretRef.{name} is malformed")


@dataclass(frozen=True)
class DataAreaDescriptor:
    """A claimed data space: stable namespace identity + declared guarantees.

    ``backend_kind``/``supported_schema_range``/``current_schema_evidence``
    are declared by the plugin and verified by the adapters — constructing a
    database is never an implicit migration authorization.
    """

    area_id: str
    namespace: str
    owner_domain: str
    backend_kind: str  # file|sqlite|external|memory
    supported_schema_range: str
    current_schema_evidence: str | None
    access: str  # read|write
    persistence_guarantee: str  # durable|none
    retention: str  # keep|ephemeral

    def __post_init__(self) -> None:
        for name in ("area_id", "namespace", "owner_domain"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _NAMESPACE.match(v):
                raise ValueError(f"DataAreaDescriptor.{name} is malformed")
        if self.backend_kind not in {"file", "sqlite", "external", "memory"}:
            raise ValueError(f"DataAreaDescriptor.backend_kind {self.backend_kind!r} is not frozen")
        if self.access not in {"read", "write"}:
            raise ValueError("DataAreaDescriptor.access must be read|write")
        if self.persistence_guarantee not in {"durable", "none"}:
            raise ValueError("DataAreaDescriptor.persistence_guarantee must be durable|none")
        if self.retention not in {"keep", "ephemeral"}:
            raise ValueError("DataAreaDescriptor.retention must be keep|ephemeral")
        if not isinstance(self.supported_schema_range, str) or not re.match(
            r"^[0-9]+(\.[0-9]+)?-[0-9]+(\.[0-9]+)?$", self.supported_schema_range
        ):
            raise ValueError("DataAreaDescriptor.supported_schema_range must be lo-hi")


class HostDialogStatus(Enum):
    SELECTED = "selected"          # a path/dir selection (grants nothing)
    CONFIRMED = "confirmed"        # a plain user confirmation — NOT an approval
    CANCELLED = "cancelled"        # zero domain writes
    REVOKED = "revoked"            # scope died before the answer returned
    UNAVAILABLE = "unavailable"    # capability absent — never fabricate a choice
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HostDialogRequest:
    """Workbench/native-bridge dialog request (F4 §宿主交互)."""

    operation_id: str
    caller_activation: str
    caller_generation: int
    scope: str
    purpose: str
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not _OPERATION.match(self.operation_id):
            raise ValueError("HostDialogRequest.operation_id is malformed")
        for name in ("caller_activation", "scope", "purpose"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _NAMESPACE.match(v):
                raise ValueError(f"HostDialogRequest.{name} is malformed")
        if type(self.caller_generation) is not int or self.caller_generation < 0:
            raise ValueError("HostDialogRequest.caller_generation must be a non-negative int")


@dataclass(frozen=True)
class HostDialogResult:
    """Late-safe dialog outcome: revoked/cancelled write nothing anywhere."""

    operation_id: str
    status: HostDialogStatus
    selected_handle: str | None = None
    confirmed_option: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not _OPERATION.match(self.operation_id):
            raise ValueError("HostDialogResult.operation_id is malformed")
        if self.status is HostDialogStatus.SELECTED and not self.selected_handle:
            raise ValueError("selected results must carry a handle to release or register")
        if self.status is HostDialogStatus.CONFIRMED and not self.confirmed_option:
            raise ValueError("confirmed results must name the confirmed option")
        if self.status in (HostDialogStatus.CANCELLED, HostDialogStatus.REVOKED) and (
            self.selected_handle is not None or self.confirmed_option is not None
        ):
            raise ValueError("cancelled/revoked results must be write-free")
