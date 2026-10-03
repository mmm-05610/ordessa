"""Port protocols (E1 StorePort/PolicyPort, E4 DataAreaPort/SecretPort, C2
ProtectedFingerprintPort) — signatures only, no implementations, no state.

These Protocols are the frozen seams the implementations plug into:
persistence-sqlite (005), platform-services (005) and the Environment
(003/004) provide the concrete objects. An absent optional port never
disables ordinary raw/read paths — it refuses only the guarantees that need
it (E1 §PolicyPort, M06).
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from .guarantee import FingerprintDescriptor
from .identity import RequestKey
from .references import PersistentReference
from .services import DataAreaDescriptor, SecretAvailability, SecretRef


@runtime_checkable
class StorePort(Protocol):
    """Durable admission/read seam (E1). No DB transaction is held across an
    external call; every method is an isolated instance operation."""

    def transaction(self) -> Any: ...

    def reserve_request(self, key: RequestKey, digest: str) -> bool:
        """Atomically claim (E, principal, surface, request_key); False when
        the key is already spent (same digest → replay, different digest →
        conflict — never a second dispatch)."""
        ...

    def commit_activity(self, activity_id: str, receipt: Mapping[str, Any]) -> None: ...

    def commit_creation_and_usage(
        self, activity_id: str, objects: Mapping[str, Any], usages: Mapping[str, Any]
    ) -> None:
        """V3-1: receipt + objects + usages + obligation transfer in ONE
        transaction, or nothing."""
        ...

    def append_receipt(self, activity_id: str, receipt: Mapping[str, Any]) -> None: ...

    def read_current(self, activity_id: str) -> Mapping[str, Any] | None: ...

    def lookup_history(self, activity_id: str) -> Mapping[str, Any] | None:
        """History-read is a separate permission from invoke (V3-3)."""
        ...

    def claim_response_slot(self, control_id: str, delivery_revision: int) -> bool:
        """V3-5: one effectful answer per control delivery revision."""
        ...


@runtime_checkable
class PolicyPort(Protocol):
    """Environment admission policy (E1): refuse-by-default for effects when
    absent; resource read-allowed-by-assembly otherwise."""

    def admit_invoke(self, principal: str, surface: str, guarantee: str) -> bool: ...

    def admit_object_access(self, principal: str, object_ref: str, mode: str) -> bool: ...


@runtime_checkable
class ProtectedFingerprintPort(Protocol):
    """C2/M06: command-agnostic protected fingerprint of complete inputs."""

    def describe(self) -> FingerprintDescriptor: ...

    def fingerprint(self, key: RequestKey, binding_digest: str, content_digest: str) -> str:
        """HMAC-SHA256 over the canonical request-key MAC encoding; raises
        ComparisonUnavailableError when the named key material is gone —
        spent tombstones still block re-dispatch."""
        ...


@runtime_checkable
class DataAreaPort(Protocol):
    """E4 data-space seam: claim/open/close/inspect with stable namespaces."""

    def claim(self, namespace: str, access: str, schema_declaration: str) -> DataAreaDescriptor: ...

    def open(self, area_id: str) -> Any: ...

    def close(self, area_id: str) -> None: ...

    def inspect(self, area_id: str) -> DataAreaDescriptor: ...


@runtime_checkable
class SecretPort(Protocol):
    """E4 secret seam: refs only leave the trusted side; renderer manages
    references, never plaintext."""

    def store(self, ref: SecretRef, purpose: str) -> SecretRef: ...

    def describe(self, ref: SecretRef) -> SecretAvailability: ...

    def borrow_for_use(
        self, ref: SecretRef, principal: str, purpose: str, target: str
    ) -> Any:
        """Trusted-side short-term borrow registered as a Usage; verifies
        principal/activation/purpose/target/generation every time."""
        ...

    def revoke_access(self, ref: SecretRef, principal: str) -> None: ...

    def delete(self, ref: SecretRef, evidence: Mapping[str, str]) -> None:
        """Independent authorized effect; in-flight borrows and persistent
        references participate in the deletion admission; spent MAC tombstones
        survive."""
        ...


@runtime_checkable
class RelationshipPort(Protocol):
    """E5 persistent-reference seam (same-Environment gate; 004 implements)."""

    def publish_reference_set(
        self, source_key: str, source_revision: str, relations: tuple[PersistentReference, ...],
        operation_id: str,
    ) -> None: ...

    def inspect_incoming(
        self, target_key: str, change_kind: str, coverage_epoch: int
    ) -> Mapping[str, Any]:
        """Declared relations + coverage known/unknown — never a business-DB
        scan."""
        ...

    def prepare_resource_change(
        self, target_key: str, expected_revision: str, change_kind: str, operation_id: str
    ) -> Any:
        """ChangeReservation admission; serialized with new relations at the
        same gate."""
        ...
