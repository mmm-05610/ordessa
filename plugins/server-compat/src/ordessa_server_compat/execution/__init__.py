"""Neutral execution and Harness capability contracts.

Server composes extensions through these types only; concrete Harness
implementations are selected in `server/bootstrap` and owned by plugins.
MB-E2a: the pure contract definitions (``CancelOutcome`` …
``ExecutionObservation`` and ``TurnExecutionPort``) live once in
``pacthold.execution.contracts`` and are re-exported here as the same
objects for historical import paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from pacthold.execution.contracts import TurnExecutionPort
from pacthold_runtime_compat.resource_contracts.harness_capabilities import (
    CapabilityDeclaration,
    capability_view as _capability_view,
    merge_capabilities,
    validate_claims,
)
from ordessa_server_compat.execution.execution_contract import (
    CancelOutcome, ExecutionObservation, ExecutionReceipt, ExecutionRequest,
)
from ordessa_server_compat.execution.protocols import (
    CANONICAL_PROTOCOLS, CANONICAL_PROTOCOL_SET, MAX_WIRE_PROTOCOLS,
)


class HarnessDescriptorError(ValueError):
    """A deployment seat declared a field the assembly refuses (typed)."""


def _validate_wire_protocols(value: Mapping[str, str]) -> dict[str, str]:
    """Freeze a seat's protocol map to canonical keys in canonical order.

    Every key must be one of the four canonical protocols, every value a
    non-empty native-dialect string, and the map may not exceed the vocabulary.
    A violation is a typed ``HarnessDescriptorError`` the bootstrap turns into
    ``SIDECAR_DEPLOYMENT_INVALID`` - so a production template cannot smuggle a
    second, unchecked protocol dictionary the compatibility derivation would
    silently trust.
    """
    if not isinstance(value, Mapping):
        raise HarnessDescriptorError("wire_protocols must be an object")
    if len(value) > MAX_WIRE_PROTOCOLS:
        raise HarnessDescriptorError("too many wire_protocols declared")
    normalized: dict[str, str] = {}
    for key, dialect in value.items():
        if key not in CANONICAL_PROTOCOL_SET:
            raise HarnessDescriptorError(f"wire_protocols key {key!r} is not canonical")
        if not isinstance(dialect, str) or not dialect:
            raise HarnessDescriptorError(f"wire_protocols value for {key!r} must be non-empty")
        normalized[key] = dialect
    return {name: normalized[name] for name in CANONICAL_PROTOCOLS if name in normalized}


@dataclass(frozen=True)
class HarnessDescriptor:
    """One registered Harness extension as the Server may describe it.

    `capability_claims` is the *static ceiling*: it is validated against the
    versioned canonical contract at construction time, so a production template
    cannot smuggle in a second, unchecked dictionary. Unverified abilities stay
    false rather than defaulting to true.
    """

    harness_type: str
    credential_kind: str | None = None
    # A Harness deployment may declare which provider/model reference control
    # selects the native model.  The Server resolves and freezes that reference
    # generically; the plugin still owns what the native control means.
    model_control_id: str | None = None
    # Optional, declarative adapter environment key.  Credential bytes are
    # never stored in this descriptor or in a configuration object.
    credential_environment: str | None = None
    configuration_validator: Callable[[Any], None] | None = None
    capability_claims: Mapping[str, bool] = field(default_factory=dict)
    # Optional-value controls this Harness declares, in declaration order; the
    # first entry is the access-layer default. Only declared controls are
    # offered, so a client never sees an invented option.
    control_options: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    # Controls a security rule pins; they are reported as locked and cannot be
    # overridden by a Profile default or a temporary override.
    security_locked_controls: tuple[str, ...] = ()
    # Work Order 092: the canonical protocols this Harness can speak, mapped to
    # that family's own native dialect value (e.g. a family whose "openai-chat"
    # is spelled "chat"). Declared only for families whose dialect is pinned in
    # this repo; a family that declares none is *undeclared*, not incompatible.
    wire_protocols: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 声明只能是 canonical id + 真 bool；装配期就失败，而不是等到某次执行
        # 才把漂移写法当成“支持”。校验后按 canonical 次序冻结为普通字典快照。
        object.__setattr__(
            self, "capability_claims", validate_claims(self.capability_claims),
        )
        object.__setattr__(self, "wire_protocols", _validate_wire_protocols(self.wire_protocols))


class HarnessRegistry:
    """Registration state assembled at bootstrap; never brand-switched on."""

    def __init__(self) -> None:
        self._descriptors: dict[str, HarnessDescriptor] = {}

    def register(self, descriptor: HarnessDescriptor) -> None:
        if descriptor.harness_type in self._descriptors:
            raise ValueError(f"harness already registered: {descriptor.harness_type}")
        self._descriptors[descriptor.harness_type] = descriptor

    def get(self, harness_type: str) -> HarnessDescriptor:
        try:
            return self._descriptors[harness_type]
        except KeyError:
            raise KeyError("HARNESS_NOT_REGISTERED") from None

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._descriptors))

    def wire_protocols(self, harness_type: str) -> dict[str, str]:
        """The canonical→native protocol map one Harness seat declared (092).

        Empty means the seat declares none: an *undeclared* family is not
        incompatible, it is unknown, and the Server never blocks on unknown.
        """
        descriptor = self._descriptors.get(harness_type)
        return dict(descriptor.wire_protocols) if descriptor else {}

    def claims_for(self, harness_type: str) -> dict[str, bool]:
        """External-compatible shape: {canonical id: declared}; unknown → {}."""
        return self.canonical_claims(harness_type)

    def canonical_claims(self, harness_type: str) -> dict[str, bool]:
        """registry 派生的 canonical 静态声明（Profile 视图的唯一来源）。"""
        descriptor = self._descriptors.get(harness_type)
        return dict(descriptor.capability_claims) if descriptor else {}

    def capability_declarations(self, harness_type: str) -> tuple[CapabilityDeclaration, ...]:
        """静态 canonical 视图（无任何运行时观测；未注册 → 空）。"""
        descriptor = self._descriptors.get(harness_type)
        if descriptor is None:
            return ()
        return merge_capabilities(descriptor.capability_claims, {})

    def capability_view(self, harness_type: str) -> dict[str, Any]:
        """静态 canonical 视图字典，形状与运行时视图一致。"""
        return _capability_view(harness_type, self.capability_declarations(harness_type))

    def __contains__(self, harness_type: str) -> bool:
        return harness_type in self._descriptors


from .sidecar_backend import SidecarExecutionBackend  # noqa: E402

__all__ = [
    "CancelOutcome", "ExecutionObservation", "ExecutionReceipt", "ExecutionRequest",
    "HarnessDescriptor", "HarnessRegistry", "SidecarExecutionBackend", "TurnExecutionPort",
]
