"""Adapter inputs: evidence, compile snapshots and observations.

These are the adapter's *own* thin DTOs around the consumed domain types
(`PermissionIntent`, `EffectiveCeiling` from the permissions API) - the domain
records are imported, never redefined here. Every field is load-bearing: a
compile binds to one harness at one measured native version, and a verify
binds to the identity pair (compiled-under, observed) so drift is visible
instead of assumed away.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ordessa_permissions_api import (
    TOOL_KEYS,
    EffectiveCeiling,
    PermissionIntent,
    PolicyRefusal,
    RefusalCode,
)

__all__ = [
    "PiToolCallGateEvidence",
    "PolicyBinding",
    "PolicyCompileSnapshot",
    "PolicyObservation",
    "SupportEvidence",
]

_MISSING = object()


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value.strip()


@dataclass(frozen=True)
class PolicyBinding:
    """Which native pin and which runtime generation an observation is about."""

    native_version: str | None = None
    runtime_generation: str | None = None

    def __post_init__(self) -> None:
        if self.native_version is not None:
            object.__setattr__(self, "native_version",
                               _text(self.native_version, name="native_version"))
        if self.runtime_generation is not None:
            object.__setattr__(self, "runtime_generation",
                               _text(self.runtime_generation, name="runtime_generation"))


@dataclass(frozen=True)
class PiToolCallGateEvidence:
    """One observation of a loaded Pi `tool_call` gate extension.

    The gate is an example extension, not built-in enforcement
    (docs/design/safety-controls/harness-adapters.md row Pi), so this type
    exists only to *name the evidence*; without it Pi policy enforcement is
    unsupported. Nothing constructs it in production yet - that path is the
    G1/G2 seam.
    """

    extension_id: str
    loaded: bool
    interceptable_tool_keys: tuple[str, ...]
    observed_native_version: str
    generation: str | None = None

    @classmethod
    def of(cls, *, extension_id: Any, loaded: Any, interceptable_tool_keys: Any,
           observed_native_version: Any, generation: Any = None) -> "PiToolCallGateEvidence":
        if type(loaded) is not bool:
            raise ValueError("PiToolCallGateEvidence.loaded must be a bool")
        if isinstance(interceptable_tool_keys, (str, bytes)) or \
                not isinstance(interceptable_tool_keys, (tuple, list)):
            raise ValueError("interceptable_tool_keys must be a sequence of tool keys")
        keys = tuple(interceptable_tool_keys)
        if len(set(keys)) != len(keys):
            raise ValueError("interceptable_tool_keys must be unique")
        for key in keys:
            if key not in TOOL_KEYS:
                raise PolicyRefusal(RefusalCode.PERMISSION_UNKNOWN_TOOL,
                                    source="dto.PiToolCallGateEvidence.of",
                                    target=str(key))
        return cls(
            extension_id=_text(extension_id, name="extension_id"),
            loaded=loaded,
            interceptable_tool_keys=keys,
            observed_native_version=_text(observed_native_version,
                                          name="observed_native_version"),
            generation=None if generation is None else _text(generation,
                                                              name="generation"),
        )


@dataclass(frozen=True)
class SupportEvidence:
    """What the caller knows about one harness instance at one pin."""

    harness_id: str
    native_version: str
    pi_tool_call_gate: PiToolCallGateEvidence | None = None

    @classmethod
    def of(cls, *, harness_id: Any, native_version: Any,
           pi_tool_call_gate: Any = None) -> "SupportEvidence":
        if pi_tool_call_gate is not None and \
                not isinstance(pi_tool_call_gate, PiToolCallGateEvidence):
            raise ValueError("pi_tool_call_gate must be a PiToolCallGateEvidence")
        return cls(harness_id=_text(harness_id, name="harness_id"),
                   native_version=_text(native_version, name="native_version"),
                   pi_tool_call_gate=pi_tool_call_gate)


@dataclass(frozen=True)
class PolicyCompileSnapshot:
    """The pure inputs of one `compilePolicy` call (§C1).

    Only the intent, the effective ceiling and the pin identity enter; there
    is deliberately no field a file path, environment or credential could
    ride through.
    """

    harness_id: str
    native_version: str
    intent: PermissionIntent | None = None
    ceiling: EffectiveCeiling | None = None
    evidence: SupportEvidence | None = None

    @classmethod
    def of(cls, *, harness_id: Any, native_version: Any, intent: Any = None,
           ceiling: Any = None, evidence: Any = None) -> "PolicyCompileSnapshot":
        for name, value, kind in (("intent", intent, PermissionIntent),
                                  ("ceiling", ceiling, EffectiveCeiling),
                                  ("evidence", evidence, SupportEvidence)):
            if value is not None and not isinstance(value, kind):
                raise ValueError(f"{name} must be a {kind.__name__} or None")
        return cls(harness_id=_text(harness_id, name="harness_id"),
                   native_version=_text(native_version, name="native_version"),
                   intent=intent, ceiling=ceiling, evidence=evidence)


@dataclass(frozen=True)
class PolicyObservation:
    """What someone *saw* on the native side, bound to the compile it checks."""

    harness_id: str
    compile_binding: PolicyBinding | None = None
    observed_binding: PolicyBinding | None = None
    expected_fields: Mapping[str, Any] = field(default_factory=dict)
    observed_values: Mapping[str, Any] = field(default_factory=dict)
    receipt_confirmed: bool = False
    receipt_source: str | None = None

    @classmethod
    def of(cls, *, harness_id: Any, compile_binding: Any = None,
           observed_binding: Any = None, expected_fields: Any = None,
           observed_values: Any = None, receipt_confirmed: Any = False,
           receipt_source: Any = None) -> "PolicyObservation":
        for name, value in (("compile_binding", compile_binding),
                            ("observed_binding", observed_binding)):
            if value is not None and not isinstance(value, PolicyBinding):
                raise ValueError(f"{name} must be a PolicyBinding")
        for name, value in (("expected_fields", expected_fields),
                            ("observed_values", observed_values)):
            if value is not None and not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
        if type(receipt_confirmed) is not bool:
            raise ValueError("receipt_confirmed must be a bool")
        if receipt_source is not None:
            receipt_source = _text(receipt_source, name="receipt_source")
        return cls(
            harness_id=_text(harness_id, name="harness_id"),
            compile_binding=compile_binding, observed_binding=observed_binding,
            expected_fields=dict(expected_fields or {}),
            observed_values=dict(observed_values or {}),
            receipt_confirmed=receipt_confirmed, receipt_source=receipt_source,
        )
