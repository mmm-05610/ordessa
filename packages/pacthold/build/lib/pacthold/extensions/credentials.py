"""Provider-neutral execution-scoped SecretMount protocol.

The public objects intentionally contain no source path, secret bytes, digest,
or environment material.  Source handles remain private to the materializer
and the sandbox implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..resource_contracts import CredentialRefV1

CONTRACT_ID = CredentialRefV1.contract_id


@dataclass(frozen=True)
class ResolvedCredential:
    ref: CredentialRefV1
    provider: str
    status: str = "resolved"


@dataclass(frozen=True)
class PreparedSecretMount:
    token: str
    credential_ref: CredentialRefV1
    execution_scope: str
    guest_target: str
    access: str
    materialization_method: str = "readonly-bind"

    def __post_init__(self) -> None:
        if not self.token or "\0" in self.token:
            raise ValueError("invalid prepared secret token")
        if not self.execution_scope or not self.guest_target.startswith("/"):
            raise ValueError("invalid prepared secret mount scope or target")
        if self.access != "ro":
            raise ValueError("secret mounts are read-only")


@runtime_checkable
class CredentialMaterializer(Protocol):
    provider_id: str
    supported_contract_ids: frozenset[str]

    def resolve(self, contract_id: str, ref: object, *, context: object | None = None) -> ResolvedCredential: ...
    def prepare_mount(self, ref: CredentialRefV1, execution_scope: str, guest_target: str, access: str) -> PreparedSecretMount: ...
    def cleanup(self, prepared: PreparedSecretMount) -> None: ...
