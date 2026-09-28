"""Harness v2's two open contribution handlers.

The Server host declares the points and supplies owner identity. This module
validates payloads and keeps private staged reservations; it never imports host
implementation, publishes on stage, or owns the host's in-use lease authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any
from weakref import WeakSet

from ordessa_harness_api import (
    ConfigurationAdapterDescriptor, FieldClaim, RuntimeAdapterDescriptor,
    ValueSchema, VersionRange,
)
from server_plugin_api import Contribution, ServerContributionHandler

RUNTIME_POINT = "harness.runtime-adapters"
CONFIGURATION_POINT = "harness.configuration-adapters"
POINT_API_VERSION = "v1"
_RUNTIME_METHODS = (
    "describe_installation", "describe_targets", "describe_actions", "prepare_launch",
    "start", "connect", "close", "reconcile", "prepare_reconfiguration", "resume",
)
_CONFIGURATION_METHODS = ("assess", "compile", "verify")


class HarnessContributionError(ValueError):
    """A T04 admission conflict; no registry entry was published."""


_registries_lock = RLock()
_registries: WeakSet[HarnessContributionRegistry] = WeakSet()


def _version_snapshot(value: VersionRange) -> VersionRange:
    return VersionRange(tuple(value.minimum),
                        None if value.maximum is None else tuple(value.maximum))


def _schema_snapshot(value: ValueSchema) -> ValueSchema:
    return ValueSchema(value.kind, value.nullable, tuple(value.enum),
                       tuple((name, _schema_snapshot(schema)) for name, schema in value.properties),
                       tuple(value.required),
                       None if value.items is None else _schema_snapshot(value.items),
                       value.additional_properties)


def _descriptor_snapshot(value: RuntimeAdapterDescriptor | ConfigurationAdapterDescriptor
                         ) -> RuntimeAdapterDescriptor | ConfigurationAdapterDescriptor:
    """Revalidate a detached graph; no author or reader receives registry-owned nodes."""
    if isinstance(value, RuntimeAdapterDescriptor):
        return RuntimeAdapterDescriptor(value.adapter_id, value.api_version,
                                        value.harness_id, tuple(value.aliases),
                                        _version_snapshot(value.supported_versions))
    return ConfigurationAdapterDescriptor(
        value.adapter_id, value.api_version, value.facet_id, value.facet_schema_version,
        value.harness_id, _version_snapshot(value.native_versions),
        _version_snapshot(value.adapter_versions), tuple(value.entries),
        _schema_snapshot(value.payload_schema),
        tuple(FieldClaim(claim.target_kind, claim.target_id, tuple(claim.field_path))
              for claim in value.claims),
    )


def admitted_descriptor(payload: object, owner: str, point: str
                        ) -> RuntimeAdapterDescriptor | ConfigurationAdapterDescriptor:
    """Return the immutable descriptor admitted for this exact published payload.

    The host's public view carries the author's object unchanged. A mutable
    ``payload.descriptor`` therefore cannot be an authority after admission.
    The registry is composition-owned; weak registry references avoid keeping
    retired products alive, while host busy leases keep a viewed registration
    published until its consumer releases it.
    """
    with _registries_lock:
        registries = tuple(_registries)
    matches = []
    for registry in registries:
        with registry._lock:
            matches.extend(entry.descriptor for entry in registry._published
                           if entry.point == point and entry.owner == owner and entry.payload is payload)
    if not matches or any(item != matches[0] for item in matches[1:]):
        raise HarnessContributionError("published Harness adapter identity is unavailable or ambiguous")
    return _descriptor_snapshot(matches[0])


@dataclass(eq=False)
class _Prepared:
    point: str
    owner: str
    payload: object
    descriptor: RuntimeAdapterDescriptor | ConfigurationAdapterDescriptor


def _overlap(left: VersionRange, right: VersionRange) -> bool:
    return (left.maximum is None or left.maximum >= right.minimum) and (
        right.maximum is None or right.maximum >= left.minimum
    )


def _claim_overlap(left: FieldClaim, right: FieldClaim) -> bool:
    # A directory/file collision is conservative: a future codec may write
    # inside the directory. Distinct target IDs have distinct runtime handles.
    if left.target_id != right.target_id:
        return False
    if left.target_kind != right.target_kind and "environment" in (left.target_kind, right.target_kind):
        return False
    a, b = left.field_path, right.field_path
    return a[:len(b)] == b or b[:len(a)] == a


class _Handler(ServerContributionHandler):
    def __init__(self, registry: HarnessContributionRegistry, point: str) -> None:
        self._registry = registry
        self._point = point

    def stage(self, contribution: Contribution, owner: str) -> _Prepared:
        return self._registry._stage(self._point, contribution, owner)

    def commit(self, contribution: Contribution, prepared: _Prepared, owner: str) -> None:
        self._registry._commit(self._point, prepared, owner)

    def rollback(self, contribution: Contribution, prepared: _Prepared, owner: str) -> None:
        self._registry._rollback(self._point, prepared, owner)


class HarnessContributionRegistry:
    """Shared conflict authority behind the two host-bound point handlers.

    Staged reservations only guard competing admissions; consumers see solely
    committed descriptors. The host's published contribution view and
    ``use_contribution`` remain the source of truth for authorization/busy.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._staged: list[_Prepared] = []
        self._published: list[_Prepared] = []
        self.runtime_handler: ServerContributionHandler = _Handler(self, RUNTIME_POINT)
        self.configuration_handler: ServerContributionHandler = _Handler(self, CONFIGURATION_POINT)
        with _registries_lock:
            _registries.add(self)

    def runtime_descriptors(self) -> tuple[RuntimeAdapterDescriptor, ...]:
        with self._lock:
            return tuple(_descriptor_snapshot(entry.descriptor) for entry in self._published
                         if entry.point == RUNTIME_POINT)

    def configuration_descriptors(self) -> tuple[ConfigurationAdapterDescriptor, ...]:
        with self._lock:
            return tuple(_descriptor_snapshot(entry.descriptor) for entry in self._published
                         if entry.point == CONFIGURATION_POINT)

    def _stage(self, point: str, contribution: Contribution, owner: str) -> _Prepared:
        if contribution.point_id != point or contribution.api_version != POINT_API_VERSION:
            raise HarnessContributionError("wrong Harness contribution point or API version")
        if not isinstance(owner, str) or not owner.strip():
            raise HarnessContributionError("host owner is required")
        payload = contribution.payload
        # An author-supplied owner must never supersede the host identity.
        if isinstance(payload, dict) or hasattr(payload, "owner"):
            raise HarnessContributionError("contribution payload may not declare owner")
        descriptor: Any = getattr(payload, "descriptor", None)
        expected = RuntimeAdapterDescriptor if point == RUNTIME_POINT else ConfigurationAdapterDescriptor
        if not isinstance(descriptor, expected):
            raise HarnessContributionError(f"{point} needs {expected.__name__}")
        methods = _RUNTIME_METHODS if point == RUNTIME_POINT else _CONFIGURATION_METHODS
        if any(not callable(getattr(payload, method, None)) for method in methods):
            raise HarnessContributionError(
                f"{point} needs a callable {'RuntimeAdapter' if point == RUNTIME_POINT else 'ConfigurationAdapter'}"
            )
        entry = _Prepared(point, owner, payload, _descriptor_snapshot(descriptor))
        with self._lock:
            for other in (*self._published, *self._staged):
                if other.point == point:
                    self._check_conflict(entry, other)
            self._staged.append(entry)
        return entry

    @staticmethod
    def _check_conflict(entry: _Prepared, other: _Prepared) -> None:
        a, b = entry.descriptor, other.descriptor
        if a.adapter_id == b.adapter_id:
            raise HarnessContributionError(f"adapter_id already registered: {a.adapter_id}")
        if isinstance(a, RuntimeAdapterDescriptor):
            if ({a.harness_id, *a.aliases} & {b.harness_id, *b.aliases}):
                raise HarnessContributionError("canonical Harness or alias already registered")
            return
        if a.harness_id != b.harness_id:
            return
        versions_overlap = _overlap(a.native_versions, b.native_versions) and _overlap(a.adapter_versions, b.adapter_versions)
        if not versions_overlap:
            return
        if a.facet_id == b.facet_id and set(a.entries) & set(b.entries):
            raise HarnessContributionError("facet/entry/version range overlap")
        if any(_claim_overlap(left, right) for left in a.claims for right in b.claims):
            raise HarnessContributionError("native field claims overlap")

    def _commit(self, point: str, prepared: _Prepared, owner: str) -> None:
        with self._lock:
            if prepared.point != point or prepared.owner != owner or prepared not in self._staged:
                raise HarnessContributionError("staged contribution identity changed")
            self._staged.remove(prepared)
            self._published.append(prepared)

    def _rollback(self, point: str, prepared: _Prepared, owner: str) -> None:
        with self._lock:
            if prepared.point != point or prepared.owner != owner:
                raise HarnessContributionError("rollback owner or point mismatch")
            if prepared in self._staged:
                self._staged.remove(prepared)
            if prepared in self._published:
                self._published.remove(prepared)
