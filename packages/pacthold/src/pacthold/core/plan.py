"""``ExecutionPlan`` and ``ResourceRequirement`` (specs/010 data-model.md).

An ExecutionPlan is immutable by construction (frozen + content digest):
after submission the only equality that matters is
``(request_key, digest)`` — the same key with a different digest must be
rejected by the host before any dispatch (contract primitive
``same_key_conflicting_digest``; wiring lands in T008).

Resource rules kept honest here: slots are unique, dependencies reference
declared slots only and must form no cycle ("无环"), and a missing provider
is recorded as ``None`` for the host to refuse explicitly — the core never
implicitly selects a provider.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .descriptors import validate_component_id, validate_contract_id
from .enums import OwnershipKind
from .errors import CoreDTOError

_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _non_blank(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CoreDTOError(f"{name} must be a non-empty string, got {value!r}")
    return value


@dataclass(frozen=True)
class ResourceRequirement:
    """One declared resource input of a plan: slot/contract/provider/deps/ownership."""

    slot: str
    contract_id: str
    provider_id: str | None = None
    dependencies: tuple[str, ...] = ()
    ownership: OwnershipKind = OwnershipKind.OWN

    def __post_init__(self) -> None:
        if not isinstance(self.slot, str) or not _COMPONENT_ID.fullmatch(self.slot):
            raise CoreDTOError(f"invalid requirement slot: {self.slot!r}")
        validate_contract_id(self.contract_id)
        if self.provider_id is not None:
            validate_component_id(self.provider_id, kind="provider")
        if not isinstance(self.dependencies, tuple) or any(
            not isinstance(dep, str) or not _COMPONENT_ID.fullmatch(dep)
            for dep in self.dependencies
        ):
            raise CoreDTOError(
                "dependencies must be a tuple of declared slot names, got "
                f"{self.dependencies!r}"
            )
        if self.slot in self.dependencies:
            raise CoreDTOError(f"requirement slot {self.slot!r} depends on itself")
        if not isinstance(self.ownership, OwnershipKind):
            raise CoreDTOError(f"ownership must be an OwnershipKind member, got {self.ownership!r}")


@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable submission: provider/version/resources/request_key/digest/Work."""

    request_key: str
    digest: str
    provider_id: str
    provider_version: str
    work_id: str
    resources: tuple[ResourceRequirement, ...] = ()
    previous_execution_ref: str | None = None
    """Session-resume association (specs/010 data-model.md Recovery: "Session
    resume 新 Execution，可关联 previous_execution_ref，不复用终态 ID").

    Optional and purely associative: a resume submits a NEW ``request_key`` (so a
    new execution id) over the same ``work_id`` and may name the terminal
    Execution it continues.  The dispatcher persists it verbatim on the new
    Execution row and never reads or rewrites the referenced record — terminal
    immutability (FR-004) is not a loophole for the predecessor.  The core does
    not verify that the referenced id exists: a resume legitimately names a
    terminal execution from this instance's history, and existence checks here
    would make an association able to fail a submission."""

    def __post_init__(self) -> None:
        _non_blank(self.request_key, "request_key")
        if not isinstance(self.digest, str) or not _DIGEST.fullmatch(self.digest):
            raise CoreDTOError(
                f"digest must be a 64-char lowercase hex content digest, got {self.digest!r}"
            )
        validate_component_id(self.provider_id, kind="provider")
        _non_blank(self.provider_version, "provider_version")
        # Work association: an existing Work id (FR: no implicit Profile/Session).
        _non_blank(self.work_id, "work_id")
        if self.previous_execution_ref is not None:
            _non_blank(self.previous_execution_ref, "previous_execution_ref")
        if isinstance(self.resources, (str, bytes)) or not isinstance(self.resources, (list, tuple)):
            raise CoreDTOError("resources must be a sequence of ResourceRequirement")
        items = tuple(self.resources)
        for item in items:
            if not isinstance(item, ResourceRequirement):
                raise CoreDTOError(f"resource entry must be ResourceRequirement, got {item!r}")
        slots = [item.slot for item in items]
        if len(slots) != len(set(slots)):
            raise CoreDTOError("plan resource slots must be unique")
        known = set(slots)
        for item in items:
            unknown = sorted(set(item.dependencies).difference(known))
            if unknown:
                raise CoreDTOError(
                    f"slot {item.slot!r} depends on undeclared slot(s): {', '.join(unknown)}"
                )
        self._reject_dependency_cycle(items)
        object.__setattr__(self, "resources", items)

    @staticmethod
    def _reject_dependency_cycle(items: tuple[ResourceRequirement, ...]) -> None:
        by_slot = {item.slot: item for item in items}
        # DFS with explicit path detection over the declared dependency graph.
        done: set[str] = set()
        for root in by_slot:
            if root in done:
                continue
            stack: list[str] = []
            on_path: set[str] = set()

            def visit(slot: str) -> None:
                if slot in on_path:
                    cycle = " -> ".join([*stack, slot])
                    raise CoreDTOError(f"plan dependency cycle: {cycle}")
                if slot in done:
                    return
                on_path.add(slot)
                stack.append(slot)
                for dep in sorted(by_slot[slot].dependencies):
                    visit(dep)
                stack.pop()
                on_path.discard(slot)
                done.add(slot)

            visit(root)

    def same_key_conflicting_digest(self, other: "ExecutionPlan") -> bool:
        """True when ``other`` replays this plan's request_key with a
        different content digest — the host must reject it and never
        dispatch a second time (contract primitive for T007/T008)."""
        if not isinstance(other, ExecutionPlan):
            raise CoreDTOError(f"cannot compare digest against {other!r}")
        return self.request_key == other.request_key and self.digest != other.digest

    @staticmethod
    def compute_digest(payload: bytes) -> str:
        """Convenience: sha256 hex over the caller's canonical plan bytes."""
        return hashlib.sha256(payload).hexdigest()
