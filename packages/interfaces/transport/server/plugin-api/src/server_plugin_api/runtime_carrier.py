"""Closed native carrier operation declarations for Server transport providers.

These values never own execution admission, attempts or target creation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Protocol, runtime_checkable

_TRANSPORT_OPERATION_TYPE = re.compile(r"^[a-z][a-z0-9.-]+@[1-9][0-9]*$")

def _text(value: str, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\0" in value:
        raise ValueError(f"invalid {name}")
    return value



@dataclass(frozen=True)
class HostTransportOperation:
    """Closed operation handed to HostTransport; never a shell command."""

    attempt_key: str
    spawn_token: str
    spec_digest: str
    transport_kind: str = "typed"
    sealed_payload: str | None = None



class HostTransport(Protocol):
    def submit(self, operation: HostTransportOperation) -> str: ...



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

