"""Typed identity refs (E1 §概念, V3 A-01) and the C2 request key.

Identity rules frozen here:

* every ref carries the ``EnvironmentId`` so two data roots can never be
  conflated;
* ``ObjectRef`` carries the full owner instance + generation (A-01: the
  environment being globally unique is NOT assumed — I1/g1/S and I2/g1/S are
  different objects);
* ``RequestKey`` is the C2 logical-request identity: environment persistent
  namespace + authorized principal scope + request id. Restarts, activation
  generations, transport kinds and raw/reliable levels never mint a new key;
  target/binding/guarantee/input digest are *comparison* fields of the same
  key, not part of its identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

#: E + installation-ish local ids: lowercase ascii, dot/dash/underscore.
_LOCAL_ID = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_PRINCIPAL_SCOPE = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")


def _check_local_id(value: str, what: str) -> str:
    if not isinstance(value, str) or not _LOCAL_ID.match(value):
        raise ValueError(f"{what} must match { _LOCAL_ID.pattern!r}: {value!r}")
    return value


@dataclass(frozen=True)
class EnvironmentId:
    """Stable identity of one environment (data root + persistent namespace)."""

    value: str

    def __post_init__(self) -> None:
        _check_local_id(self.value, "EnvironmentId.value")


@dataclass(frozen=True)
class ActivationRef:
    """One plugin activation: E + plugin id + activation generation."""

    environment: str
    plugin_id: str
    generation: int

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "ActivationRef.environment")
        _check_local_id(self.plugin_id, "ActivationRef.plugin_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("ActivationRef.generation must be a non-negative int")


@dataclass(frozen=True)
class ParticipantInstanceRef:
    """A participant instance hosted by one plugin activation (V3 Participant)."""

    environment: str
    instance_id: str
    generation: int

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "ParticipantInstanceRef.environment")
        _check_local_id(self.instance_id, "ParticipantInstanceRef.instance_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("ParticipantInstanceRef.generation must be a non-negative int")


@dataclass(frozen=True)
class SurfaceRef:
    """A published interaction surface: activation/instance + surface + version."""

    environment: str
    surface_id: str
    contract_version: str
    owner: ActivationRef | None = None
    owner_instance: ParticipantInstanceRef | None = None

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "SurfaceRef.environment")
        _check_local_id(self.surface_id, "SurfaceRef.surface_id")
        if not self.owner and not self.owner_instance:
            raise ValueError("SurfaceRef needs an owning activation or instance")


@dataclass(frozen=True)
class ObjectRef:
    """Full-identity object locator — A-01: never keyed by bare object id.

    E + owner instance id + owner generation + object id; a historical ref has
    read-only semantics and grants no invoke right.
    """

    environment: str
    owner_instance_id: str
    owner_generation: int
    object_id: str

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "ObjectRef.environment")
        _check_local_id(self.owner_instance_id, "ObjectRef.owner_instance_id")
        _check_local_id(self.object_id, "ObjectRef.object_id")
        if type(self.owner_generation) is not int or self.owner_generation < 0:
            raise ValueError("ObjectRef.owner_generation must be a non-negative int")


@dataclass(frozen=True)
class ActivityRef:
    """One admitted environment activity, keyed by caller request identity."""

    environment: str
    activity_id: str
    request: "RequestKey | None" = None

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "ActivityRef.environment")
        _check_local_id(self.activity_id, "ActivityRef.activity_id")


@dataclass(frozen=True)
class UsageRef:
    """One usage relation (grantee and rights are fixed at issuance)."""

    environment: str
    usage_id: str

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "UsageRef.environment")
        _check_local_id(self.usage_id, "UsageRef.usage_id")


@dataclass(frozen=True)
class ControlRef:
    """A reverse control request (Q) delivery — one response slot."""

    environment: str
    control_id: str
    delivery_revision: int

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "ControlRef.environment")
        _check_local_id(self.control_id, "ControlRef.control_id")
        if type(self.delivery_revision) is not int or self.delivery_revision < 0:
            raise ValueError("ControlRef.delivery_revision must be a non-negative int")


@dataclass(frozen=True)
class SubscriptionRef:
    """One subscription (observer) — not object ownership."""

    environment: str
    subscription_id: str

    def __post_init__(self) -> None:
        _check_local_id(self.environment, "SubscriptionRef.environment")
        _check_local_id(self.subscription_id, "SubscriptionRef.subscription_id")


@dataclass(frozen=True)
class RequestKey:
    """C2 logical-request identity — stable across restart/generation/transport.

    ``comparison`` holds target/binding/guarantee/input-digest values used to
    DETECT divergence of the same key; a differing comparison never licenses
    a second dispatch of the same key.
    """

    environment_namespace: str
    principal_scope: str
    request_id: str
    comparison: Mapping[str, str] = field(default_factory=dict, compare=True)

    def __post_init__(self) -> None:
        _check_local_id(self.environment_namespace, "RequestKey.environment_namespace")
        if not isinstance(self.principal_scope, str) or not _PRINCIPAL_SCOPE.match(
            self.principal_scope
        ):
            raise ValueError("RequestKey.principal_scope is malformed")
        _check_local_id(self.request_id, "RequestKey.request_id")
